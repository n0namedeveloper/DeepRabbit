"""Tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.config import settings
from src.models import ReviewRequest, ReviewResult


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Health check endpoint tests."""

    def test_health_check(self, client):
        """GET /healthz should return ok status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestRootEndpoint:
    """Root endpoint tests."""

    def test_root(self, client):
        """GET / should return service info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "DeepRabbit" in data["service"]
        assert "endpoints" in data
        assert "/review" in data["endpoints"]


class TestReviewEndpoint:
    """Review endpoint tests."""

    def test_review_missing_api_key(self, client):
        """POST /review without API key should return 403."""
        response = client.post("/review", json={})
        assert response.status_code == 403

    def test_review_invalid_api_key(self, client):
        """POST /review with wrong API key should return 401."""
        response = client.post(
            "/review",
            json={},
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401
        assert "Invalid API key" in response.text

    def test_review_invalid_payload(self, client):
        """POST /review with invalid payload should return 422."""
        response = client.post(
            "/review",
            json={"invalid": "data"},
            headers={"X-API-Key": settings.deeprabbit_api_key},
        )
        assert response.status_code == 422


class TestMergeIssues:
    """Issue merging logic tests."""

    def test_merge_empty_list(self):
        """Empty list should return empty list."""
        from src.main import _merge_issues
        assert _merge_issues([]) == []

    def test_merge_deduplicates(self):
        """Duplicate issues should be removed."""
        from src.main import _merge_issues
        from src.models import Issue, IssueType, Severity

        issue = Issue(
            type=IssueType.BUG,
            severity=Severity.HIGH,
            title="Bug",
            description="Desc",
            file="test.py",
            line=1,
        )
        duplicate = Issue(
            type=IssueType.BUG,
            severity=Severity.HIGH,
            title="Bug",
            description="Desc",
            file="test.py",
            line=1,
        )
        result = _merge_issues([issue, duplicate])
        assert len(result) == 1

    def test_merge_sorts_by_severity(self):
        """Issues should be sorted by severity."""
        from src.main import _merge_issues
        from src.models import Issue, IssueType, Severity

        low = Issue(type=IssueType.CONVENTION, severity=Severity.LOW,
                    title="Low", file="a.py", line=1)
        crit = Issue(type=IssueType.SECURITY, severity=Severity.CRITICAL,
                     title="Critical", file="b.py", line=1)
        high = Issue(type=IssueType.BUG, severity=Severity.HIGH,
                     title="High", file="c.py", line=1)

        result = _merge_issues([low, crit, high])
        assert result[0].severity == Severity.CRITICAL
        assert result[1].severity == Severity.HIGH
        assert result[2].severity == Severity.LOW

    def test_merge_different_files(self):
        """Same title on different files should both be kept."""
        from src.main import _merge_issues
        from src.models import Issue, IssueType, Severity

        issue1 = Issue(
            type=IssueType.BUG, severity=Severity.HIGH, title="Bug",
            file="a.py", line=1,
        )
        issue2 = Issue(
            type=IssueType.BUG, severity=Severity.HIGH, title="Bug",
            file="b.py", line=1,
        )
        result = _merge_issues([issue1, issue2])
        assert len(result) == 2
