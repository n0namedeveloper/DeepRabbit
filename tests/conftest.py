"""Pytest fixtures and configuration."""

import pytest

from src.security_scanner import SecurityScanner
from src.code_analyzer import CodeAnalyzer
from src.comment_generator import CommentGenerator
from src.models import Issue, IssueType, Severity


@pytest.fixture
def sample_python_code() -> str:
    """Sample Python code with various issues."""
    return """
def authenticate_user(username, password):
    # TODO: fix this
    if username == "admin" and password == "supersecret123":
        return True
    return False

def process_data(data):
    query = f"SELECT * FROM users WHERE id = {data['id']}"
    cursor.execute(query)
    return cursor.fetchall()

def very_long_function(a, b, c, d, e, f, g, h):
    if a:
        if b:
            if c:
                if d:
                    if e:
                        if f:
                            if g:
                                if h:
                                    return True
    return False

class GodClass:
    def method1(self): pass
    def method2(self): pass
    def method3(self): pass
    def method4(self): pass
    def method5(self): pass
    def method6(self): pass
    def method7(self): pass
    def method8(self): pass
    def method9(self): pass
    def method10(self): pass
    def method11(self): pass
    def method12(self): pass
    def method13(self): pass
    def method14(self): pass
    def method15(self): pass
"""


@pytest.fixture
def sample_insecure_code() -> str:
    """Code with security vulnerabilities."""
    return """
import pickle
import yaml
import hashlib
import random

API_KEY = "sk-1234567890abcdef1234567890abcdef12345678abcdef1234"

def load_user_data(data):
    return pickle.loads(data)

def parse_config(config_str):
    return yaml.load(config_str)

def get_password_hash(pw):
    return hashlib.md5(pw.encode()).hexdigest()

def generate_token():
    return random.random()
"""


@pytest.fixture
def security_scanner() -> SecurityScanner:
    """Security scanner fixture."""
    return SecurityScanner()


@pytest.fixture
def code_analyzer() -> CodeAnalyzer:
    """Code analyzer fixture."""
    return CodeAnalyzer()


@pytest.fixture
def comment_generator() -> CommentGenerator:
    """Comment generator fixture."""
    return CommentGenerator()


@pytest.fixture
def sample_issues() -> list[Issue]:
    """Sample issues for testing comment generation."""
    return [
        Issue(
            type=IssueType.SECURITY,
            severity=Severity.CRITICAL,
            title="Hardcoded API Key",
            description="API key found in source code.",
            file="src/config.py",
            line=10,
            suggestion="Move to environment variables.",
            code_snippet='API_KEY = "sk-1234"',
            category="secret_leak",
        ),
        Issue(
            type=IssueType.CODE_SMELL,
            severity=Severity.LOW,
            title="Overly Long Function",
            description="Function is too long.",
            file="src/main.py",
            line=42,
            suggestion="Split into smaller functions.",
            category="god_function",
        ),
    ]


@pytest.fixture
def sample_file_contents() -> dict[str, str]:
    """Sample file contents for testing."""
    return {
        "src/main.py": "def main():\n    pass\n",
        "src/utils.py": "def helper():\n    return True\n",
    }


@pytest.fixture
def sample_review_summary() -> str:
    """Sample review summary text."""
    return "The code is generally well-written with a few security concerns that need addressing."
