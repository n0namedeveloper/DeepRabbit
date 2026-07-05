"""Configuration for DeepRabbit."""

import os

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys
    deepseek_api_key: str
    github_token: str
    deeprabbit_api_key: str

    # Server
    port: int = 8000
    host: str = "0.0.0.0"
    workers: int = 1

    # LLM
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_timeout: int = 300
    max_tokens: int = 4096
    temperature: float = 0.1

    # Review
    review_level: str = "normal"  # light, normal, strict
    max_files_per_review: int = 20
    max_lines_per_file: int = 500
    max_diff_size: int = 100000  # characters

    # GitHub
    github_api_url: str = "https://api.github.com"
    max_comments_per_pr: int = 50
    max_detail_comments_per_pr: int = Field(default=10, gt=0)
    max_comment_snippet_length: int = Field(default=500, gt=0)

    # Logging
    log_level: str = "INFO"
    structured_logs: bool = True


def _load_settings() -> Settings:
    """Load application settings.

    In production, all required environment variables MUST be present.
    In dev/test mode (DEEPRABBIT_DEV_MODE=1), missing required vars
    fall back to safe dev defaults instead of raising ValidationError.

    Issue #16: model_construct() silent fallback removed. Tests use
    conftest fixtures that either set DEEPRABBIT_DEV_MODE=1 (so missing
    required env vars are replaced by defaults) or monkeypatch
    individual fields on a Settings instance pre-loaded with defaults.
    """
    if os.getenv("DEEPRABBIT_DEV_MODE"):
        return Settings(
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "dev-deepseek-key"),
            github_token=os.getenv("GITHUB_TOKEN", "dev-github-token"),
            deeprabbit_api_key=os.getenv(
                "DEEPRABBIT_API_KEY", "dev-deeprabbit-key"),
        )
    # Production: strict validation, crash loudly if env vars are missing
    return Settings()


settings = _load_settings()
