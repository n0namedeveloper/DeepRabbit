"""GitHub API client for PR interactions with retry/backoff (#6)."""
import asyncio
import base64
from typing import Any

import httpx
import structlog
from github import Auth, Github
from github.PullRequest import PullRequest

from src.config import settings
from src.models import LineComment, ReviewSummary

logger = structlog.get_logger()

# Retry/backoff configuration for transient GitHub API failures (#6)
_RETRYABLE: set[int] = {500, 502, 503, 504}
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0  # seconds (exponential: 1, 2, 4)


class GitHubClient:
    """GitHub API client with PR review capabilities and resilient HTTP."""

    def __init__(self, token: str | None = None):
        self.token = token or settings.github_token
        self.auth = Auth.Token(self.token)
        self.github = Github(auth=self.auth, base_url=settings.github_api_url)
        self._httpx_client: httpx.AsyncClient | None = None
        logger.info("github_client.initialized")

    async def _get_httpx_client(self) -> httpx.AsyncClient:
        """Lazy-init async HTTP client for GitHub REST API calls."""
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(
                base_url=settings.github_api_url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "DeepRabbit/1.0",
                },
                timeout=httpx.Timeout(30.0),
            )
        return self._httpx_client

    # -------------------------------------------------------------------
    # Issue #6: wrapped httpx helpers with retry + exponential backoff
    # -------------------------------------------------------------------
    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        *,
        json: Any = None,
    ) -> httpx.Response:
        """Execute an HTTP request against the GitHub API with retry."""
        client = await self._get_httpx_client()
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                resp = await client.request(method, endpoint, json=json)
                if resp.status_code in _RETRYABLE and attempt < _RETRY_ATTEMPTS - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "github.retry_transient",
                        status=resp.status_code,
                        attempt=attempt + 1,
                        delay=delay,
                        endpoint=endpoint,
                    )
                    await asyncio.sleep(delay)
                    continue
                return resp
            except httpx.HTTPError:
                if attempt < _RETRY_ATTEMPTS - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                raise
        return resp  # type: ignore[return-value]

    async def get_pr(self, repo_name: str, pr_number: int) -> PullRequest:
        """Get a pull request object via thread to avoid blocking."""
        repo = await asyncio.to_thread(self.github.get_repo, repo_name)
        return await asyncio.to_thread(repo.get_pull, pr_number)

    async def post_review(
        self,
        repo_name: str,
        pr_number: int,
        commit_sha: str,
        summary: ReviewSummary,
        comments: list[LineComment],
    ) -> dict:
        """Post a review with inline comments to the PR (with retry)."""
        pr = await self.get_pr(repo_name, pr_number)

        # Build review body
        body = self._build_review_body(summary)

        try:
            # Build review comments using line+side (not position)
            review_comments = []
            for c in comments[: settings.max_comments_per_pr]:
                if c.line and c.line > 0:
                    review_comments.append({
                        "path": c.path,
                        "body": c.body,
                        "line": c.line,
                        "side": c.side if c.side in ("LEFT", "RIGHT") else "RIGHT",
                    })

            endpoint = f"/repos/{repo_name}/pulls/{pr_number}/reviews"
            payload = {
                "commit_id": commit_sha,
                "body": body,
                "event": self._map_rating_to_event(summary.rating),
                "comments": review_comments,
            }

            resp = await self._request_with_retry("POST", endpoint, json=payload)

            if resp.status_code == 422:
                # Inline comment positions failed — post review without comments
                logger.warning(
                    "github.review_inline_failed",
                    status=422,
                    msg="Retrying without inline comments",
                )
                payload["comments"] = []
                resp = await self._request_with_retry("POST", endpoint, json=payload)

            resp.raise_for_status()
            data = resp.json()

            logger.info(
                "github.review_posted",
                pr=pr_number,
                repo=repo_name,
                comments=len(review_comments),
            )
            return {"id": data.get("id"), "state": data.get("state"), "comments_posted": len(review_comments)}

        except httpx.HTTPStatusError as e:
            logger.error(
                "github.review_error",
                status=e.response.status_code,
                body=e.response.text[:500],
            )
            fallback = await asyncio.to_thread(pr.create_issue_comment, body)
            return {"fallback_comment_id": fallback.id}
        except Exception as e:
            logger.error("github.review_error", error=str(e))
            fallback = await asyncio.to_thread(pr.create_issue_comment, body)
            return {"fallback_comment_id": fallback.id}

    async def post_inline_comments(
        self,
        repo_name: str,
        pr_number: int,
        commit_sha: str,
        comments: list[LineComment],
    ) -> int:
        """Post individual review comments on lines (with retry)."""
        pr = await self.get_pr(repo_name, pr_number)
        posted = 0

        for comment in comments[: settings.max_comments_per_pr]:
            try:
                endpoint = f"/repos/{repo_name}/pulls/{pr_number}/comments"
                payload = {
                    "body": comment.body,
                    "commit_id": commit_sha,
                    "path": comment.path,
                    "line": comment.line,
                    "side": comment.side if comment.side in ("LEFT", "RIGHT") else "RIGHT",
                }
                resp = await self._request_with_retry("POST", endpoint, json=payload)
                resp.raise_for_status()
                posted += 1
            except Exception as e:
                logger.warning(
                    "github.comment_error",
                    file=comment.path,
                    line=comment.line,
                    error=str(e),
                )

        return posted

    async def update_labels(
        self,
        repo_name: str,
        pr_number: int,
        summary: ReviewSummary,
    ) -> list[str]:
        """Add relevant labels to the PR based on review results."""
        pr = await self.get_pr(repo_name, pr_number)
        labels: list[str] = []

        if summary.security_count > 0:
            labels.append("deeprabbit-security")
        if summary.refactoring_suggestions > 0:
            labels.append("deeprabbit-refactoring")
        if summary.critical_count > 0 or summary.high_count > 2:
            labels.append("deeprabbit-needs-review")
        if summary.rating == "request_changes":
            labels.append("deeprabbit-changes-requested")

        if labels:
            await asyncio.to_thread(pr.add_to_labels, *labels)
        return labels

    async def post_detail_comments(
        self,
        repo_name: str,
        pr_number: int,
        detail_blocks: list[str],
    ) -> int:
        """Post a list of detailed markdown blocks as separate PR issue comments."""
        pr = await self.get_pr(repo_name, pr_number)
        posted = 0
        for block in detail_blocks[: settings.max_detail_comments_per_pr]:
            try:
                await asyncio.to_thread(pr.create_issue_comment, block)
                posted += 1
            except Exception as e:
                logger.warning(
                    "github.post_detail_failed", pr=pr_number, error=str(e)
                )
        return posted

    def _build_review_body(self, summary: ReviewSummary) -> str:
        """Build markdown review body."""
        lines = [
            "## \ud83d\udc07 DeepRabbit AI Code Review",
            "",
            "### Summary",
            f"{summary.summary}",
            "",
            "### Statistics",
            f"- \ud83d\udd34 Critical: {summary.critical_count}",
            f"- \ud83d\udfe0 High: {summary.high_count}",
            f"- \ud83d\udfe1 Medium: {summary.medium_count}",
            f"- \ud83d\udfe2 Low: {summary.low_count}",
            f"- \u2139\ufe0f Info: {summary.info_count}",
            f"- \ud83d\udd12 Security: {summary.security_count}",
            f"- \ud83d\udd27 Refactoring: {summary.refactoring_suggestions}",
        ]

        return "\n".join(lines)

    def _map_rating_to_event(self, rating: str) -> str:
        """Map our rating to GitHub review event."""
        mapping = {
            "approve": "APPROVE",
            "comment": "COMMENT",
            "request_changes": "REQUEST_CHANGES",
        }
        return mapping.get(rating, "COMMENT")

    async def close(self) -> None:
        """Clean up HTTP client."""
        if self._httpx_client:
            await self._httpx_client.aclose()
