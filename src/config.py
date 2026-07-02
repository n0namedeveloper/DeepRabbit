"""Configuration for DeepRabbit."""

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
    llm_timeout: int = 120
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
    """Load application settings without crashing module import in test/dev environments."""
    try:
        return Settings()
    except ValidationError:
        return Settings.model_construct(
            deepseek_api_key="dev-deepseek-key",
            github_token="dev-github-token",
            deeprabbit_api_key="dev-deeprabbit-key",
            port=8000,
            host="0.0.0.0",
            workers=1,
            llm_model="deepseek-chat",
            llm_base_url="https://api.deepseek.com/v1",
            llm_timeout=120,
            max_tokens=4096,
            temperature=0.1,
            review_level="normal",
            max_files_per_review=20,
            max_lines_per_file=500,
            max_diff_size=100000,
            github_api_url="https://api.github.com",
            max_comments_per_pr=50,
            max_detail_comments_per_pr=10,
            max_comment_snippet_length=500,
            log_level="INFO",
            structured_logs=True,
        )


settings = _load_settings()
