# Contributing to DeepRabbit

Thank you for considering contributing to DeepRabbit!

## How to Contribute

1. **Fork** the repository
2. Create a **feature branch**: `git checkout -b feature/amazing-feature`
3. **Commit** your changes: `git commit -m 'Add amazing feature'`
4. **Push** to the branch: `git push origin feature/amazing-feature`
5. Open a **Pull Request**

## Development Setup

```bash
# Clone
\`git clone https://github.com/deeprabbbit-ai/deeprabbit.git\`
\`cd deeprabbit\`

# Install dependencies
\`pip install -e ".[dev]"\`

# Run tests
\`pytest tests/ -v\`

# Run linting
\`ruff check src/\`
\`mypy src/\`
```

## Code Style

- Follow PEP 8
- Use type hints on all public functions
- Add docstrings to all modules and functions
- Keep functions under 50 lines when possible

## Reporting Security Issues

Please email security@deeprabbit.dev instead of opening a public issue.
