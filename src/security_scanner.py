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

# ── Binary file extensions to skip ──────────────────────────────────
BINARY_EXTENSIONS: set[str] = {
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp', '.bmp', '.tiff',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.jar', '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.exe', '.dll', '.so', '.dylib', '.o', '.a', '.lib',
    '.pyc', '.pyo', '.pyd',
    '.whl', '.egg', '.deb', '.rpm',
    '.mp3', '.mp4', '.avi', '.mov', '.wav', '.flac',
    '.min.js', '.min.css',
}


def _is_binary_file(filename: str) -> bool:
    """Check if a file should be skipped (binary or minified)."""
    return any(filename.lower().endswith(ext) for ext in BINARY_EXTENSIONS)


# ── Pre-compiled regex patterns ─────────────────────────────────────
# Format: (compiled_regex, description, severity)
SECRET_PATTERNS: list[tuple[re.Pattern, str, Severity]] = [
    (re.compile(
        r"api[_-]?key\s*[:=]\s*['\"]([a-zA-Z0-9_-]{16,})['\"]", re.IGNORECASE), "Potential API Key", Severity.HIGH),
    (re.compile(r"secret\s*[:=]\s*['\"]([a-zA-Z0-9_-]{8,})['\"]",
     re.IGNORECASE), "Potential Secret", Severity.HIGH),
    (re.compile(r"password\s*[:=]\s*['\"]([^'\"]{6,})['\"]",
     re.IGNORECASE), "Hardcoded Password", Severity.CRITICAL),
    (re.compile(r"token\s*[:=]\s*['\"]([a-zA-Z0-9_-]{20,})['\"]",
     re.IGNORECASE), "Potential Token", Severity.HIGH),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID", Severity.CRITICAL),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"),
     "GitHub Personal Access Token", Severity.CRITICAL),
    (re.compile(r"gho_[a-zA-Z0-9]{36}"),
     "GitHub OAuth Token", Severity.CRITICAL),
    (re.compile(r"sk-[a-zA-Z0-9]{48}"), "OpenAI API Key", Severity.HIGH),
    (re.compile(r"rk_live_[a-zA-Z0-9]{24,}"),
     "Stripe Restricted Key", Severity.CRITICAL),
    (re.compile(r"sk_live_[a-zA-Z0-9]{24,}"),
     "Stripe Secret Key", Severity.CRITICAL),
    (re.compile(r"bearer\s+[a-zA-Z0-9\-_.~+/]{30,}",
     re.IGNORECASE), "Hardcoded Bearer Token", Severity.HIGH),
    (re.compile(r"jdbc:[a-z]+://[^/\s]+/[^\s'\"<>]+", re.IGNORECASE),
     "Hardcoded JDBC Connection String", Severity.CRITICAL),
]

# SQL injection patterns (pre-compiled)
SQLI_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"(?:execute|cursor\.execute|raw\b|query)\s*\(\s*['\"].*%", re.IGNORECASE), "Parameterized query not used"),
    (re.compile(r'f[\'"].*SELECT.*FROM.*\{.*\}',
     re.IGNORECASE), "SQL via f-string interpolation"),
    (re.compile(r"\.format\s*\([^)]*\).*(?:SELECT|INSERT|UPDATE|DELETE)",
     re.IGNORECASE), "SQL with .format()"),
    (re.compile(r"\+ \s*['\"].*(?:SELECT|INSERT|UPDATE|DELETE).*\+",
     re.IGNORECASE), "SQL via string concatenation"),
]

# Path traversal patterns (pre-compiled)
PATH_TRAVERSAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"open\s*\([^)]*\+", re.IGNORECASE),
     "File path built via concatenation"),
    (re.compile(r"os\.path\.join.*request", re.IGNORECASE),
     "Request data used in path join"),
    (re.compile(r"Path\s*\(.*request", re.IGNORECASE), "Request data used in Path()"),
    (re.compile(r"send_file\s*\(.*request", re.IGNORECASE),
     "Request data used in send_file()"),
    (re.compile(r"open\s*\(.*\.format", re.IGNORECASE), "File path via .format()"),
]

# Insecure deserialization (pre-compiled)
INSECURE_DESER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"pickle\.loads?\s*\(", re.IGNORECASE),
     "Unsafe pickle deserialization"),
    (re.compile(r"yaml\.load\s*\([^)]*\)", re.IGNORECASE),
     "Unsafe YAML loading (use yaml.safe_load)"),
    (re.compile(r"eval\s*\(\s*request", re.IGNORECASE), "eval() on request data"),
    (re.compile(r"exec\s*\([^)]*\+", re.IGNORECASE),
     "exec() with concatenated input"),
    (re.compile(r"marshal\.loads?\s*\(", re.IGNORECASE),
     "Unsafe marshal deserialization"),
]

# Weak crypto patterns (pre-compiled)
WEAK_CRYPTO_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"hashlib\.md5\s*\(", re.IGNORECASE),
     "MD5 is cryptographically broken", "Use SHA-256 or SHA-3"),
    (re.compile(r"hashlib\.sha1\s*\(", re.IGNORECASE),
     "SHA-1 is deprecated for security use", "Use SHA-256 or SHA-3"),
    (re.compile(r"\bDES\b", re.IGNORECASE),
     "DES is insecure (56-bit key)", "Use AES-256-GCM"),
    (re.compile(r"MODE_ECB", re.IGNORECASE),
     "ECB mode leaks plaintext patterns", "Use GCM or CBC mode with random IV"),
    (re.compile(r"random\.random\s*\(|random\.randint\s*\(", re.IGNORECASE),
     "Insecure randomness", "Use secrets module for security-sensitive randomness"),
]

