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
        raw = self._extract_json(text)
        logger.info("llm.json_extracted", raw_preview=raw[:100], raw_len=len(raw))
        data = self._try_parse_json(raw)

        if data is None:
            logger.warning("llm.invalid_json", preview=raw[:300])
            return self._fallback_summary(text), []

        logger.info("llm.json_parsed", top_keys=list(data.keys()) if isinstance(data, dict) else "not-dict")

        # Find issues list and summary dict from whatever structure LLM returned
        issues_list, summary_data = self._extract_issues_and_summary(data)

        summary = ReviewSummary(
            summary=summary_data.get("summary", "Review completed."),
            issues_found=0,
            rating=summary_data.get("rating", "comment"),
            overall_comment=summary_data.get("overall_comment"),
        )

        issues = []
        for item in issues_list:
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
                logger.warning("llm.issue_parse_error", error=str(e), item=str(item)[:150])
                continue

        summary.issues_found = len(issues)
        summary.critical_count = sum(1 for i in issues if i.severity == Severity.CRITICAL)
        summary.high_count = sum(1 for i in issues if i.severity == Severity.HIGH)
        summary.medium_count = sum(1 for i in issues if i.severity == Severity.MEDIUM)
        summary.low_count = sum(1 for i in issues if i.severity == Severity.LOW)
        summary.info_count = sum(1 for i in issues if i.severity == Severity.INFO)
        summary.security_count = sum(1 for i in issues if i.type == IssueType.SECURITY)
        summary.refactoring_suggestions = sum(1 for i in issues if i.type == IssueType.REFACTORING)

        logger.info(
            "llm.parse_complete",
            issues_found=len(issues),
            critical=summary.critical_count,
            high=summary.high_count,
            summary_preview=summary.summary[:80],
        )
        return summary, issues

    @staticmethod
    def _extract_issues_and_summary(data: dict) -> tuple[list, dict]:
        """Extract issues list and summary dict from any LLM response structure."""
        if not isinstance(data, dict):
            return [], {}

        # Case 1: {"issues": [...], "summary": {...or str}}
        if "issues" in data and isinstance(data["issues"], list):
            summary_data = data.get("summary", {})
            if isinstance(summary_data, str):
                summary_data = {"summary": summary_data}
            elif not isinstance(summary_data, dict):
                summary_data = {}
            return data["issues"], summary_data

        # Case 2: {"summary": {"summary": "...", "issues": [...], "rating": "..."}}
        if "summary" in data and isinstance(data["summary"], dict):
            inner = data["summary"]
            issues = inner.get("issues", [])
            summary_data = {k: v for k, v in inner.items() if k != "issues"}
            if isinstance(issues, list):
                return issues, summary_data

        # Case 3: search all values for a list of dicts that look like issues
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "severity" in v[0]:
                summary_data = {k: val for k, val in data.items() if not isinstance(val, list)}
                return v, summary_data

        return [], {k: v for k, v in data.items() if isinstance(v, str)}

    @staticmethod
    def _try_parse_json(text: str):
        """Try to parse JSON with multiple fallback strategies."""
        # Strategy 1: direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.debug("llm.json_strategy1_failed", error=str(e)[:80])

        # Strategy 2: strip trailing comma before ] or }
        try:
            cleaned = re.sub(r',\s*([}\]])', r'\1', text)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Strategy 3: close unclosed braces/arrays
        try:
            in_str = False
            esc = False
            depth_brace = 0
            depth_bracket = 0
            last_valid_pos = 0
            for i, ch in enumerate(text):
                if esc:
                    esc = False
                    continue
                if ch == '\\' and in_str:
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == '{':
                    depth_brace += 1
                elif ch == '}':
                    depth_brace -= 1
                    if depth_brace == 0 and depth_bracket == 0:
                        last_valid_pos = i + 1
                elif ch == '[':
                    depth_bracket += 1
                elif ch == ']':
                    depth_bracket -= 1
            if last_valid_pos > 0:
                candidate = text[:last_valid_pos]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
            # Close open structures
            suffix = ']' * max(0, depth_bracket) + '}' * max(0, depth_brace)
            if suffix:
                try:
                    return json.loads(text + suffix)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass

        return None

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON block from LLM response text."""
        # Strip leading/trailing whitespace
        text = text.strip()

        # Code fence with json tag (closed)
        m = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        if m:
            return m.group(1).strip()

        # Code fence without tag (closed)
        m = re.search(r'```\s*\n(.*?)\n```', text, re.DOTALL)
        if m:
            return m.group(1).strip()

        # Code fence unclosed - strip the opening fence and take the rest
        m = re.match(r'```(?:json)?\s*\n?(.*)', text, re.DOTALL)
        if m:
            content = m.group(1).strip()
            # Remove trailing ``` if present
            content = re.sub(r'\n?```\s*$', '', content).strip()
            return content

        # Brace-match from first {
        idx = text.find('{')
        if idx != -1:
            return text[idx:].strip()

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
