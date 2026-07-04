"""Generate GitHub review comments from detected issues."""
import structlog
from collections import Counter

from src.config import settings
from src.models import Issue, IssueType, LineComment, Severity

logger = structlog.get_logger()


SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "🔵",
    Severity.INFO: "⚪",
}

ISSUE_TYPE_EMOJI = {
    IssueType.SECURITY: "🔒",
    IssueType.PERFORMANCE: "⚡",
    IssueType.BUG: "🐛",
    IssueType.CODE_SMELL: "👃",
    IssueType.CONVENTION: "✒️",
    IssueType.REFACTORING: "🔧",
    IssueType.DOCUMENTATION: "📓",
    IssueType.COMPLEXITY: "🧩",
}


# ---------------------------------------------------------------------------
# Module-level helpers reused across comment-generation methods
# ---------------------------------------------------------------------------

def _normalize_sev(sv) -> str:
    """Normalise a Severity enum or string to its lowercase value."""
    v = getattr(sv, "value", None)
    if v is None:
        v = str(sv)
    return str(v).lower()


def _normalize_type(tp) -> str:
    """Normalise an IssueType enum or string to its lowercase value."""
    v = getattr(tp, "value", None)
    if v is None:
        v = str(tp)
    return str(v).lower()


class CommentGenerator:
    """Convert issues into GitHub review comments."""

    MAX_SNIPPET_LENGTH = 500

    def __init__(self):
        logger.info("comment_generator.initialized")

    def generate_comments(
        self,
        issues: list[Issue],
        file_contents: dict[str, str],
    ) -> list[LineComment]:
        """Generate actionable inline comments from issues."""
        comments = []
        seen = set()

        for issue in issues:
            if not issue.file or not issue.line:
                continue

            key = (issue.file, issue.line, issue.title)
            if key in seen:
                continue
            seen.add(key)

            body = self._format_comment(issue)
            comment = LineComment(
                path=issue.file,
                line=issue.line,
                body=body,
                side="RIGHT",
                original_line=issue.line,
            )
            comments.append(comment)

        logger.info("comments.generated", count=len(comments))
        return comments

    def _format_comment(self, issue: Issue) -> str:
        """Format a single issue into a GitHub comment markdown."""
        severity_icon = SEVERITY_EMOJI.get(issue.severity, "⚪")
        type_icon = ISSUE_TYPE_EMOJI.get(issue.type, "💡")

        lines = [
            f"{severity_icon} {type_icon} **{issue.title}**",
            "",
            f"**Severity:** {issue.severity.value}",
            f"**Category:** {issue.category or 'general'}",
            "",
        ]

        if issue.description:
            lines.append(issue.description)
            lines.append("")

        if issue.code_snippet:
            lines.append("**Relevant code:**")
            lines.append(
                f"```\n{self._trim_snippet(issue.code_snippet, 300)}\n```")
            lines.append("")

        if issue.suggestion:
            # Extract just the code part from suggestion if it contains one
            suggestion_code = self._extract_suggestion_code(issue.suggestion)
            if suggestion_code:
                # Render as GitHub suggestion block (shows Apply button in PR)
                lines.append("**Suggested fix:**")
                lines.append(f"```suggestion\n{suggestion_code}\n```")
            else:
                lines.append(f"**Suggestion:** {issue.suggestion}")

        return "\n".join(lines)

    def _count_issues(self, issues: list[Issue]) -> tuple[Counter, Counter]:
        """Count issues by severity and type, returning (sev_counter, type_counter)."""
        sev_counter: Counter = Counter()
        type_counter: Counter = Counter()
        for it in issues:
            sev_counter[_normalize_sev(it.severity)] += 1
            type_counter[_normalize_type(it.type)] += 1
        return sev_counter, type_counter

    def generate_summary_comment(self, issues: list[Issue], overall_comment: str | None) -> str:
        """Generate an overall markdown summary for the review.

        Includes counts by severity and security/refactor highlights.
        """
        sev_counter, type_counter = self._count_issues(issues)

        critical = sev_counter.get("critical", 0)
        high = sev_counter.get("high", 0)
        medium = sev_counter.get("medium", 0)
        low = sev_counter.get("low", 0)
        info = sev_counter.get("info", 0)
        security = type_counter.get("security", 0)
        refactor = type_counter.get("refactoring", 0)

        lines = [
            "## 🐇 DeepRabbit AI Code Review",
            "",
            "### Summary",
            overall_comment or "No overall comment provided.",
            "",
            "### Statistics",
            f"- 🔴 Critical: {critical}",
            f"- 🟠 High: {high}",
            f"- 🟡 Medium: {medium}",
            f"- 🟢 Low: {low}",
            f"- ℹ️ Info: {info}",
            f"- 🔒 Security: {security}",
            f"- 🔧 Refactoring: {refactor}",
            "",
        ]

        if issues:
            lines.append("### Top issues")
            # Include short blocks for top issues with code snippets and suggestions
            for i in issues[:10]:
                sev = _normalize_sev(i.severity).upper()
                location = f"{i.file}:{i.line}" if i.file and i.line else (
                    i.file or "")
                lines.append(f"- **{i.title}** — {sev} — {location}")
                if i.description:
                    lines.append(f"\n    {i.description}")
                if i.code_snippet:
                    lines.append("\n**Relevant code:**")
                    lines.append(f"```\n{i.code_snippet[:400]}\n```")
                if i.suggestion:
                    suggestion_code = self._extract_suggestion_code(
                        i.suggestion)
                    if suggestion_code:
                        lines.append("\n**Suggested fix:**")
                        lines.append(
                            f"```suggestion\n{suggestion_code}\n```")
                    else:
                        lines.append(
                            f"\n**Suggestion:** {i.suggestion}")

            # Add a short "Summary of Key Findings" with bullets
            lines.append("")
            lines.append("### Summary of Key Findings:")
            lines.append("")
            for i in issues[:10]:
                short = i.suggestion or i.description or "No details provided."
                short_line = short.splitlines()[0]
                lines.append(f"- {i.title}: {short_line}")

        return "\n".join(lines)

    def generate_summary_body(self, issues: list[Issue], overall_comment: str | None) -> str:
        """Generate a compact summary body without detailed fix blocks."""
        sev_counter, type_counter = self._count_issues(issues)

        critical = sev_counter.get(Severity.CRITICAL.value, 0)
        high = sev_counter.get(Severity.HIGH.value, 0)
        medium = sev_counter.get(Severity.MEDIUM.value, 0)
        low = sev_counter.get(Severity.LOW.value, 0)
        info = sev_counter.get(Severity.INFO.value, 0)
        security = type_counter.get(IssueType.SECURITY.value, 0)
        refactor = type_counter.get(IssueType.REFACTORING.value, 0)

        lines = [
            "## 🐇 DeepRabbit AI Code Review",
            "",
            "### Summary",
            overall_comment or "No overall comment provided.",
            "",
            "### Statistics",
            f"- 🔴 Critical: {critical}",
            f"- 🟠 High: {high}",
            f"- 🟡 Medium: {medium}",
            f"- 🟢 Low: {low}",
            f"- ℹ️ Info: {info}",
            f"- 🔒 Security: {security}",
            f"- 🔧 Refactoring: {refactor}",
        ]

        return "\n".join(lines)

    def generate_detail_blocks(self, issues: list[Issue]) -> list[str]:
        """Generate separate markdown blocks for each issue's fix suggestion.

        Each block is intended to be posted as an individual PR comment.
        """
        blocks: list[str] = []
        if not issues:
            return blocks

        for idx, i in enumerate(issues, 1):
            parts: list[str] = []
            sev_emoji = SEVERITY_EMOJI.get(i.severity, "⚪")
            location = f"{i.file}:{i.line}" if i.file and i.line else (
                i.file or "unknown")
            parts.append(f"#### {idx}. {sev_emoji} {i.title}")
            parts.append(
                f"**Location:** {location} | **Severity:** {self._severity_label(i)}")
            parts.append("")

            if i.description:
                parts.append(i.description)
                parts.append("")

            if i.code_snippet:
                parts.append("**Problematic code:**")
                parts.append(
                    f"```python\n{self._trim_snippet(i.code_snippet, self.MAX_SNIPPET_LENGTH)}\n```")
                parts.append("")

            if i.suggestion:
                suggestion_code = self._extract_suggestion_code(i.suggestion)
                if suggestion_code:
                    parts.append("**Suggested fix:**")
                    parts.append(
                        f"```suggestion\n{self._trim_snippet(suggestion_code, self.MAX_SNIPPET_LENGTH)}\n```")
                else:
                    parts.append("**Suggested fix:**")
                    parts.append(i.suggestion)
                parts.append("")

            blocks.append("\n".join(parts))

        return blocks

    @staticmethod
    def _extract_suggestion_code(suggestion: str) -> str | None:
        """Extract code from suggestion text if it contains a code block."""
        import re
        # Look for explicit code block
        match = re.search(r"```(?:\w+)?\n(.*?)```", suggestion, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Look for inline code with backticks spanning multiple lines
        match = re.search(r"`([^`]{10,})`", suggestion)
        if match:
            return match.group(1).strip()
        # If suggestion itself looks like code (starts with keyword or indent)
        stripped = suggestion.strip()
        code_starters = (
            "cursor.execute(",
            "conn.execute(",
            "stmt ",
            "query ",
            "SELECT ",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "import ",
            "from ",
            "def ",
            "class ",
        )
        if any(stripped.startswith(s) for s in code_starters):
            return stripped
        return None

    @staticmethod
    def _severity_label(issue: Issue) -> str:
        return getattr(issue.severity, "value", str(issue.severity)).upper()

    @staticmethod
    def _trim_snippet(snippet: str, limit: int, indent: str = "") -> str:
        """Trim a snippet to a safe length while preserving readability."""
        text = snippet[:limit]
        if len(snippet) > limit:
            text += "\n... (truncated)"
        if indent:
            return "\n".join(f"{indent}{line}" for line in text.splitlines())
        return text
