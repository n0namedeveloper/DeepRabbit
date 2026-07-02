"""Tests for LLM client."""

import json

import pytest

from src.llm_client import DeepSeekClient
from src.models import Issue, IssueType, ReviewLevel, ReviewSummary, Severity


class TestLLMClient:
    """LLM client test suite."""

    def test_extract_json_from_code_block(self):
        """Extract JSON from a markdown code block."""
        text = 'Here is the result:\n```json\n{"key": "value"}\n```\nDone'
        result = DeepSeekClient._extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_plain(self):
        """Extract JSON from plain text."""
        text = '{"key": "value"}'
        result = DeepSeekClient._extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_no_json(self):
        """Return original text if no JSON found."""
        text = 'Just some text'
        result = DeepSeekClient._extract_json(text)
        assert result == text

    def test_parse_review_response_valid(self):
        """Parse a valid JSON review response."""
        response = json.dumps({
            "summary": {
                "summary": "Good code.",
                "rating": "approve",
                "overall_comment": "LGTM",
            },
            "issues": [
                {
                    "type": "bug",
                    "severity": "high",
                    "title": "Null pointer",
                    "description": "Potential NPE",
                    "file": "src/main.py",
                    "line": 42,
                    "suggestion": "Add null check",
                    "category": "null_pointer",
                }
            ],
        })
        client = DeepSeekClient(api_key="test-key")
        summary, issues = client._parse_review_response(response)

        assert isinstance(summary, ReviewSummary)
        assert summary.summary == "Good code."
        assert summary.rating == "approve"
        assert len(issues) == 1

        issue = issues[0]
        assert isinstance(issue, Issue)
        assert issue.type == IssueType.BUG
        assert issue.severity == Severity.HIGH
        assert issue.title == "Null pointer"
        assert issue.line == 42

    def test_parse_review_response_empty_issues(self):
        """Parse response with no issues."""
        response = json.dumps({
            "summary": {
                "summary": "Clean code.",
                "rating": "approve",
            },
            "issues": [],
        })
        client = DeepSeekClient(api_key="test-key")
        summary, issues = client._parse_review_response(response)
        assert len(issues) == 0
        assert summary.rating == "approve"

    def test_parse_review_response_invalid_json(self):
        """Fallback when JSON is invalid."""
        response = "This is not valid JSON at all"
        client = DeepSeekClient(api_key="test-key")
        summary, issues = client._parse_review_response(response)

        assert isinstance(summary, ReviewSummary)
        assert len(issues) == 0
        assert summary.rating == "comment"
        assert "Could not parse" in summary.summary

    def test_parse_review_response_partial_issues(self):
        """Skip malformed issues, keep valid ones."""
        response = json.dumps({
            "summary": {
                "summary": "Review done.",
                "rating": "comment",
            },
            "issues": [
                {
                    "type": "bug",
                    "severity": "high",
                    "title": "Valid issue",
                    "description": "This is valid",
                    "file": "test.py",
                    "line": 1,
                },
                {
                    "type": "invalid_type",  # Will fail IssueType validation
                    "severity": "high",
                    "title": "Invalid issue",
                },
            ],
        })
        client = DeepSeekClient(api_key="test-key")
        summary, issues = client._parse_review_response(response)
        assert len(issues) == 1
        assert issues[0].title == "Valid issue"

    def test_fallback_summary(self):
        """Test fallback summary creation."""
        text = "Raw LLM output here"
        summary = DeepSeekClient._fallback_summary(text)
        assert isinstance(summary, ReviewSummary)
        assert "Could not parse" in summary.summary
        assert summary.overall_comment == text
        assert summary.rating == "comment"

    def test_build_review_prompt(self):
        """Test building the review prompt."""
        from src.prompt_templates import build_review_prompt

        diff = "@@ -1,3 +1,4 @@\n-def foo():\n+def bar():\n     pass"
        files = [{"filename": "test.py", "status": "modified"}]
        file_contents = {"test.py": "def bar():\n    pass\n"}

        prompt = build_review_prompt(
            diff, files, file_contents, ReviewLevel.NORMAL, "test/repo")
        assert "test/repo" in prompt
        assert "test.py" in prompt
        assert ReviewLevel.NORMAL in prompt

    @pytest.mark.asyncio
    async def test_chat_completion_error_handling(self):
        """Test error handling in chat completion."""
        client = DeepSeekClient(
            api_key="invalid-key",
            base_url="https://api.invalid.url/v1",
        )
        with pytest.raises(Exception):
            await client._chat_completion("System", "User message")
