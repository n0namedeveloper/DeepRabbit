# 🐇 DeepRabbit — Autonomous AI Code Reviewer

[![GitHub Action](https://img.shields.io/badge/GitHub%20Action-ready-blue?logo=github-actions)](https://github.com/features/actions)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek%20V4-orange)](https://deepseek.ai)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**DeepRabbit** is an open-source autonomous AI code reviewer, similar to [CodeRabbit](https://coderabbit.ai) and [PR-Agent](https://github.com/Codium-ai/pr-agent), but free and self-hosted. It analyzes Pull Requests with an LLM and finds security issues, code smells, convention violations, and refactoring opportunities.

## ✨ Features

- 🔒 **Security Scan** — detects SQL injection, XSS, secret leaks, path traversal, insecure deserialization, weak cryptography, SSRF, auth bypass, and mass assignment
- 👃 **Code Smells** — catches duplication, magic numbers, god classes, dead code, and bare `except`
- 📏 **Conventions** — checks naming, formatting, type hints, and code style
- 🔧 **Refactoring** — suggests concrete improvements with before/after code
- 📊 **Complexity Analysis** — cyclomatic complexity, maintainability index, nesting depth
- 🎯 **Inline Comments** — posts AI comments directly on changed PR lines
- 🏷️ **Labels** — automatically adds PR labels such as `deeprabbit-security`, `deeprabbit-refactoring`, and `deeprabbit-changes-requested`
- 📝 **Review Summary** — posts an overall review summary comment with statistics
- 🌍 **Multi-Language** — Python, JavaScript, TypeScript, Java, Go, SQL (via tree-sitter)
- 📦 **Diff Chunking** — large diffs are automatically split into chunks and reviewed in parallel
- ⚙️ **Custom Prompts** — load your own review prompts from `.deeprabbit/prompt.md`
- 🖥️ **CLI Tool** — review local diffs from the command line
- 🐳 **Docker** — ready-to-use Dockerfile and docker-compose setup
- 🪝 **Pre-commit** — Git hook for pre-commit reviews

<img width="713" height="768" alt="image" src="https://github.com/user-attachments/assets/40dd5eab-0b42-406b-8c87-35a7401517c8" />



<img width="713" height="768" alt="image" src="https://github.com/user-attachments/assets/40dd5eab-0b42-406b-8c87-35a7401517c8" />


## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐      ┌─────────────────┐
│  GitHub PR  │────▶│ GitHub Action│────▶│  FastAPI Server │
└─────────────┘     └──────────────┘      └─────────────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │   DeepSeek V4   │
                                          │   (LLM API)     │
                                          └─────────────────┘
```

## 🚀 Quick Start

### 1. GitHub Action

Add `.github/workflows/deeprabbit.yml` to your repository:

```yaml
name: DeepRabbit Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: deeprabbit-ai/deeprabbit@v1
        with:
          api_url: 'https://your-server.com/review'
          api_key: ${{ secrets.DEEPRABBIT_API_KEY }}
          deepseek_api_key: ${{ secrets.DEEPSEEK_API_KEY }}
```

#### Optional action inputs

| Input | Description | Default |
|-------|-------------|---------|
| `review_level` | Review strictness (`light`, `normal`, `strict`) | `normal` |
| `server_side_fetch` | Let the server fetch diff and file contents internally | `false` |

### 2. Self-Hosted Server (FastAPI)

```bash
git clone https://github.com/your-org/deeprabbit.git
cd deeprabbit

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run
python -m src.main
# or
uvicorn src.main:app --reload --port 8000
```

### 3. Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPSEEK_API_KEY` | DeepSeek API key | ✅ |
| `GITHUB_TOKEN` | GitHub Personal Access Token | ✅ |
| `DEEPRABBIT_API_KEY` | API key for webhook protection | ✅ |
| `PORT` | Server port (default: `8000`) | ❌ |
| `HOST` | Server host (default: `0.0.0.0`) | ❌ |
| `LOG_LEVEL` | Logging level (default: `INFO`) | ❌ |
| `LLM_BASE_URL` | Custom LLM endpoint (default: DeepSeek) | ❌ |
| `GITHUB_API_URL` | GitHub Enterprise URL (default: `https://api.github.com`) | ❌ |
| `MAX_FILES_PER_REVIEW` | Maximum changed files per review | ❌ |
| `MAX_COMMENTS_PER_PR` | Maximum inline comments per PR | ❌ |
| `MAX_DETAIL_COMMENTS_PER_PR` | Maximum detail suggestion comments per PR | ❌ |

### 4. Docker

```bash
cp .env.example .env
docker compose up -d --build
```

The API is available at `http://localhost:8000`, health check at `/healthz`.

## 🖥️ CLI Tool

DeepRabbit provides a CLI for local diff reviews:

```bash
pip install -e .
deeprabbit --diff HEAD~1 --api-url http://localhost:8000 --repo owner/repo
```

Environment variables: `API_URL`, `API_KEY`, `REPO`, `PR_NUMBER`.

## 🪝 Pre-commit Hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/deeprabbbit-ai/deeprabbit
    rev: v1.0.0
    hooks:
      - id: deeprabbit-review
```

Or use `.pre-commit-hooks.yaml` from this repo.

## ⚙️ Custom Prompts

Place a file at `.deeprabbit/prompt.md` in the repository root to override built-in system and review prompts. Separate system prompt and review template with `## ---`.

## 🧪 Local Testing

```bash
# Run tests
pytest tests/ -v

# Run linters
ruff check src/
mypy src/

# Run the server locally
uvicorn src.main:app --reload --port 8000
```

## 📁 Project Structure

```
deeprabbit/
├── .github/
│   └── workflows/
│       └── deeprabbit.yml          # GitHub Action example
├── src/
│   ├── __init__.py
│   ├── main.py                     # FastAPI entrypoint
│   ├── cli.py                      # CLI tool
│   ├── config.py                   # Pydantic settings
│   ├── github_client.py            # GitHub API client (with retry/backoff)
│   ├── llm_client.py               # DeepSeek LLM client (chunking + JSON mode)
│   ├── code_analyzer.py            # Code quality & complexity analyzer
│   ├── comment_generator.py        # Comment & summary generator
│   ├── security_scanner.py         # Vulnerability scanner
│   ├── prompt_templates.py         # LLM prompts (supports external overrides)
│   └── models.py                   # Pydantic models
├── scripts/
│   └── send_review.py              # GitHub Action payload builder
├── tests/
│   ├── conftest.py
│   ├── test_analyzer.py
│   ├── test_comment_generator.py
│   ├── test_config.py
│   ├── test_llm_client.py
│   ├── test_main.py
│   └── test_security_scanner.py
├── examples/
│   └── terrible_code.py            # Example vulnerable code for testing
├── action.yml                      # GitHub Action metadata
├── Dockerfile
├── docker-compose.yml
├── .pre-commit-hooks.yaml
├── pyproject.toml
├── requirements.txt
├── CONTRIBUTING.md
└── README.md
```

## 🔐 Security Issues We Detect

- Hardcoded secrets (API keys, tokens, passwords, AWS keys, Stripe keys)
- SQL injection via f-strings, `.format()`, and string concatenation
- Path traversal from user-controlled paths
- Insecure deserialization (`pickle`, `yaml.load`, `eval`, `marshal`)
- Weak cryptography (MD5, SHA1, DES, ECB mode, insecure randomness)
- Cross-site scripting (`innerHTML`, `document.write`, `dangerouslySetInnerHTML`)
- Server-side request forgery
- Missing authentication on sensitive routes
- Mass assignment vulnerabilities

## 📝 Code Smells & Conventions

- God classes / long functions (>50 lines)
- Code duplication and magic numbers
- Unused imports and print statements
- Missing type hints and docstrings
- Deep nesting and high cyclomatic complexity
- TODO/FIXME comments

## 🤝 Contributing

1. Fork the repository
2. Create a branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to your branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request — DeepRabbit will review it automatically! 🐰

See [CONTRIBUTING.md](CONTRIBUTING.md) for more details.

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE).

---

Made with ❤️ and 🤖 by Artsiom Beniash. Make the world a better place to live! <3