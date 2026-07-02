"""Tests for the security scanner."""

import pytest

from src.models import IssueType, Severity
from src.security_scanner import SecurityScanner


class TestSecurityScanner:
    """Security scanner test suite."""

    def test_detects_secrets(self, security_scanner, sample_insecure_code):
        issues = security_scanner._scan_secrets("test.py", sample_insecure_code)
        secrets = [i for i in issues if i.category == "secret_leak"]
        assert len(secrets) > 0
        assert any("API Key" in s.title for s in secrets)

    def test_detects_sql_injection(self, security_scanner):
        code = "query = f'SELECT * FROM users WHERE id = {user_id}'"
        issues = security_scanner._scan_sqli("test.py", code)
        assert len(issues) == 1
        assert issues[0].severity == Severity.CRITICAL
        assert "SQL Injection" in issues[0].title

    def test_detects_path_traversal(self, security_scanner):
        code = "open(os.path.join(BASE_DIR, request.files['file']))"
        issues = security_scanner._scan_path_traversal("test.py", code)
        assert len(issues) >= 1
        assert "Path Traversal" in issues[0].title

    def test_detects_insecure_deserialization(self, security_scanner):
        code = "pickle.loads(user_data)"
        issues = security_scanner._scan_insecure_deser("test.py", code)
        assert len(issues) == 1
        assert issues[0].severity == Severity.CRITICAL

    def test_detects_weak_crypto(self, security_scanner):
        code = "hashlib.md5(password.encode()).hexdigest()"
        issues = security_scanner._scan_weak_crypto("test.py", code)
        assert len(issues) == 1
        assert "Weak Cryptography" in issues[0].title

    def test_detects_mass_assignment(self, security_scanner):
        code = "User.create(**request.json)"
        issues = security_scanner._scan_mass_assignment("test.py", code)
        assert len(issues) == 1
        assert issues[0].type == IssueType.SECURITY

    def test_scan_all_returns_issues(self, security_scanner, sample_insecure_code):
        files = {"test.py": sample_insecure_code}
        issues = security_scanner.scan_files(files)
        assert len(issues) > 0
        severities = [i.severity for i in issues]
        assert Severity.CRITICAL in severities or Severity.HIGH in severities
