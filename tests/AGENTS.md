# Testing Guide

Place unit tests in this folder and run them with:
```
make test           # or: python -m pytest -q
```

Tests run automatically in CI on every pull request.

## Writing Tests
- Tests should avoid network calls; rely on fixtures or sample data.
- Use `pytest-asyncio` for async tests (mode is set to `auto` in pyproject.toml).
- Use the `test_harness.py` script to ensure all cogs load offline.
