"""Generate GitHub review comments from detected issues."""
import structlog

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


class CommentGenerator:
    """Convert issues into GitHub review comments."""

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
            lines.append(f"```\n{issue.code_snippet[:300]}\n```")
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

    def generate_summary_comment(self, issues: list[Issue], overall_comment: str | None) -> str:
        """Generate an overall markdown summary for the review.

        Includes counts by severity and security/refactor highlights.
        """
        critical = sum(1 for i in issues if getattr(
            i.severity, 'value', str(i.severity)) == Severity.CRITICAL.value)
        high = sum(1 for i in issues if getattr(
            i.severity, 'value', str(i.severity)) == Severity.HIGH.value)
        medium = sum(1 for i in issues if getattr(
            i.severity, 'value', str(i.severity)) == Severity.MEDIUM.value)
        low = sum(1 for i in issues if getattr(
            i.severity, 'value', str(i.severity)) == Severity.LOW.value)
        info = sum(1 for i in issues if getattr(
            i.severity, 'value', str(i.severity)) == Severity.INFO.value)
        security = sum(1 for i in issues if getattr(
            i.type, 'value', str(i.type)) == IssueType.SECURITY.value)
        refactor = sum(1 for i in issues if getattr(
            i.type, 'value', str(i.type)) == IssueType.REFACTORING.value)

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
            for i in issues[:10]:
                lines.append(f"- **{i.title}** — {i.severity.value.upper()}")

        return "\n".join(lines)

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
