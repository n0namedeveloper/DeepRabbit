"""Tests for code analyzer."""

import pytest

from src.code_analyzer import CodeAnalyzer
from src.models import IssueType, Severity


class TestCodeAnalyzer:
    """Code analyzer test suite."""

    def test_detects_long_functions(self, code_analyzer, sample_python_code):
        issues = code_analyzer.analyze({"test.py": sample_python_code})
        long_funcs = [i for i in issues if i.category == "god_function"]
        assert len(long_funcs) > 0
        assert any("Overly Long Function" in i.title for i in issues)

    def test_detects_deep_nesting(self, code_analyzer):
        code = """
def deeply_nested():
    if True:
        if True:
            if True:
                if True:
                    if True:
                        if True:
                            return 1
        """
        issues = code_analyzer.analyze({"test.py": code})
        nesting = [i for i in issues if i.category == "deep_nesting"]
        assert len(nesting) > 0

    def test_detects_high_complexity(self, code_analyzer):
        code = """
def complex_func(x):
    if x:
        for i in range(10):
            while i < 5:
                if i % 2:
                    try:
                        print(i)
                    except:
                        pass
    return x
        """
        issues = code_analyzer.analyze({"test.py": code})
        complexity = [i for i in issues if i.category == "high_complexity"]
        assert len(complexity) > 0

    def test_detects_missing_docstrings(self, code_analyzer):
        code = "def public_function():\n    return 42\n"
        issues = code_analyzer.analyze({"test.py": code})
        docs = [i for i in issues if i.category == "missing_docstring"]
        assert len(docs) > 0
        assert docs[0].type == IssueType.DOCUMENTATION

    def test_detects_bare_except(self, code_analyzer):
        code = "try:\n    pass\nexcept:\n    pass\n"
        issues = code_analyzer.analyze({"test.py": code})
        smells = [i for i in issues if i.category == "bare_except"]
        assert len(smells) > 0

    def test_complexity_metrics(self, code_analyzer):
        code = "def simple(): return 42\n"
        metrics = code_analyzer.get_complexity_metrics({"test.py": code})
        assert len(metrics) == 1
        assert metrics[0].cyclomatic_complexity <= 2
        assert metrics[0].maintainability_index > 50
