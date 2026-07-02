"""Pydantic models for DeepRabbit."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Issue severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IssueType(str, Enum):
    """Types of code issues."""

    SECURITY = "security"
    PERFORMANCE = "performance"
    BUG = "bug"
    CODE_SMELL = "code_smell"
    CONVENTION = "convention"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    COMPLEXITY = "complexity"


class ReviewLevel(str, Enum):
    """Review strictness levels."""

    LIGHT = "light"
    NORMAL = "normal"
    STRICT = "strict"


class FileChange(BaseModel):
    """A changed file in a PR."""

    filename: str
    status: str  # added, modified, deleted, renamed
    content: str | None = None
    patch: str | None = None
    additions: int = 0
    deletions: int = 0


class LineComment(BaseModel):
    """An inline comment on a specific line."""

    path: str
    line: int
    body: str
    side: str = "RIGHT"  # LEFT = base, RIGHT = head
    start_line: int | None = None
    original_line: int | None = None


class Issue(BaseModel):
    """A detected code issue."""

    type: IssueType
    severity: Severity
    title: str
    description: str = ""
    file: str | None = None
    line: int | None = None
    end_line: int | None = None
    column: int | None = None
    suggestion: str | None = None
    code_snippet: str | None = None
    rule_id: str | None = None
    category: str | None = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ReviewSummary(BaseModel):
    """Overall PR review summary."""

    summary: str
    issues_found: int
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    security_count: int = 0
    refactoring_suggestions: int = 0
    rating: str = "pending"  # approve, comment, request_changes
    overall_comment: str | None = None


class ReviewRequest(BaseModel):
    """Incoming review request payload."""

    repository: str
    pr_number: int
    head_sha: str
    base_sha: str
    diff: str
    files: list[dict[str, Any]]
    file_contents: dict[str, str]
    deepseek_api_key: str
    github_token: str
    review_level: str = "normal"
        llm_base_url: str = ""


class ReviewResult(BaseModel):
    """Response from the review endpoint."""

    success: bool
    summary: ReviewSummary
    issues: list[Issue]
    comments: list[LineComment]
    comments_posted: int = 0
    issues_count: int = 0
    message: str | None = None
    processing_time_ms: int | None = None


class SecurityFinding(BaseModel):
    """A security-related finding."""

    severity: Severity
    tool: str
    rule: str
    message: str
    file: str
    line: int
    column: int | None = None
    code: str | None = None
    remediation: str | None = None


class ComplexityMetrics(BaseModel):
    """Code complexity metrics."""

    file: str
    cyclomatic_complexity: float
    maintainability_index: float
    lines_of_code: int
    functions: list[dict[str, Any]]
