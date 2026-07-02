"""Tests for comment generator."""

import pytest

from src.comment_generator import CommentGenerator
from src.models import Issue, IssueType, LineComment, Severity


class TestCommentGenerator:
    """Comment generator test suite."""

    def test_generate_comments_empty_issues(self, comment_generator):
        """Should return empty list when no issues."""
        comments = comment_generator.generate_comments([], {})
        assert comments == []

    def test_generate_comments_skips_issues_without_file(self, comment_generator, sample_issues):
        """Should skip issues that have no file or line."""
        issue_no_file = Issue(
            type=IssueType.BUG,
            severity=Severity.HIGH,
            title="Bug",
            description="Bug description",
            file=None,
            line=None,
        )
        issues = sample_issues + [issue_no_file]
        comments = comment_generator.generate_comments(issues, {})
        # Should only have the two sample issues with file/line
        assert len(comments) == len(sample_issues)

    def test_generate_comments_deduplicates(self, comment_generator, sample_issues):
        """Should deduplicate identical issues."""
        duplicate = Issue(
            type=sample_issues[0].type,
            severity=sample_issues[0].severity,
            title=sample_issues[0].title,
            description=sample_issues[0].description,
            file=sample_issues[0].file,
            line=sample_issues[0].line,
        )
        issues = sample_issues + [duplicate]
        comments = comment_generator.generate_comments(issues, {})
        assert len(comments) == len(sample_issues)

    def test_generate_comments_returns_line_comments(self, comment_generator):
        """Should return LineComment instances."""
        issues = [
            Issue(
                type=IssueType.CODE_SMELL,
                severity=Severity.LOW,
                title="Test Issue",
                description="Description",
                file="test.py",
                line=10,
                category="test",
            )
        ]
        comments = comment_generator.generate_comments(issues, {})
        assert len(comments) == 1
        comment = comments[0]
        assert isinstance(comment, LineComment)
        assert comment.path == "test.py"
        assert comment.line == 10
        assert comment.side == "RIGHT"

    def test_format_comment_critical_security(self, comment_generator):
        """Format a critical security issue."""
        issue = Issue(
            type=IssueType.SECURITY,
            severity=Severity.CRITICAL,
            title="SQL Injection",
            description="User input directly concatenated into query.",
            file="app.py",
            line=25,
            suggestion="Use parameterized queries.",
            category="injection",
        )
        body = comment_generator._format_comment(issue)
        assert "🔴" in body  # Severity emoji
        assert "🔒" in body  # Type emoji
        assert "SQL Injection" in body
        assert "CRITICAL" in body.upper()
        assert "Use parameterized queries" in body

    def test_format_comment_with_code_snippet(self, comment_generator):
        """Format comment with code snippet."""
        issue = Issue(
            type=IssueType.BUG,
            severity=Severity.HIGH,
            title="Potential Null Reference",
            description="Variable may be null.",
            file="app.py",
            line=42,
            code_snippet="result = None\nprint(result.length)",
            category="null_pointer",
        )
        body = comment_generator._format_comment(issue)
        assert "```" in body
        assert "None" in body

    def test_generate_summary_comment(self, comment_generator, sample_issues):
        """Generate overall summary comment."""
        summary = "The code has a few issues to address."
        result = comment_generator.generate_summary_comment(
            sample_issues, summary)
        assert "🐇" in result
        assert "DeepRabbit" in result
        assert "CRITICAL" in result.upper()
        assert "LOW" in result.upper()
        assert "Hardcoded API Key" in result
        assert "Overly Long Function" in result
