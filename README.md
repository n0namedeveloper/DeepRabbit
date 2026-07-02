# 🐇 DeepRabbit — Autonomous AI Code Reviewer

[![GitHub Action](https://img.shields.io/badge/GitHub%20Action-ready-blue?logo=github-actions)](https://github.com/features/actions)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek%20V4-orange)](https://deepseek.ai)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**DeepRabbit** is an open-source autonomous AI code reviewer, similar to [CodeRabbit](https://coderabbit.ai) and [PR-Agent](https://github.com/Codium-ai/pr-agent), but free and self-hosted. It automatically analyzes Pull Requests with an LLM and finds security issues, code smells, convention violations, and refactoring opportunities.

## ✨ Features

- 🔒 **Security Scan** — detects vulnerabilities such as SQL injection, XSS, and secret leaks
- 👃 **Code Smells** — catches duplication, magic numbers, god classes, and dead code
- 📏 **Conventions** — checks naming, formatting, and code style
- 🔧 **Refactoring** — suggests concrete improvements
- 📊 **Complexity Analysis** — analyzes cyclomatic complexity
- 🎯 **Inline Comments** — posts AI comments directly on changed PR lines
- 🏷️ **Labels** — automatically adds PR labels such as security and refactoring
- 📝 **Review Summary** — posts an overall review summary comment on the PR

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  GitHub PR  │────▶│ GitHub Action│────▶│  FastAPI Server │
└─────────────┘     └──────────────┘     └─────────────────┘
                                                │
                                       ┌────────▼────────┐
                                       │   DeepSeek V4   │
                                       │   (LLM API)     │
                                       └─────────────────┘
```

## 🚀 Quick Start

### 1. Install the GitHub Action

Add this file to your repository as `.github/workflows/deeprabbit.yml`:

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

### 2. Self-hosted server (FastAPI)

```bash
# Clone the repository
git clone https://github.com/your-org/deeprabbit.git
cd deeprabbit

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run the server
python -m src.main
```

### 3. Environment Variables

| Variable | Description | Required |
|------------|----------|--------------|
| `DEEPSEEK_API_KEY` | DeepSeek API key | ✅ |
| `GITHUB_TOKEN` | GitHub Personal Access Token | ✅ |
| `DEEPRABBIT_API_KEY` | API key for webhook protection | ✅ |
| `PORT` | Server port (default: 8000) | ❌ |

### 4. Deployment

For local or server deployment, use the `.env.example` template:

```bash
cp .env.example .env
docker compose up -d --build
```

The API will be available at `http://localhost:8000`, and the health check is exposed at `/healthz`.

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
│       └── deeprabbit.yml          # GitHub Action
├── src/
│   ├── __init__.py
│   ├── main.py                     # FastAPI entrypoint
│   ├── config.py                   # Configuration
│   ├── github_client.py            # GitHub API client
│   ├── llm_client.py               # DeepSeek LLM client
│   ├── code_analyzer.py            # Code analyzer
│   ├── comment_generator.py        # Comment generator
│   ├── security_scanner.py         # Vulnerability scanner
│   ├── prompt_templates.py         # LLM prompts
│   └── models.py                   # Pydantic models
├── tests/
│   ├── conftest.py
│   ├── test_analyzer.py
│   ├── test_github_client.py
│   └── test_security_scanner.py
├── action.yml                      # GitHub Action metadata
├── Dockerfile
├── requirements.txt
├── pyproject.toml
└── README.md
```

## 🔐 Example Findings

### Security Issues
- Hardcoded secrets in source code
- SQL injection via f-strings
- Missing input validation
- Sensitive data leakage in logs

### Code Smells
- God classes / long functions (>50 lines)
- Code duplication
- Magic numbers
- Unused imports

### Conventions
- Naming convention violations (snake_case, CamelCase)
- Missing type hints
- Incorrect or missing function documentation

## 🤝 Contributing

1. Fork the repository
2. Create a branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to your branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request — DeepRabbit will review it automatically! 🐰

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE).

---

Made with ❤️ and 🤖 by Artsiom Beniash. Make the world a better place to live! <3