"""Security vulnerability scanner for common vulnerabilities.

Uses static pattern matching to detect:
- Secret leaks (API keys, tokens, passwords)
- SQL injection via string formatting/concatenation
- Path traversal from user-controlled paths
- Insecure deserialization (pickle, yaml.load, eval)
- Weak cryptography (MD5, SHA1, DES)
- Cross-site scripting (innerHTML, document.write)
- Server-side request forgery
- Missing authentication on sensitive routes
- Mass assignment vulnerabilities
"""

import re
from pathlib import PurePath

import structlog

from src.models import Issue, IssueType, Severity

logger = structlog.get_logger()

# Patterns for finding secrets in code
SECRET_PATTERNS: list[tuple[str, str, Severity]] = [
    (r"api[_-]?key\s*[:=]\s*['\"]([a-zA-Z0-9_-]{16,})['\"]",
     "Potential API Key", Severity.HIGH),
    (r"secret\s*[:=]\s*['\"]([a-zA-Z0-9_-]{8,})['\"]",
     "Potential Secret", Severity.HIGH),
    (r"password\s*[:=]\s*['\"]([^'\"]{6,})['\"]",
     "Hardcoded Password", Severity.CRITICAL),
    (r"token\s*[:=]\s*['\"]([a-zA-Z0-9_-]{20,})['\"]",
     "Potential Token", Severity.HIGH),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID", Severity.CRITICAL),
    (r"ghp_[a-zA-Z0-9]{36}",
     "GitHub Personal Access Token", Severity.CRITICAL),
    (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth Token", Severity.CRITICAL),
    (r"sk-[a-zA-Z0-9]{48}", "OpenAI API Key", Severity.HIGH),
    (r"rk_live_[a-zA-Z0-9]{24,}", "Stripe Restricted Key", Severity.CRITICAL),
    (r"sk_live_[a-zA-Z0-9]{24,}", "Stripe Secret Key", Severity.CRITICAL),
    (r"(?i)bearer\s+[a-zA-Z0-9\-_.~+/]{30,}",
     "Hardcoded Bearer Token", Severity.HIGH),
    (r"(?i)jdbc:[a-z]+://[^/\s]+/[^\s'\"<>]+",
     "Hardcoded JDBC Connection String", Severity.CRITICAL),
]

# SQL injection patterns
SQLI_PATTERNS: list[tuple[str, str]] = [
    (r"(?:execute|cursor\.execute|raw\b|query)\s*\(\s*['\"].*%",
     "Parameterized query not used"),
    (r'f[\'"].*SELECT.*FROM.*\{.*\}', "SQL via f-string interpolation"),
    (r"\.format\s*\([^)]*\).*(?:SELECT|INSERT|UPDATE|DELETE)",
     "SQL with .format()"),
    (r"\+ \s*['\"].*(?:SELECT|INSERT|UPDATE|DELETE).*\+",
     "SQL via string concatenation"),
]

# Path traversal patterns
PATH_TRAVERSAL_PATTERNS: list[tuple[str, str]] = [
    (r"open\s*\([^)]*\+", "File path built via concatenation"),
    (r"os\.path\.join.*request", "Request data used in path join"),
    (r"Path\s*\(.*request", "Request data used in Path()"),
    (r"send_file\s*\(.*request", "Request data used in send_file()"),
    (r"open\s*\(.*\.format", "File path via .format()"),
]

# Insecure deserialization
INSECURE_DESER_PATTERNS: list[tuple[str, str]] = [
    (r"pickle\.loads?\s*\(", "Unsafe pickle deserialization"),
    (r"yaml\.load\s*\([^)]*\)", "Unsafe YAML loading (use yaml.safe_load)"),
    (r"eval\s*\(\s*request", "eval() on request data"),
    (r"exec\s*\([^)]*\+", "exec() with concatenated input"),
    (r"marshal\.loads?\s*\(", "Unsafe marshal deserialization"),
]

# Weak crypto patterns
WEAK_CRYPTO_PATTERNS: list[tuple[str, str, str]] = [
    (r"hashlib\.md5\s*\(", "MD5 is cryptographically broken", "Use SHA-256 or SHA-3"),
    (r"hashlib\.sha1\s*\(", "SHA-1 is deprecated for security use", "Use SHA-256 or SHA-3"),
    (r"\bDES\b", "DES is insecure (56-bit key)", "Use AES-256-GCM"),
    (r"MODE_ECB", "ECB mode leaks plaintext patterns",
     "Use GCM or CBC mode with random IV"),
    (r"random\.random\s*\(|random\.randint\s*\(", "Insecure randomness",
     "Use secrets module for security-sensitive randomness"),
]

# XSS patterns
XSS_PATTERNS: list[tuple[str, str]] = [
    (r"innerHTML\s*=\s*", "Direct innerHTML assignment"),
    (r"\.html\s*\(\s*[^)]*\+", "jQuery .html() with concatenated data"),
    (r"document\.write\s*\(", "document.write() with user data"),
    (r"dangerouslySetInnerHTML", "React dangerouslySetInnerHTML usage"),
]

# SSRF patterns
SSRF_PATTERNS: list[tuple[str, str]] = [
    (r"requests\.(?:get|post|put|delete|patch)\s*\(\s*[^)]*request",
     "Request data in outgoing HTTP call"),
    (r"urllib\.request\.urlopen\s*\([^)]*request",
     "Request data in urllib call"),
    (r"curl_exec\s*\(\s*[^)]*\$", "User input in curl_exec()"),
]


class SecurityScanner:
    """Static regex-based security scanner for common vulnerability patterns.

    Intended as a fast first-pass filter.  For production use combine with
    Semgrep/CodeQL for deeper data-flow analysis.
    """

    def __init__(self) -> None:
        logger.info("security_scanner.initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_files(self, file_contents: dict[str, str]) -> list[Issue]:
        """Run all static security checks across every file in *file_contents*."""
        issues: list[Issue] = []
        for filename, content in file_contents.items():
            issues.extend(self._scan_secrets(filename, content))
            issues.extend(self._scan_sqli(filename, content))
            issues.extend(self._scan_path_traversal(filename, content))
            issues.extend(self._scan_insecure_deser(filename, content))
            issues.extend(self._scan_weak_crypto(filename, content))
            issues.extend(self._scan_xss(filename, content))
            issues.extend(self._scan_ssrf(filename, content))
            issues.extend(self._scan_auth_bypass(filename, content))
            issues.extend(self._scan_mass_assignment(filename, content))
            issues.extend(self._scan_hardcoded_credentials(filename, content))
        logger.info("security_scanner.completed", total_issues=len(issues))
        return issues

    # ------------------------------------------------------------------
    # Individual scanners
    # ------------------------------------------------------------------

    def _scan_secrets(self, filename: str, content: str) -> list[Issue]:
        return self._match_generic(filename, content, SECRET_PATTERNS,
                                   "Secret Leak", "secret_leak")

    def _scan_sqli(self, filename: str, content: str) -> list[Issue]:
        return self._match_generic(filename, content, SQLI_PATTERNS,
                                   "SQL Injection Vulnerability", "sql_injection",
                                   default_severity=Severity.CRITICAL)

    def _scan_path_traversal(self, filename: str, content: str) -> list[Issue]:
        issues: list[Issue] = []
        for pattern, description in PATH_TRAVERSAL_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line = content[: match.start()].count("\n") + 1
                issues.append(Issue(
                    type=IssueType.SECURITY,
                    severity=Severity.HIGH,
                    title="Path Traversal Risk",
                    description=description,
                    file=filename,
                    line=line,
                    suggestion="Avoid using request-controlled paths directly; validate and normalize inputs.",
                    category="path_traversal",
                    code_snippet=match.group(0)[:120],
                ))
        return issues

    def _scan_insecure_deser(self, filename: str, content: str) -> list[Issue]:
        return self._match_generic(filename, content, INSECURE_DESER_PATTERNS,
                                   "Insecure Deserialization", "insecure_deserialization",
                                   default_severity=Severity.CRITICAL)

    def _scan_weak_crypto(self, filename: str, content: str) -> list[Issue]:
        issues: list[Issue] = []
        for pattern, description, remediation in WEAK_CRYPTO_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line = content[: match.start()].count("\n") + 1
                issues.append(Issue(
                    type=IssueType.SECURITY,
                    severity=Severity.HIGH,
                    title="Weak Cryptography",
                    description=description,
                    file=filename,
                    line=line,
                    suggestion=remediation,
                    category="weak_crypto",
                    code_snippet=match.group(0)[:120],
                ))
        return issues

    def _scan_xss(self, filename: str, content: str) -> list[Issue]:
        return self._match_generic(filename, content, XSS_PATTERNS,
                                   "Cross-Site Scripting (XSS) Risk", "xss",
                                   default_severity=Severity.HIGH)

    def _scan_ssrf(self, filename: str, content: str) -> list[Issue]:
        return self._match_generic(filename, content, SSRF_PATTERNS,
                                   "Server-Side Request Forgery (SSRF)", "ssrf",
                                   default_severity=Severity.HIGH)

    def _scan_auth_bypass(self, filename: str, content: str) -> list[Issue]:
        """Detect sensitive routes lacking authentication guards."""
        issues: list[Issue] = []
        sensitive_routes = r"@app\.(?:route|get|post|put|delete|patch)\s*\([^)]*\b(?:admin|delete|user|account)"
        has_auth = bool(re.search(
            r"@login_required|@require_auth|@jwt_required|check_auth|requires_auth|permission_required",
            content, re.IGNORECASE,
        ))

        for match in re.finditer(sensitive_routes, content, re.IGNORECASE):
            if has_auth:
                continue
            line = content[: match.start()].count("\n") + 1
            issues.append(Issue(
                type=IssueType.SECURITY,
                severity=Severity.MEDIUM,
                title="Missing Authentication on Sensitive Route",
                description="A route handling sensitive data appears unprotected.",
                file=filename,
                line=line,
                suggestion="Add an authentication decorator (e.g. @login_required).",
                category="auth_bypass",
                code_snippet=match.group(0)[:120],
            ))
        return issues

    def _scan_hardcoded_credentials(self, filename: str, content: str) -> list[Issue]:
        """Find credentials that look like real secrets (not placeholders)."""
        issues: list[Issue] = []
        pattern = (
            r"(?:admin|root|password|passwd|db_pass)\s*[:=]\s*['\"]"
            r"(?!\$\{|os\.environ|Config|None|''|\"\"|example|test|changeme|secret|password)"
            r"([^'\"]{4,})['\"]"
        )
        for match in re.finditer(pattern, content, re.IGNORECASE):
            value = match.group(1)
            if value.lower() in ("null", "none", "example", "test", "changeme", "secret", "password"):
                continue
            line = content[: match.start()].count("\n") + 1
            issues.append(Issue(
                type=IssueType.SECURITY,
                severity=Severity.CRITICAL,
                title="Hardcoded Credentials",
                description=f"Hardcoded credential '{value[:20]}…' found in source.",
                file=filename,
                line=line,
                suggestion="Move to environment variables or a secrets manager.",
                category="hardcoded_credentials",
                code_snippet=match.group(0)[:100],
            ))
        return issues

    def _scan_mass_assignment(self, filename: str, content: str) -> list[Issue]:
        """Detect mass-assignment patterns."""
        issues: list[Issue] = []
        patterns = [
            (r"\.create\s*\(\s*\*\*.*request",
             "Direct request data passed to .create()"),
            (r"update\s*\(\s*\*\*.*request",
             "Direct request data passed to update()"),
        ]
        for pat, desc in patterns:
            for match in re.finditer(pat, content, re.IGNORECASE):
                line = content[: match.start()].count("\n") + 1
                issues.append(Issue(
                    type=IssueType.SECURITY,
                    severity=Severity.MEDIUM,
                    title="Mass Assignment Vulnerability",
                    description=desc,
                    file=filename,
                    line=line,
                    suggestion="Explicitly whitelist allowed fields; use Pydantic/SQLAlchemy column allowlists.",
                    category="mass_assignment",
                    code_snippet=match.group(0)[:100],
                ))
        return issues

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_generic(
        filename: str,
        content: str,
        patterns: list[tuple[str, object]],
        title_prefix: str,
        category: str,
        *,
        default_severity: Severity = Severity.HIGH,
    ) -> list[Issue]:
        """Generic pattern-matching loop producing Issue objects."""
        issues: list[Issue] = []
        for entry in patterns:
            pattern = entry[0]
            # Description from tuple (optional, may be absent for 2-tuples)
            description = entry[1] if len(entry) > 1 else ""
            severity = entry[2] if len(
                entry) > 2 else default_severity  # type: ignore[misc]
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line = content[: match.start()].count("\n") + 1
                issues.append(Issue(
                    type=IssueType.SECURITY,
                    severity=severity,
                    title=f"{title_prefix}: {description}" if description else title_prefix,
                    description=(
                        f"{description}. Move secrets to environment variables or a secrets manager."
                        if category == "secret_leak" else description
                    ),
                    file=filename,
                    line=line,
                    suggestion=(
                        "Use environment variables or a secrets manager."
                        if category == "secret_leak"
                        else "Review the highlighted code and apply the remediation described above."
                    ),
                    category=category,
                    code_snippet=match.group(0)[:120],
                ))
        return issues
