"""DeepSeek LLM client for code review."""

import json
import re
import time
import asyncio

import httpx
import structlog

from src.config import settings
from src.models import Issue, IssueType, ReviewLevel, ReviewSummary, Severity

logger = structlog.get_logger()


class DeepSeekClient:
    """Client for DeepSeek LLM API."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = settings.llm_model
        self.timeout = settings.llm_timeout
        self.max_tokens = settings.max_tokens
        self.temperature = settings.temperature

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self.timeout, connect=30),
        )
        logger.info("llm_client.initialized", model=self.model, base_url=self.base_url)

    async def review_diff(
        self,
        diff: str,
        files: list[dict],
        file_contents: dict[str, str],
        review_level: str = ReviewLevel.NORMAL,
        repo_info: str = "",
    ) -> tuple[ReviewSummary, list[Issue]]:
        """Send diff to LLM and parse review results."""
        from src.prompt_templates import SYSTEM_PROMPT, build_review_prompt

        prompt = build_review_prompt(diff, files, file_contents, review_level, repo_info)

        start = time.monotonic()
        response_text = await self._chat_completion(SYSTEM_PROMPT, prompt)
        duration_ms = int((time.monotonic() - start) * 1000)

        logger.info("llm.review.completed", duration_ms=duration_ms, response_length=len(response_text))

        summary, issues = self._parse_review_response(response_text)
        return summary, issues

    async def generate_inline_comment(
        self,
        file_path: str,
        line_content: str,
        line_number: int,
        context_lines: list[str],
        issue: dict,
    ) -> str:
        """Generate a specific inline comment using LLM."""
        from src.prompt_templates import build_inline_comment_prompt

        prompt = build_inline_comment_prompt(
            file_path, line_content, line_number, context_lines, issue
        )
        response = await self._chat_completion(
            "You are a concise code reviewer.", prompt, max_tokens=300
        )
        return response.strip().strip('"').strip("'")

    async def _chat_completion(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
    ) -> str:
        """Make a chat completion request."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = await self.client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500]
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    wait = 5 * (2 ** attempt)
                    logger.warning("llm.rate_limited", attempt=attempt + 1, wait_s=wait)
                    await asyncio.sleep(wait)
                    continue
                logger.error("llm.http_error", status=e.response.status_code, body=body)
                raise
            except (KeyError, IndexError) as e:
                logger.error("llm.response_parse_error", error=str(e))
                raise
    def _parse_review_response(self, text: str) -> tuple[ReviewSummary, list[Issue]]:
        """Parse JSON review response from LLM."""
        text = self._extract_json(text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("llm.invalid_json", text=text[:200])
            return self._fallback_summary(text), []

        summary_data = data.get("summary", {})
        summary = ReviewSummary(
            summary=summary_data.get("summary", "Review completed."),
            issues_found=0,
            rating=summary_data.get("rating", "comment"),
            overall_comment=summary_data.get("overall_comment"),
        )

        issues = []
        for item in data.get("issues", []):
            try:
                issue = Issue(
                    type=IssueType(item.get("type", "code_smell")),
                    severity=Severity(item.get("severity", "medium")),
                    title=item.get("title", "Untitled issue"),
                    description=item.get("description", ""),
                    file=item.get("file"),
                    line=item.get("line"),
                    end_line=item.get("end_line"),
                    suggestion=item.get("suggestion"),
                    code_snippet=item.get("code_snippet"),
                    category=item.get("category"),
                    confidence=item.get("confidence", 0.8),
                )
                issues.append(issue)
            except (ValueError, TypeError) as e:
                logger.warning("llm.issue_parse_error", error=str(e), item=str(item))
                continue

        # Update summary counts
        summary.issues_found = len(issues)
        summary.critical_count = sum(1 for i in issues if i.severity == Severity.CRITICAL)
        summary.high_count = sum(1 for i in issues if i.severity == Severity.HIGH)
        summary.medium_count = sum(1 for i in issues if i.severity == Severity.MEDIUM)
        summary.low_count = sum(1 for i in issues if i.severity == Severity.LOW)
        summary.info_count = sum(1 for i in issues if i.severity == Severity.INFO)
        summary.security_count = sum(1 for i in issues if i.type == IssueType.SECURITY)
        summary.refactoring_suggestions = sum(1 for i in issues if i.type == IssueType.REFACTORING)

        return summary, issues

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from markdown code block or raw text."""
        # Try code block first
        if "```json" in text:
            match = re.search(r"```json\n(.*?)```", text, re.DOTALL)
            if match:
                return match.group(1).strip()
        if "```" in text:
            match = re.search(r"```\n(.*?)```", text, re.DOTALL)
            if match:
                return match.group(1).strip()
        # Try braces matching
        try:
            start = text.index("{")
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        except ValueError:
            pass
        return text

    @staticmethod
    def _fallback_summary(text: str) -> ReviewSummary:
        """Create a fallback summary when JSON parsing fails."""
        return ReviewSummary(
            summary="Could not parse structured review results. Raw response provided.",
            issues_found=0,
            overall_comment=text[:4000],
            rating="comment",
        )