# XSS patterns (pre-compiled)
XSS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"innerHTML\s*=\s*", re.IGNORECASE), "Direct innerHTML assignment"),
    (re.compile(r"\.html\s*\(\s*[^)]*\+", re.IGNORECASE),
     "jQuery .html() with concatenated data"),
    (re.compile(r"document\.write\s*\(", re.IGNORECASE),
     "document.write() with user data"),
    (re.compile(r"dangerouslySetInnerHTML", re.IGNORECASE),
     "React dangerouslySetInnerHTML usage"),
]

# SSRF patterns (pre-compiled)
SSRF_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"requests\.(?:get|post|put|delete|patch)\s*\(\s*[^)]*request", re.IGNORECASE), "Request data in outgoing HTTP call"),
    (re.compile(r"urllib\.request\.urlopen\s*\([^)]*request",
     re.IGNORECASE), "Request data in urllib call"),
    (re.compile(r"curl_exec\s*\(\s*[^)]*\$",
     re.IGNORECASE), "User input in curl_exec()"),
]


class SecurityScanner:
    """Static regex-based security scanner for common vulnerability patterns.

    Intended as a fast first-pass filter. For production use combine with
    Semgrep/CodeQL for deeper data-flow analysis.
    """

    # Pre‑compile one‑off patterns used inside class methods
    _auth_guard_re: re.Pattern = re.compile(
        r"@login_required|@require_auth|@jwt_required|check_auth|requires_auth|permission_required",
        re.IGNORECASE,
    )
    _sensitive_route_re: re.Pattern = re.compile(
        r"@app\.(?:route|get|post|put|delete|patch)\s*\([^)]*\b(?:admin|delete|user|account)",
        re.IGNORECASE,
    )
    _hardcoded_creds_re: re.Pattern = re.compile(
        r"(?:admin|root|password|passwd|db_pass)\s*[:=]\s*['\"]"
        r"(?!\$\{|os\.environ|Config|None|''|\"\"|example|test|changeme|secret|password)"
        r"([^'\"]{4,})['\"]",
        re.IGNORECASE,
    )
    _mass_assign_re: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\.create\s*\(\s*\*\*.*request", re.IGNORECASE),
         "Direct request data passed to .create()"),
        (re.compile(r"update\s*\(\s*\*\*.*request", re.IGNORECASE),
         "Direct request data passed to update()"),
    ]

    def __init__(self) -> None:
        logger.info("security_scanner.initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_files(self, file_contents: dict[str, str]) -> list[Issue]:
        """Run all static security checks across every file in *file_contents*.

        Skips binary / minified files to avoid false positives and wasted CPU.
        """
        issues: list[Issue] = []
        for filename, content in file_contents.items():
            if _is_binary_file(filename):
                logger.debug("security_scanner.skip_binary", file=filename)
                continue
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
        return self._match_generic(filename, content, SECRET_PATTERNS, "Secret Leak", "secret_leak")

    def _scan_sqli(self, filename: str, content: str) -> list[Issue]:
        return self._match_generic(filename, content, SQLI_PATTERNS, "SQL Injection Vulnerability", "sql_injection", default_severity=Severity.CRITICAL)

    def _scan_path_traversal(self, filename: str, content: str) -> list[Issue]:
        issues: list[Issue] = []
        for compiled_re, description in PATH_TRAVERSAL_PATTERNS:
            for match in compiled_re.finditer(content):
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
        return self._match_generic(filename, content, INSECURE_DESER_PATTERNS, "Insecure Deserialization", "insecure_deserialization", default_severity=Severity.CRITICAL)

    def _scan_weak_crypto(self, filename: str, content: str) -> list[Issue]:
        issues: list[Issue] = []
        for compiled_re, description, remediation in WEAK_CRYPTO_PATTERNS:
            for match in compiled_re.finditer(content):
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
        return self._match_generic(filename, content, XSS_PATTERNS, "Cross-Site Scripting (XSS) Risk", "xss", default_severity=Severity.HIGH)

    def _scan_ssrf(self, filename: str, content: str) -> list[Issue]:
        return self._match_generic(filename, content, SSRF_PATTERNS, "Server-Side Request Forgery (SSRF)", "ssrf", default_severity=Severity.HIGH)

    def _scan_auth_bypass(self, filename: str, content: str) -> list[Issue]:
        """Detect sensitive routes lacking authentication guards."""
        issues: list[Issue] = []
        has_auth = bool(self._auth_guard_re.search(content))

        for match in self._sensitive_route_re.finditer(content):
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
        for match in self._hardcoded_creds_re.finditer(content):
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
        for compiled_re, desc in self._mass_assign_re:
            for match in compiled_re.finditer(content):
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

    def _match_generic(self, filename: str, content: str, patterns: list, title: str, category: str, default_severity: Severity = Severity.HIGH) -> list[Issue]:
        """Generic matcher for predefined regex lists."""
        issues: list[Issue] = []
        for item in patterns:
            compiled_re = item[0]
            description = item[1]
            # Some patterns include severity as 3rd item, otherwise fallback to default
            severity = item[2] if len(item) > 2 else default_severity

            for match in compiled_re.finditer(content):
                line = content[: match.start()].count("\n") + 1
                issues.append(Issue(
                    type=IssueType.SECURITY,
                    severity=severity,
                    title=title,
                    description=description,
                    file=filename,
                    line=line,
                    suggestion="Review and refactor based on secure coding practices.",
                    category=category,
                    code_snippet=match.group(0)[:120],
                ))
        return issues
