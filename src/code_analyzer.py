"""Code quality analysis (complexity, smells, conventions)."""

import ast
import math
import re

import structlog

from src.models import ComplexityMetrics, Issue, IssueType, Severity

logger = structlog.get_logger()


# Maximum thresholds for code quality
MAX_FUNCTION_LENGTH = 10
MAX_CLASS_LENGTH = 200
MAX_COMPLEXITY = 5
MAX_NESTING_DEPTH = 4


class ComplexityVisitor(ast.NodeVisitor):
    """AST visitor to compute cyclomatic complexity."""

    def __init__(self):
        self.complexity = 1

    def visit_If(self, node):  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node):  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node):  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node):  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node):  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_comprehension(self, node):  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)


class CodeAnalyzer:
    """Analyze code for quality, complexity, and conventions."""

    def __init__(self):
        self.issues: list[Issue] = []
        logger.info("code_analyzer.initialized")

    def analyze(self, file_contents: dict[str, str]) -> list[Issue]:
        """Run all analysis passes on the codebase."""
        self.issues = []
        for filename, content in file_contents.items():
            logger.debug("analyzing_file", file=filename)
            self._analyze_length(filename, content)
            self._analyze_ast(filename, content)
            self._analyze_conventions(filename, content)
            self._analyze_smells(filename, content)
            self._analyze_documentation(filename, content)
        return self.issues

    def get_complexity_metrics(self, file_contents: dict[str, str]) -> list[ComplexityMetrics]:
        """Compute complexity metrics for all Python files."""
        metrics = []
        for filename, content in file_contents.items():
            if not filename.endswith(".py"):
                continue
            try:
                tree = ast.parse(content)
                visitor = ComplexityVisitor()
                visitor.visit(tree)
                func_complexities = self._get_function_complexities(tree)
                loc = content.count("\n")
                mi = self._maintainability_index(
                    content, visitor.complexity, loc)
                metrics.append(
                    ComplexityMetrics(
                        file=filename,
                        cyclomatic_complexity=float(visitor.complexity),
                        maintainability_index=mi,
                        lines_of_code=loc,
                        functions=func_complexities,
                    )
                )
            except SyntaxError:
                logger.warning("syntax_error_in_file", file=filename)
                continue
        return metrics

    def _analyze_length(self, filename: str, content: str) -> None:
        """Check for overly long functions/classes."""
        if not filename.endswith(".py"):
            return
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                length = (node.end_lineno - node.lineno +
                          1) if node.end_lineno else 0
                if length > MAX_FUNCTION_LENGTH:
                    self.issues.append(
                        Issue(
                            type=IssueType.CODE_SMELL,
                            severity=Severity.LOW,
                            title="Overly Long Function",
                            description=f"Function '{node.name}' is {length} lines. Consider breaking into smaller functions.",
                            file=filename,
                            line=node.lineno,
                            end_line=node.end_lineno,
                            suggestion=f"Split '{node.name}' into smaller functions. Aim for <{MAX_FUNCTION_LENGTH} lines per function.",
                            category="god_function",
                        )
                    )
            elif isinstance(node, ast.ClassDef):
                length = (node.end_lineno - node.lineno +
                          1) if node.end_lineno else 0
                if length > MAX_CLASS_LENGTH:
                    self.issues.append(
                        Issue(
                            type=IssueType.CODE_SMELL,
                            severity=Severity.MEDIUM,
                            title="Overly Large Class",
                            description=f"Class '{node.name}' is {length} lines. Consider extracting responsibilities.",
                            file=filename,
                            line=node.lineno,
                            end_line=node.end_lineno,
                            suggestion="Apply Single Responsibility Principle. Extract related methods to new classes.",
                            category="god_class",
                        )
                    )

    def _analyze_ast(self, filename: str, content: str) -> None:
        """Analyze Python AST for complexity and issues."""
        if not filename.endswith(".py"):
            return
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                visitor = ComplexityVisitor()
                visitor.visit(node)
                if visitor.complexity > MAX_COMPLEXITY:
                    self.issues.append(
                        Issue(
                            type=IssueType.COMPLEXITY,
                            severity=Severity.MEDIUM,
                            title="High Cyclomatic Complexity",
                            description=f"Function '{node.name}' has complexity {visitor.complexity}. Reduce branching.",
                            file=filename,
                            line=node.lineno,
                            suggestion="Extract nested conditions into helper functions or use early returns.",
                            category="high_complexity",
                        )
                    )

            # Check nesting depth
            max_depth = self._max_nesting_depth(node)
            if max_depth > MAX_NESTING_DEPTH:
                self.issues.append(
                    Issue(
                        type=IssueType.COMPLEXITY,
                        severity=Severity.LOW,
                        title="Deep Nesting",
                        description=f"Deep nesting detected ({max_depth} levels). Refactor for readability.",
                        file=filename,
                        line=node.lineno if hasattr(node, "lineno") else 1,
                        suggestion="Use guard clauses, early returns, or extract nested logic into functions.",
                        category="deep_nesting",
                    )
                )

    def _analyze_conventions(self, filename: str, content: str) -> None:
        """Check naming conventions and style."""
        if not filename.endswith(".py"):
            return

        # Naming conventions
        name_issues = {
            r"def [A-Z]": (Severity.INFO, "Function should use snake_case, not CamelCase"),
            r"class [a-z]": (Severity.INFO, "Class should use PascalCase"),
            r"[A-Z][a-zA-Z0-9]* = [\"']": (Severity.LOW, "Constant should be UPPER_CASE"),
        }

        for pattern, (severity, msg) in name_issues.items():
            for match in re.finditer(pattern, content):
                line = content[: match.start()].count("\n") + 1
                self.issues.append(
                    Issue(
                        type=IssueType.CONVENTION,
                        severity=severity,
                        title="Naming Convention Violation",
                        description=msg,
                        file=filename,
                        line=line,
                        suggestion="Follow PEP 8 naming conventions",
                        category="naming_convention",
                    )
                )

        # Check for type hints
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    # Check if function has any type annotations
                    has_types = bool(node.returns)
                    has_arg_types = any(
                        arg.annotation for arg in node.args.args + node.args.kwonlyargs
                    )
                    if not has_types and not has_arg_types and len(node.args.args) > 0:
                        self.issues.append(
                            Issue(
                                type=IssueType.CONVENTION,
                                severity=Severity.LOW,
                                title="Missing Type Hints",
                                description=f"Function '{node.name}' lacks type annotations.",
                                file=filename,
                                line=node.lineno,
                                suggestion="Add type hints: def func(x: int) -> str:",
                                category="missing_type_hints",
                            )
                        )
        except SyntaxError:
            pass

    def _analyze_smells(self, filename: str, content: str) -> None:
        """Detect code smells."""
        if not filename.endswith(".py"):
            return

        smells = [
            (
                r"except\s*:\s*\n",
                Severity.HIGH,
                "Bare except catches everything including SystemExit",
                "Use 'except Exception:' or catch specific exceptions",
                "bare_except",
            ),
            (
                r"print\s*\(",
                Severity.LOW,
                "Print statement found in code",
                "Use logging instead of print for production code",
                "print_statement",
            ),
            (
                r"TODO|FIXME|XXX|HACK",
                Severity.INFO,
                "TODO/FIXME comment found",
                "Consider addressing this technical debt",
                "todo_comment",
            ),
            (
                r"pass\s*\n\s*except",
                Severity.MEDIUM,
                "Empty pass before except (swallowing exception)",
                "Don't silently swallow exceptions without logging",
                "empty_except",
            ),
        ]

        for pattern, severity, title, suggestion, category in smells:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line = content[: match.start()].count("\n") + 1
                self.issues.append(
                    Issue(
                        type=IssueType.CODE_SMELL,
                        severity=severity,
                        title=title,
                        description=title,
                        file=filename,
                        line=line,
                        suggestion=suggestion,
                        category=category,
                    )
                )

    def _analyze_documentation(self, filename: str, content: str) -> None:
        """Check for missing docstrings."""
        if not filename.endswith(".py"):
            return
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Skip private functions
                if node.name.startswith("_"):
                    continue

                has_docstring = False
                if node.body and isinstance(node.body[0], ast.Expr):
                    value = node.body[0].value
                    # Different Python versions represent string docstrings differently in the AST.
                    # Prefer ast.Constant with a str value; fall back to ast.Str if present.
                    if hasattr(ast, "Constant") and isinstance(value, ast.Constant):
                        has_docstring = isinstance(value.value, str)
                    elif hasattr(ast, "Str") and isinstance(value, ast.Str):
                        has_docstring = True

                if not has_docstring:
                    self.issues.append(
                        Issue(
                            type=IssueType.DOCUMENTATION,
                            severity=Severity.LOW,
                            title="Missing Docstring",
                            description=f"Public function '{node.name}' lacks a docstring.",
                            file=filename,
                            line=node.lineno,
                            suggestion=f"Add a docstring to '{node.name}': def {node.name}(...):\\n    \"\"\"Description.\"\"\"",
                            category="missing_docstring",
                        )
                    )

    @staticmethod
    def _get_function_complexities(tree: ast.AST) -> list[dict]:
        """Get complexity per function."""
        result = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                visitor = ComplexityVisitor()
                visitor.visit(node)
                result.append(
                    {
                        "name": node.name,
                        "complexity": visitor.complexity,
                        "line": node.lineno,
                    }
                )
        return result

    def _maintainability_index(self, content: str, complexity: int, loc: int) -> float:
        """Calculate Microsoft-style maintainability index."""
        # MI = max(0, (171 − 5.2 * ln(Halstead Volume) − 0.23 * CC − 16.2 * ln(LOC)) * 100 / 171)
        # Simplified version without Halstead metrics
        if loc == 0:
            return 100.0
        cc_penalty = 0.23 * complexity
        loc_penalty = 16.2 * math.log(loc + 1)
        raw = max(0, 171 - cc_penalty - loc_penalty)
        return round(100 * raw / 171, 2)

    def _max_nesting_depth(self, node: ast.AST, depth: int = 0) -> int:
        """Calculate maximum nesting depth of an AST node."""
        if depth > 15:
            return depth
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                ast.If | ast.While | ast.For | ast.With | ast.Try | ast.ExceptHandler,
            ):
                d = self._max_nesting_depth(child, depth + 1)
                max_depth = max(max_depth, d)
            else:
                d = self._max_nesting_depth(child, depth)
                max_depth = max(max_depth, d)
        return max_depth
