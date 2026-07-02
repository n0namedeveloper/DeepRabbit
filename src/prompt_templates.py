"""LLM prompt templates for code review."""

from src.models import ReviewLevel


SYSTEM_PROMPT = """You are DeepRabbit, an expert code reviewer with 15+ years of experience.
Your job is to perform thorough, professional code reviews with the following priorities:

1. SECURITY (highest priority) - Find vulnerabilities, injection risks, auth issues, secret leaks
2. BUGS - Logic errors, race conditions, null pointer risks, error handling gaps
3. CODE QUALITY - Code smells, duplication, overly complex functions
4. CONVENTIONS - Naming, formatting, type hints, documentation
5. PERFORMANCE - Inefficient algorithms, memory leaks, N+1 queries
6. REFACTORING - Concrete suggestions to improve the code

Rules:
- Be specific: always reference exact line numbers and code snippets
- Be constructive: explain WHY something is an issue and HOW to fix it
- Be concise: focus on impactful issues, don't nitpick formatting unless asked
- Format findings as JSON
- If a file looks good, say so explicitly
- Never hallucinate issues - if unsure, say so
"""


def build_review_prompt(
    diff: str,
    files: list[dict],
    file_contents: dict[str, str],
    review_level: str = ReviewLevel.NORMAL,
    repo_info: str = "",
) -> str:
    """Build the main review prompt."""
    level_instructions = {
        ReviewLevel.LIGHT: "Focus only on critical/high severity issues. Skip style/ formatting comments.",
        ReviewLevel.NORMAL: "Cover security, bugs, code smells, and significant convention violations.",
        ReviewLevel.STRICT: "Be thorough. Flag even minor issues. Check every function for documentation and type hints.",
    }

    files_summary = []
    for f in files:
        fname = f.get("filename", "unknown")
        status = f.get("status", "modified")
        content = file_contents.get(fname, "")
        lines = content.count("\n") if content else 0
        files_summary.append(f"- {fname} ({status}, {lines} lines)")

    prompt = f"""## Context
Repository: {repo_info}
  Review Level: {review_level.value if hasattr(review_level, 'value') else review_level}
  Instructions: {level_instructions.get(review_level, level_instructions[ReviewLevel.NORMAL])}

## Changed Files
{chr(10).join(files_summary)}

## Git Diff
```diff
{diff[:80000]}
```

## Task
Perform a comprehensive code review of this Pull Request. Return your findings in the following JSON format:

```json
{{
  "summary": {{
    "summary": "Brief overall assessment (2-3 sentences)",
    "rating": "approve|comment|request_changes",
    "overall_comment": "Markdown summary with key findings"
  }},
  "issues": [
    {{
      "type": "security|performance|bug|code_smell|convention|refactoring|documentation|complexity",
      "severity": "critical|high|medium|low|info",
      "title": "Short issue title",
      "description": "Detailed explanation",
      "file": "relative/path/file.ext",
      "line": 42,
      "end_line": 45,
      "suggestion": "How to fix (with code example if applicable)",
            "code_snippet": "REQUIRED: copy the exact problematic line(s) of code from the diff verbatim, max 3 lines",
      "category": "injection|race_condition|duplicate|naming|missing_docs|etc"
    }}
  ],
  "refactoring": [
    {{
      "file": "path/to/file",
      "current": "current code",
      "suggested": "improved code",
      "explanation": "why this is better"
    }}
  ]
}}
```

Requirements:
- Only report issues with specific line numbers visible in the diff
- For security issues, explain the exact vulnerability and provide a fix
- For refactoring, provide BEFORE/AFTER code with explanation
- Limit to the most impactful 15-20 issues
- If no issues found, return empty issues array and positive summary
"""
    return prompt


SECURITY_PROMPT = """You are a security expert specializing in application security.
Analyze the following code for security vulnerabilities:

```
{code}
```

Focus on:
1. SQL Injection (string concatenation/format in queries)
2. Command Injection (subprocess with unsanitized input)
3. XSS (unescaped output in web contexts)
4. Path Traversal (file operations with user paths)
5. Insecure Deserialization (pickle, yaml.load)
6. Secret Leaks (API keys, passwords in code)
7. Weak Crypto (MD5, SHA1, hardcoded salts)
8. SSRF (requests to user-controlled URLs)
9. Auth Bypass (missing checks, hardcoded credentials)
10. Mass Assignment (unfiltered object creation)

For each finding, provide:
- Severity (critical/high/medium)
- CWE reference
- Exact line
- Exploitation scenario
- Secure fix example

Return as structured JSON."""


COMPLEXITY_PROMPT = """Analyze the cyclomatic complexity and maintainability of this code:

```
{code}
```

Report:
1. Total cyclomatic complexity
2. Functions with complexity > 10 (flag as refactor needed)
3. Cognitive complexity issues
4. Nesting depth concerns
5. Maintainability score (0-100)
6. Refactoring suggestions with code examples

Return as JSON."""


def build_inline_comment_prompt(
    file_path: str,
    line_content: str,
    line_number: int,
    context_lines: list[str],
    issue: dict,
) -> str:
    """Build prompt for generating a specific inline comment."""
    context = "\n".join(
        f"{i + 1}: {line}" for i, line in enumerate(context_lines)
    )

    return f"""Given this code context:

File: {file_path}
Line {line_number}: {line_content}
Context:
{context}

Issue detected: {issue.get("type", "general")} - {issue.get("title", "")}
Description: {issue.get("description", "")}

Write a concise, professional inline code review comment (2-4 sentences) that:
1. States the problem clearly
2. Explains why it matters
3. Suggests how to fix it

Keep it under 250 characters and suitable for a GitHub PR comment."""
