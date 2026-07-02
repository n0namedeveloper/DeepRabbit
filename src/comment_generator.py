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
    IssueType.CONVENTION: "📏",
    IssueType.REFACTORING: "🔧",
    IssueType.DOCUMENTATION: "📝",
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
            )
            comments.append(comment)

            if len(comments) >= settings.max_comments_per_pr:
                logger.info("comment_limit_reached", limit=settings.max_comments_per_pr)
                break

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

        if issue.suggestion:
            lines.append(f"**Suggestion:** {issue.suggestion}")
            lines.append("")

        if issue.code_snippet:
            lines.append("**Relevant code:**")
            lines.append(f"```\n{issue.code_snippet[:250]}\n```")

        return "\n".join(lines)

    def generate_summary_comment(
        self,
        issues: list[Issue],
        summary: str,
    ) -> str:
        """Generate a overall PR summary comment."""
        by_severity = {
            Severity.CRITICAL: [],
            Severity.HIGH: [],
            Severity.MEDIUM: [],
            Severity.LOW: [],
            Severity.INFO: [],
        }
        for i in issues:
            by_severity.get(i.severity, by_severity[Severity.INFO]).append(i)

        lines = [
            "## 🐇 DeepRabbit AI Code Review",
            "",
            f"**Summary:** {summary}",
            "",
        ]

        for sev in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]:
            items = by_severity[sev]
            if not items:
                continue
            icon = SEVERITY_EMOJI.get(sev, "")
            lines.append(f"### {icon} {sev.value.upper()} ({len(items)})")
            for issue in items[:5]:
                file_info = f"`{issue.file}:{issue.line}`" if issue.file else ""
                lines.append(f"- **{issue.title}** {file_info}")
            if len(items) > 5:
                lines.append(f"- ... and {len(items) - 5} more")
            lines.append("")

        return "\n".join(lines)
