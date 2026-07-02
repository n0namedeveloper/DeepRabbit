"""GitHub API client for PR interactions."""

import base64
from typing import Any

import httpx
import structlog
from github import Auth, Github
from github.PullRequest import PullRequest

from src.config import settings
from src.models import LineComment, ReviewSummary

logger = structlog.get_logger()


class GitHubClient:
    """GitHub API client with PR review capabilities."""

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

    async def get_pr(self, repo_name: str, pr_number: int) -> PullRequest:
        """Get a pull request object."""
        repo = self.github.get_repo(repo_name)
        return repo.get_pull(pr_number)

    async def post_review(
        self,
        repo_name: str,
        pr_number: int,
        commit_sha: str,
        summary: ReviewSummary,
        comments: list[LineComment],
    ) -> dict:
        """Post a review with inline comments to the PR."""
        pr = await self.get_pr(repo_name, pr_number)

        # Build review body
        body = self._build_review_body(summary)

        # GitHub API limit: use review comments for inline, overall review for summary
        try:
            client = await self._get_httpx_client()
            repo = self.github.get_repo(repo_name)

            # Build the review payload for the GraphQL/REST API
            review_comments = []
            for c in comments[: settings.max_comments_per_pr]:
                review_comments.append({
                    "path": c.path,
                    "body": c.body,
                    "position": c.line if c.side == "RIGHT" else c.original_line,
                })

            endpoint = f"/repos/{repo_name}/pulls/{pr_number}/reviews"
            payload = {
                "commit_id": commit_sha,
                "body": body,
                "event": self._map_rating_to_event(summary.rating),
                "comments": review_comments,
            }

            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

            logger.info(
                "github.review_posted",
                pr=pr_number,
                repo=repo_name,
                comments=len(review_comments),
            )
            return {"id": data.get("id"), "state": data.get("state")}

        except httpx.HTTPStatusError as e:
            logger.error("github.review_error",
                         status=e.response.status_code, body=e.response.text[:500])
            # Fallback: post as regular comment
            fallback = pr.create_issue_comment(body)
            return {"fallback_comment_id": fallback.id}
        except Exception as e:
            logger.error("github.review_error", error=str(e))
            # Fallback: post as regular comment
            fallback = pr.create_issue_comment(body)
            return {"fallback_comment_id": fallback.id}

    async def post_inline_comments(
        self,
        repo_name: str,
        pr_number: int,
        commit_sha: str,
        comments: list[LineComment],
    ) -> int:
        """Post individual review comments on lines."""
        pr = await self.get_pr(repo_name, pr_number)
        posted = 0
        client = await self._get_httpx_client()

        for comment in comments[: settings.max_comments_per_pr]:
            try:
                endpoint = f"/repos/{repo_name}/pulls/{pr_number}/comments"
                payload = {
                    "body": comment.body,
                    "commit_id": commit_sha,
                    "path": comment.path,
                    "line": comment.line,
                    "side": comment.side,
                }
                resp = await client.post(endpoint, json=payload)
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
        labels = []
        if summary.security_count > 0:
            labels.append("deeprabbit-security")
        if summary.refactoring_suggestions > 0:
            labels.append("deeprabbit-refactoring")
        if summary.critical_count > 0 or summary.high_count > 2:
            labels.append("deeprabbit-needs-review")
        if summary.rating == "request_changes":
            labels.append("deeprabbit-changes-requested")

        if labels:
            pr.add_to_labels(*labels)
        return labels

    def _build_review_body(self, summary: ReviewSummary) -> str:
        """Build markdown review body."""
        lines = [
            "## 🐇 DeepRabbit AI Code Review",
            "",
            f"### Summary",
            f"{summary.summary}",
            "",
            "### Statistics",
            f"- 🔴 Critical: {summary.critical_count}",
            f"- 🟠 High: {summary.high_count}",
            f"- 🟡 Medium: {summary.medium_count}",
            f"- 🟢 Low: {summary.low_count}",
            f"- ℹ️ Info: {summary.info_count}",
            f"- 🔒 Security: {summary.security_count}",
            f"- 🔧 Refactoring: {summary.refactoring_suggestions}",
            "",
        ]
        if summary.overall_comment:
            lines.append("### Details")
            lines.append(summary.overall_comment[:4000])
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
