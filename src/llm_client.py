"""DeepSeek LLM client for code review."""
import json
import re
import time
import asyncio
import hashlib
import os

CACHE_DIR = ".deeprabbit_cache"

def _get_cache_key(system: str, user: str) -> str:
    content = f"{system}|{user}".encode("utf-8")
    return hashlib.sha256(content).hexdigest()

def _get_from_cache(key: str) -> str | None:
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)["content"]
        except Exception:
            pass
    return None

def _save_to_cache(key: str, content: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"content": content}, f)
    except Exception:
        pass


import httpx
import structlog

from src.config import settings
from src.models import Issue, IssueType, ReviewLevel, ReviewSummary, Severity

logger = structlog.get_logger()

CHUNK_SIZE = 30000  # characters per LLM call (#5 diff chunking)


def _split_diff_by_files(diff: str, max_chunk: int = CHUNK_SIZE) -> list[str]:
    """Split a large git diff into chunks by file boundaries.

    Each chunk contains complete diff sections for one or more files.
    Falls back to hard splits when a single file diff is larger than max_chunk.
    """
    if len(diff) <= max_chunk:
        return [diff]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    # Diff format: each file starts with "diff --git a/..."
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            # Start new file block
            if current and current_len > 0:
                chunks.append("\n".join(current))
            current = [line]
            current_len = len(line) + 1
        else:
            current.append(line)
            current_len += len(line) + 1

        # If current chunk exceeds max, split it anyway
        if current_len >= max_chunk:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

    if current and current_len > 0:
        chunks.append("\n".join(current))

    # Merge small chunks to avoid too many API calls
    merged: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for ch in chunks:
        if buf_len + len(ch) <= max_chunk:
            buf.append(ch)
            buf_len += len(ch)
        else:
            if buf:
                merged.append("\n".join(buf))
            buf = [ch]
            buf_len = len(ch)
    if buf:
        merged.append("\n".join(buf))

    return merged if merged else [diff]


