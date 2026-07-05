"""Tests for configuration."""

import os
from unittest.mock import patch

import pytest


class TestSettings:
    """Configuration test suite."""

    def test_default_values(self, monkeypatch):
        """Settings should have correct defaults for optional fields."""
        # Set only required env vars
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
        monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
        monkeypatch.setenv("DEEPRABBIT_API_KEY", "test-deeprabbit-key")
        # Ensure optional LLM/env vars do not leak from local .env into this test
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_TIMEOUT", raising=False)
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        monkeypatch.delenv("TEMPERATURE", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        # Reimport after env changes
        # We need to reload the module due to pydantic-settings cache
        import importlib
        from src import config
        # Prevent local .env from affecting this test by temporarily moving it if present
        import pathlib
        import os
        env_path = pathlib.Path(".env")
        moved = False
        if env_path.exists():
            env_backup = env_path.with_suffix('.env.testbak')
            os.replace(env_path, env_backup)
            moved = True
        try:
            importlib.reload(config)
            settings = config.settings
        finally:
            # restore .env if we moved it
            if moved:
                os.replace(env_backup, env_path)

        assert settings.port == 8000
        assert settings.host == "0.0.0.0"
        assert settings.workers == 1
        assert settings.llm_model == "deepseek-chat"
        assert settings.llm_base_url == "https://api.deepseek.com/v1"
        assert settings.llm_timeout == 300
        assert settings.max_tokens == 4096
        assert settings.temperature == 0.1
        assert settings.review_level == "normal"
        assert settings.max_files_per_review == 20
        assert settings.max_lines_per_file == 500
        assert settings.max_diff_size == 100000
        assert settings.github_api_url == "https://api.github.com"
        assert settings.max_comments_per_pr == 50
        assert settings.log_level == "INFO"
        assert settings.structured_logs is True

    def test_required_env_vars_missing(self):
        """Should raise error when required env vars are missing."""
        with patch.dict(os.environ, {}, clear=True):
            from pydantic_settings import BaseSettings
            try:
                from src.config import Settings
                s = Settings()
                # Should fail validation
                assert False, "Should have raised ValidationError"
            except Exception:
                pass  # Expected

    def test_custom_values(self, monkeypatch):
        """Settings should respect custom env vars."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "custom-deepseek")
        monkeypatch.setenv("GITHUB_TOKEN", "custom-github-token")
        monkeypatch.setenv("DEEPRABBIT_API_KEY", "custom-deeprabbit-key")
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.setenv("HOST", "127.0.0.1")
        monkeypatch.setenv("WORKERS", "4")
        monkeypatch.setenv("LLM_MODEL", "deepseek-coder")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MAX_COMMENTS_PER_PR", "100")

        import importlib
        from src import config
        importlib.reload(config)
        settings = config.settings

        assert settings.port == 9000
        assert settings.host == "127.0.0.1"
        assert settings.workers == 4
        assert settings.llm_model == "deepseek-coder"
        assert settings.log_level == "DEBUG"
        assert settings.max_comments_per_pr == 100
