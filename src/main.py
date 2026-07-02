"""DeepRabbit FastAPI server entrypoint."""

import time

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

        # ---------- Phase 1: Static Security Scan ----------
        security_scanner = SecurityScanner()
        security_issues = security_scanner.scan_files(payload.file_contents)
        logger.info("security.scan_complete",
                    issues_found=len(security_issues))

        # ---------- Phase 2: Code Quality Analysis ----------
        code_analyzer = CodeAnalyzer()
        quality_issues = code_analyzer.analyze(payload.file_contents)
        complexity_metrics = code_analyzer.get_complexity_metrics(
            payload.file_contents)
        logger.info("quality.scan_complete", issues_found=len(quality_issues))

        if complexity_metrics:
            logger.debug("complexity.metrics", files=len(complexity_metrics))

        # ---------- Phase 3: LLM-Powered Review ----------
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

        # Build a rich overall summary comment (compact) and post detailed
        # fix-suggestion blocks as separate PR comments to avoid one huge body.
        try:
            summary_markdown = comment_gen.generate_summary_comment(
                all_issues, llm_summary.overall_comment)
            # Keep only the top portion (before detailed Fix Suggestions)
            split_token = "\n### Fix Suggestions"
            if split_token in summary_markdown:
                top, _details = summary_markdown.split(split_token, 1)
                llm_summary.overall_comment = top.strip()
            else:
                llm_summary.overall_comment = summary_markdown

            # Prepare per-issue detail blocks and post them as separate comments
            detail_blocks = comment_gen.generate_detail_blocks(all_issues)
        except Exception:
            logger.warning("comment_generator.summary_failed")
            detail_blocks = []

        # ---------- Phase 6: Post to GitHub ----------
        github = GitHubClient(token=payload.github_token)
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
    )