def _combine_issues(
    all_issues: list[dict],
    all_summaries: list[dict],
) -> tuple[dict, list[dict]]:
    """Merge results from multiple LLM chunks into a single summary + issues list."""
    # Use the first non-empty summary as base
    base_summary = {}
    for s in all_summaries:
        if s and s.get("summary"):
            base_summary = s
            break
    if not base_summary:
        base_summary = {"summary": "Review completed.", "rating": "comment"}

    # Determine overall rating: worst of all chunks
    rating_order = {"approve": 0, "comment": 1, "request_changes": 2}
    worst_rating = "comment"
    worst_score = 1
    for s in all_summaries:
        r = s.get("rating", "comment") if isinstance(s, dict) else "comment"
        if rating_order.get(r, 1) > worst_score:
            worst_score = rating_order[r]
            worst_rating = r
    base_summary["rating"] = worst_rating

    # Deduplicate issues by file+line+title
    seen = set()
    unique_issues: list[dict] = []
    for issue in all_issues:
        key = (issue.get("file", ""), issue.get(
            "line", 0), issue.get("title", ""))
        if key not in seen:
            seen.add(key)
            unique_issues.append(issue)

    return base_summary, unique_issues


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
        logger.info("llm_client.initialized",
                    model=self.model, base_url=self.base_url)

    async def review_diff(
        self,
        diff: str,
        files: list[dict],
        file_contents: dict[str, str],
        review_level: str = ReviewLevel.NORMAL,
        repo_info: str = "",
    ) -> tuple[ReviewSummary, list[Issue]]:
        """Send diff to LLM and parse review results.

        Large diffs are split into chunks by file boundaries (#5).
        Each chunk gets its own LLM call, results are aggregated.
        """
        from src.prompt_templates import SYSTEM_PROMPT, build_review_prompt

        chunks = _split_diff_by_files(diff)
        logger.info("llm.chunking", total_chunks=len(
            chunks), diff_size=len(diff))

        all_issue_dicts: list[dict] = []
        all_summaries: list[dict] = []

        for idx, chunk_diff in enumerate(chunks):
            prompt = build_review_prompt(
                chunk_diff, files, file_contents, review_level, repo_info,
                chunk_index=idx,
                total_chunks=len(chunks),
            )
            start = time.monotonic()
            response_text = await self._chat_completion(SYSTEM_PROMPT, prompt)
            duration_ms = int((time.monotonic() - start) * 1000)

            logger.info(
                "llm.chunk_completed",
                chunk=idx + 1,
                total=len(chunks),
                duration_ms=duration_ms,
                response_length=len(response_text),
            )

            summary, issues = self._parse_review_response(response_text)
            all_issue_dicts.extend(
                [i.model_dump() if isinstance(i, Issue) else i for i in issues]
            )
            all_summaries.append(
                summary.model_dump() if isinstance(summary, ReviewSummary) else summary
            )

        base_summary, unique_issue_dicts = _combine_issues(
            all_issue_dicts, all_summaries)

        summary = ReviewSummary(
            summary=base_summary.get("summary", "Review completed."),
            issues_found=0,
            rating=base_summary.get("rating", "comment"),
            overall_comment=base_summary.get("overall_comment"),
        )

        issues: list[Issue] = []
        for item in unique_issue_dicts:
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
                logger.warning("llm.issue_parse_error",
                               error=str(e), item=str(item)[:150])
                continue

        # Fill summary counts
        summary.issues_found = len(issues)
        summary.critical_count = sum(
            1 for i in issues if i.severity == Severity.CRITICAL)
        summary.high_count = sum(
            1 for i in issues if i.severity == Severity.HIGH)
        summary.medium_count = sum(
            1 for i in issues if i.severity == Severity.MEDIUM)
        summary.low_count = sum(
            1 for i in issues if i.severity == Severity.LOW)
        summary.info_count = sum(
            1 for i in issues if i.severity == Severity.INFO)
        summary.security_count = sum(
            1 for i in issues if i.type == IssueType.SECURITY)
        summary.refactoring_suggestions = sum(
            1 for i in issues if i.type == IssueType.REFACTORING
        )

        logger.info(
            "llm.parse_complete",
            issues_found=len(issues),
            critical=summary.critical_count,
            high=summary.high_count,
            summary_preview=summary.summary[:80],
        )
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
        """Make a chat completion request with JSON mode (#9)."""
        cache_key = _get_cache_key(system, user)
        cached = _get_from_cache(cache_key)
        if cached:
            logger.info("llm.cache_hit")
            return cached

        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "response_format": {"type": "json_object"},  # Issue #9: JSON Mode
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = await self.client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                _save_to_cache(cache_key, content)
                return content
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500]
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    wait = 5 * (2 ** attempt)
                    logger.warning("llm.rate_limited",
                                   attempt=attempt + 1, wait_s=wait)
                    await asyncio.sleep(wait)
                    continue
                logger.error("llm.http_error",
                             status=e.response.status_code, body=body)
                raise
            except (KeyError, IndexError) as e:
                logger.error("llm.response_parse_error", error=str(e))
                raise

    def _parse_review_response(self, text: str) -> tuple[ReviewSummary, list[Issue]]:
        """Parse JSON review response from LLM."""
        raw = self._extract_json(text)
        logger.info("llm.json_extracted",
                    raw_preview=raw[:100], raw_len=len(raw))
        data = self._try_parse_json(raw)

        if data is None:
            # Attempt targeted extraction of issues array and summary when full JSON parse fails
            logger.warning("llm.invalid_json", preview=raw[:300])
            issues_list = []
            summary_data = {}

            # helper to extract bracket-delimited content starting at idx
            def extract_bracket(s: str, start_idx: int, open_ch: str = '[', close_ch: str = ']') -> str | None:
                depth = 0
                for i, ch in enumerate(s[start_idx:], start_idx):
                    if ch == open_ch:
                        depth += 1
                    elif ch == close_ch:
                        depth -= 1
                        if depth == 0:
                            return s[start_idx:i + 1]
                return None

            # try to find an "issues" array
            m = re.search(r'"issues"\s*:\s*\[', raw)
            if m:
                arr_text = extract_bracket(raw, m.end() - 1, '[', ']')
                if arr_text:
                    try:
                        issues_list = json.loads(arr_text)
                    except Exception:
                        # Try to recover individual JSON objects inside the array
                        issues_list = []
                        objs = []
                        i = 0
                        n = len(arr_text)
                        while i < n:
                            # find next object start
                            if arr_text[i] != '{':
                                i += 1
                                continue
                            depth = 0
                            in_str = False
                            esc = False
                            start = i
                            for j in range(i, n):
                                ch = arr_text[j]
                                if esc:
                                    esc = False
                                    continue
                                if ch == '\\':
                                    esc = True
                                    continue
                                if ch == '"':
                                    in_str = not in_str
                                    continue
                                if in_str:
                                    continue
                                if ch == '{':
                                    depth += 1
                                elif ch == '}':
                                    depth -= 1
                                    if depth == 0:
                                        candidate = arr_text[start:j+1]
                                        try:
                                            objs.append(json.loads(candidate))
                                        except Exception:
                                            pass
                                        i = j + 1
                                        break
                            else:
                                break
                        issues_list = objs

            # try to find a summary object
            m2 = re.search(r'"summary"\s*:\s*\{', raw)
            if m2:
                obj_text = extract_bracket(raw, m2.end() - 1, '{', '}')
                if obj_text:
                    try:
                        summary_data = json.loads(obj_text)
                    except Exception:
                        # Try to extract a simple "summary": "..." string as fallback
                        summary_data = {}
                        mstr = re.search(
                            r'"summary"\s*:\s*"([^"]{10,2000})"', obj_text)
                        if mstr:
                            summary_data = {"summary": mstr.group(1)}

            if not issues_list and not summary_data:
                return self._fallback_summary(text), []

            # Build partial data object even if only some parts were recovered
            data = {"issues": issues_list, "summary": summary_data}
            logger.warning("llm.partial_json_recovered", issues_parsed=len(
                issues_list), has_summary=bool(summary_data))

        logger.info("llm.json_parsed", top_keys=list(data.keys())
                    if isinstance(data, dict) else "not-dict")

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
                logger.warning("llm.issue_parse_error",
                               error=str(e), item=str(item)[:150])
                continue

        summary.issues_found = len(issues)
        summary.critical_count = sum(
            1 for i in issues if i.severity == Severity.CRITICAL)
        summary.high_count = sum(
            1 for i in issues if i.severity == Severity.HIGH)
        summary.medium_count = sum(
            1 for i in issues if i.severity == Severity.MEDIUM)
        summary.low_count = sum(
            1 for i in issues if i.severity == Severity.LOW)
        summary.info_count = sum(
            1 for i in issues if i.severity == Severity.INFO)
        summary.security_count = sum(
            1 for i in issues if i.type == IssueType.SECURITY)
        summary.refactoring_suggestions = sum(
            1 for i in issues if i.type == IssueType.REFACTORING)

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
                summary_data = {
                    k: val for k, val in data.items() if not isinstance(val, list)}
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
