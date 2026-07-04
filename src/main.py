"""DeepRabbit FastAPI server entrypoint."""

import asyncio
import signal
import uuid
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.code_analyzer import CodeAnalyzer
from src.comment_generator import CommentGenerator
from src.config import settings
from src.github_client import GitHubClient
from src.llm_client import DeepSeekClient
from src.models import ReviewRequest, ReviewResult, ReviewSummary
from src.security_scanner import SecurityScanner

logger = structlog.get_logger()

app = FastAPI(
    title="DeepRabbit",
    description="AI-powered autonomous code review API",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Correlation ID middleware (issue #12)
# ---------------------------------------------------------------------------
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


@app.middleware("http")
async def correlation_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
) -> JSONResponse:
    """Inject a correlation id into every request and attach it to structlog."""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request_id_ctx.set(rid)
    structlog.contextvars.bind_contextvars(request_id=rid)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        structlog.contextvars.unbind_contextvars("request_id")


async def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    """Validate API key from request header."""
    if x_api_key is None:
        raise HTTPException(status_code=403, detail="API key required")
    if x_api_key != settings.deeprabbit_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


@app.get("/healthz")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/")
async def root() -> dict:
    """Root endpoint with service info."""
    return {
        "service": "DeepRabbit",
        "description": "AI-powered autonomous code review",
        "endpoints": ["/healthz", "/review"],
    }


@app.post("/review", response_model=ReviewResult)
async def review_pr(
    request: Request,
    payload: ReviewRequest,
    api_key: str = Depends(verify_api_key),
) -> ReviewResult:
    """Main review endpoint — orchestrates the full code review pipeline."""
    start_time = time.monotonic()
    processing_time_ms: int | None = None

    # Initialize all variables for potential exception handling
    security_issues: list = []
    quality_issues: list = []
    llm_issues: list = []
    llm_summary = ReviewSummary(
        summary="",
        issues_found=0,
        rating="comment",
        overall_comment="Review did not produce a summary.",
    )
    all_issues: list = []
    comments: list = []

    try:
        logger.info(
            "review.started",
            repo=payload.repository,
            pr=payload.pr_number,
            files=len(payload.files),
            level=payload.review_level,
        )

        # ---------- Issue #2: max_files_per_review enforcement ----------
        if len(payload.files) > settings.max_files_per_review:
            raise HTTPException( 
                status_code=400,
                detail=f"Too many files ({len(payload.files)}). "
                f"Limit is {settings.max_files_per_review}.",
            )

        # ---------- Issue #11: Server-side Fetch implementation ----------
        github = GitHubClient(token=payload.github_token)
        
        if payload.server_side_fetch:
            logger.info("server_side_fetch.started", repo=payload.repository, pr=payload.pr_number)
            try:
                pr = await github.get_pr(payload.repository, payload.pr_number)
                
                # Fetch files
                fetched_files = []
                fetched_contents = {}
                
                # pygithub doesn't directly offer a fast raw diff string as an attribute of PullRequest,
                # but we can get it via the API or by requesting the diff media type.
                # However, pygithub files list provides the patches and filenames.
                pr_files = await asyncio.to_thread(pr.get_files)
                # Note: We use list conversion or loop inside to_thread or cleanly iterate
                for pf in await asyncio.to_thread(list, pr_files):
                    # Filter deleted files and binary files
                    # Check if filename is binary
                    from scripts.send_review import _is_binary
                    if pf.status == 'removed' or _is_binary(pf.filename):
                        continue
                    
                    fetched_files.append({
                        "filename": pf.filename,
                        "status": pf.status
                    })
                    
                    # Fetch content of the head_sha version
                    try:
                        repo = await asyncio.to_thread(github.github.get_repo, payload.repository)
                        content_file = await asyncio.to_thread(repo.get_contents, pf.filename, ref=payload.head_sha)
                        if content_file and not isinstance(content_file, list):
                            raw_content = content_file.decoded_content.decode('utf-8', errors='replace')
                            fetched_contents[pf.filename] = raw_content
                    except Exception as e:
                        logger.warning("server_side_fetch.content_failed", file=pf.filename, error=str(e))
                
                # Construct a simulated diff from the file patches if needed
                simulated_diff = ""
                for pf in await asyncio.to_thread(list, pr_files):
                    if pf.patch:
                        simulated_diff += f"diff --git a/{pf.filename} b/{pf.filename}\n"
                        simulated_diff += f"--- a/{pf.filename}\n+++ b/{pf.filename}\n"
                        simulated_diff += pf.patch + "\n"
                
                payload.files = fetched_files
                payload.file_contents = fetched_contents
                payload.diff = simulated_diff
                
                logger.info("server_side_fetch.success", files_fetched=len(fetched_files))
            except Exception as e:
                logger.error("server_side_fetch.failed", error=str(e))
                raise HTTPException(status_code=500, detail=f"Server-side fetch failed: {str(e)}")

        # ---------- Phase 1 & 2: Parallel static analysis (issue #15) ----------
        async def run_security_scan() -> list:
            return await asyncio.to_thread(
                SecurityScanner().scan_files, payload.file_contents
            )

        async def run_code_analyzer() -> list:
            return await asyncio.to_thread(
                CodeAnalyzer().analyze, payload.file_contents
            )

        security_issues, quality_issues = await asyncio.gather(
            run_security_scan(), run_code_analyzer()
        )

        logger.info(
            "static_analysis.complete",
            security_issues=len(security_issues),
            quality_issues=len(quality_issues),
        )

        # Complexity metrics (run synced after analyze for now, but non-blocking)
        code_analyzer = CodeAnalyzer()
        complexity_metrics = await asyncio.to_thread(
            code_analyzer.get_complexity_metrics, payload.file_contents
        )
        if complexity_metrics:
            logger.debug("complexity.metrics", files=len(complexity_metrics))

        # ---------- Phase 3: LLM-Powered Review (with chunking - issue #5) ----------
        llm = DeepSeekClient(
            api_key=payload.deepseek_api_key,
            base_url=payload.llm_base_url or settings.llm_base_url,
        )
        llm_summary, llm_issues = await llm.review_diff(
            diff=payload.diff,
            files=payload.files,
            file_contents=payload.file_contents,
            review_level=payload.review_level,
            repo_info=payload.repository,
        )
        logger.info("llm.review_complete", issues_found=len(llm_issues))

        # ---------- Phase 4: Merge & Deduplicate Issues ----------
        all_issues = _merge_issues(
            security_issues + quality_issues + llm_issues)
        logger.info("issues.merged", total=len(all_issues))

        # ---------- Phase 5: Generate Comments ----------
        comment_gen = CommentGenerator()
        comments = comment_gen.generate_comments(
            all_issues, payload.file_contents
        )
        logger.info("comments.generated", count=len(comments))

        # Build a compact summary body and post detailed fix-suggestion blocks
        # as separate PR comments.
        try:
            summary_markdown = comment_gen.generate_summary_body(
                all_issues, llm_summary.overall_comment)
            llm_summary.overall_comment = summary_markdown
            detail_blocks = comment_gen.generate_detail_blocks(all_issues)
        except Exception:
            logger.warning("comment_generator.summary_failed")
            detail_blocks = []

        # ---------- Phase 6: Post to GitHub ----------
        # Re-use the existing github client instance
        posted = await github.post_review( 
            repo_name=payload.repository,
            pr_number=payload.pr_number,
            commit_sha=payload.head_sha,
            summary=llm_summary,
            comments=comments,
        )
        # Post detailed per-issue suggestion blocks as separate issue comments
        if detail_blocks:
            try:
                detail_posted = await github.post_detail_comments(
                    payload.repository, payload.pr_number, detail_blocks
                )
                # include count in result metadata
                posted["detail_comments_posted"] = detail_posted
            except Exception:
                logger.warning("github.post_detail_comments_failed")
        logger.info("github.review_posted", result=posted)

        # Update PR labels
        await github.update_labels(payload.repository, payload.pr_number, llm_summary)

        # Clean up HTTP clients
        await github.close()

        processing_time_ms = int((time.monotonic() - start_time) * 1000)

        result = ReviewResult(
            success=True,
            summary=llm_summary,
            issues=all_issues,
            comments=comments,
            comments_posted=posted.get("comments_posted", len(comments)),
            issues_count=len(all_issues),
            message="Review completed successfully",
            processing_time_ms=processing_time_ms,
        )

        logger.info(
            "review.completed",
            repo=payload.repository,
            pr=payload.pr_number,
            time_ms=processing_time_ms,
            issues=len(all_issues),
        )
        return result

    except Exception as exc:
        processing_time_ms = int((time.monotonic() - start_time) * 1000)
        logger.error(
            "review.failed",
            repo=payload.repository,
            pr=payload.pr_number,
            error=str(exc),
            time_ms=processing_time_ms,
        )
        return ReviewResult(
            success=False,
            summary=llm_summary,
            issues=all_issues or (security_issues + quality_issues),
            comments=comments,
            issues_count=len(all_issues or (security_issues + quality_issues)),
            message=f"Review failed: {exc}",
            processing_time_ms=processing_time_ms,
        )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions gracefully."""
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )


def _merge_issues(issues: list) -> list:
    """Deduplicate and sort issues by severity."""
    seen = set()
    unique = []
    for issue in issues:
        key = (
            issue.file or "",
            issue.line or 0,
            issue.title,
        )
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    severity_order = {"critical": 0, "high": 1,
                      "medium": 2, "low": 3, "info": 4}
    unique.sort(key=lambda i: severity_order.get(i.severity.value, 5))
    return unique


# ---------------------------------------------------------------------------
# Background task tracking for graceful shutdown (issue #13)
# ---------------------------------------------------------------------------
_background_tasks: set[asyncio.Task] = set()


def _on_signal() -> None:
    """Cancel all tracked background tasks when shutdown signal is received."""
    logger.info("shutdown.signal_received", tasks=len(_background_tasks))
    for task in list(_background_tasks):
        if not task.done():
            task.cancel()


def _setup_graceful_shutdown() -> None:
    """Register SIGTERM/SIGINT handlers for graceful shutdown."""
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _on_signal)
            except NotImplementedError:
                # Windows does not support add_signal_handler for SIGTERM
                signal.signal(sig, lambda signum, frame: _on_signal())
    except RuntimeError:
        # No running event loop (e.g. during import or test collection)
        # Fall back to standard signal module registration
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda signum, frame: _on_signal())
            except ValueError:
                # Not in main thread, ignore
                pass


_setup_graceful_shutdown()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
    )
