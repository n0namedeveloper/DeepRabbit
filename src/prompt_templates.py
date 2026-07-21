"""LLM prompt templates for code review.

Issue #10: Supports loading .deeprabbit/prompt.md from the repository root
(fetched via GitPython or passed as repo_root) with fallback to built-in prompts.
"""

import os

import structlog

from src.models import ReviewLevel

logger = structlog.get_logger()

# -------------------------------------------------------------------
# Built-in default prompts (fallback when no .deeprabbit/prompt.md)
# -------------------------------------------------------------------
_DEFAULT_SYSTEM_PROMPT = """You are DeepRabbit, an expert code reviewer with 15+ years of experience.
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

_DEFAULT_REVIEW_PROMPT = """
## Context
Repository: {repo_info}
  Review Level: {review_level}
  Instructions: {level_instructions}

## Changed Files
{files_summary}

## Git Diff
```diff
{diff}
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

# -------------------------------------------------------------------
# Load external prompt from .deeprabbit/prompt.md (#10)
# -------------------------------------------------------------------
def _load_external_prompt(repo_root: str | None = None) -> str | None:
    """Try to load a custom SYSTEM_PROMPT from the repo's .deeprabbit/prompt.md.

    The file can contain either a single prompt (used as system prompt) or
    sections delimited by ## --- markers: the first section is the system
    prompt, the second is the review prompt template.

    Returns None if the file does not exist or cannot be read.
    """
    if not repo_root:
        return None
    prompt_path = os.path.join(repo_root, ".deeprabbit", "prompt.md")
    if not os.path.isfile(prompt_path):
        return None
    try:
        with open(prompt_path, encoding="utf-8") as f:
            content = f.read()
        logger.info("prompt.loaded_external", path=prompt_path)
        return content
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("prompt.load_external_failed", path=prompt_path, error=str(e))
        return None

def _load_checklist(repo_root: str | None = None) -> str | None:
    """Try to load a custom checklist from .deeprabbit/checklist.yaml."""
    if not repo_root:
        return None
    checklist_path = os.path.join(repo_root, ".deeprabbit", "checklist.yaml")
    if not os.path.isfile(checklist_path):
        return None
    try:
        with open(checklist_path, encoding="utf-8") as f:
            content = f.read()
        logger.info("checklist.loaded", path=checklist_path)
        return content
    except Exception as e:
        logger.warning("checklist.load_failed", path=checklist_path, error=str(e))
        return None


# Global caches populated on first use
_SYSTEM_PROMPT: str | None = None
_REVIEW_TEMPLATE: str | None = None


def get_system_prompt(repo_root: str | None = None) -> str:
    """Return the active system prompt (external > built-in).

    Cached on first call; pass repo_root only on the first invocation.
    """
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is not None:
        return _SYSTEM_PROMPT
    external = None
    if repo_root:
        external = _load_external_prompt(repo_root)
    if external:
        # External file may have sections separated by ## ---
        parts = external.split("## ---", 1)
        _SYSTEM_PROMPT = parts[0].strip()
        if len(parts) > 1:
            global _REVIEW_TEMPLATE
            _REVIEW_TEMPLATE = parts[1].strip()
    else:
        _SYSTEM_PROMPT = _DEFAULT_SYSTEM_PROMPT

    # Append custom checklist if present
    checklist = _load_checklist(repo_root) if repo_root else None
    if checklist:
        _SYSTEM_PROMPT += f"\n\nAdditionally, strictly verify the following custom checklist for this repository:\n{checklist}"

    return _SYSTEM_PROMPT


def get_review_template(repo_root: str | None = None) -> str:
    """Return the active review prompt template (external > built-in).

    Cached on first call; pass repo_root only on the first invocation.
    """
    global _REVIEW_TEMPLATE
    if _REVIEW_TEMPLATE is not None:
        return _REVIEW_TEMPLATE
    external = None
    if repo_root:
        external = _load_external_prompt(repo_root)
    if external:
        parts = external.split("## ---", 1)
        if len(parts) > 1:
            _REVIEW_TEMPLATE = parts[1].strip()
            return _REVIEW_TEMPLATE
    _REVIEW_TEMPLATE = _DEFAULT_REVIEW_PROMPT
    return _REVIEW_TEMPLATE


# Expose a single SYSTEM_PROMPT constant for backward compatibility
SYSTEM_PROMPT = _DEFAULT_SYSTEM_PROMPT


def build_review_prompt(
    diff: str,
    files: list[dict],
    file_contents: dict[str, str],
    review_level: str = ReviewLevel.NORMAL,
    repo_info: str = "",
    chunk_index: int = 0,
    total_chunks: int = 1,
    repo_root: str | None = None,
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

    # Build file summary list
    files_summary_lines = []
    for f in files:
        fname = f.get("filename", "unknown")
        status = f.get("status", "modified")
        content = file_contents.get(fname, "")
        lines = content.count("\n") if content else 0
        files_summary_lines.append(f"- {fname} ({status}, {lines} lines)")

    # Determine effective review level string
    level_str = review_level.value if hasattr(review_level, "value") else review_level
    level_instr = level_instructions.get(review_level, level_instructions[ReviewLevel.NORMAL])

    # Truncate diff to max_diff_size if still needed
    from src.config import settings
    effective_diff = diff[:settings.max_diff_size]

    # Chunk info for context
    chunk_suffix = ""
    if total_chunks > 1:
        chunk_suffix = f"\n[This is chunk {chunk_index + 1} of {total_chunks} review chunks.]"

    # Use the active template (supports external from .deeprabbit/prompt.md)
    template = get_review_template(repo_root)
    prompt = template.format(
        repo_info=repo_info,
        review_level=level_str,
        level_instructions=level_instr,
        files_summary="\n".join(files_summary_lines),
        diff=effective_diff,
    )
    prompt += chunk_suffix
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
