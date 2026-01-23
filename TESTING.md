# Testing Guide for Gentlebot

This document provides guidelines for writing and running tests in the Gentlebot project.

## Table of Contents

- [Setup](#setup)
- [Running Tests](#running-tests)
- [Writing Tests](#writing-tests)
- [Test Categories](#test-categories)
- [Best Practices](#best-practices)
- [CI/CD Integration](#cicd-integration)

## Setup

### Install Development Dependencies

First, ensure you have pytest and related testing tools installed:

```bash
pip install pytest pytest-asyncio pytest-cov
```

### Environment Configuration for Tests

Tests require certain environment variables. Copy the example file:

```bash
cp .env.example .env.test
```

Edit `.env.test` and set:

```bash
env=TEST
DISCORD_TOKEN=test-token-here
PG_DSN=postgresql+asyncpg://test:test@localhost:5432/gentlebot_test
GEMINI_API_KEY=test-key
```

## Running Tests

### Run All Tests

```bash
pytest tests/
```

### Run Specific Test File

```bash
pytest tests/test_settings.py
```

### Run Tests with Coverage

```bash
pytest --cov=gentlebot --cov-report=html tests/
```

This generates an HTML coverage report in `htmlcov/index.html`.

### Run Tests with Verbose Output

```bash
pytest -v tests/
```

### Run Tests Matching a Pattern

```bash
pytest -k "settings" tests/
```

## Test Categories

### Unit Tests

Test individual functions or classes in isolation. Located in `tests/test_*.py`.

**Example:**
```python
def test_int_env_default():
    """Test that int_env returns default when env var is not set."""
    from gentlebot.util import int_env
    result = int_env("NONEXISTENT_VAR", 42)
    assert result == 42
```

### Integration Tests

Test interaction between components or external services. Use mocking for external dependencies.

**Example:**
```python
@pytest.mark.asyncio
async def test_database_pool_connection():
    """Test that database pool can be created and used."""
    from gentlebot.db import get_pool, close_pool

    pool = await get_pool()
    assert pool is not None

    # Test a simple query
    async with pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
        assert result == 1

    await close_pool()
```

### Cog Tests

Test Discord cogs using mocked Discord objects. Use the test harness:

**Example:**
```python
import pytest
from test_harness import load_cog_for_test

@pytest.mark.asyncio
async def test_gemini_cog_loads():
    """Test that GeminiCog can be loaded."""
    from gentlebot.cogs.gemini_cog import GeminiCog

    cog = await load_cog_for_test(GeminiCog)
    assert cog is not None
```

## Writing Tests

### Test File Structure

```python
"""Tests for the XYZ module."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Import what you're testing
from gentlebot.module import function_to_test


def test_simple_function():
    """Test a simple synchronous function."""
    result = function_to_test(input_value)
    assert result == expected_value


@pytest.mark.asyncio
async def test_async_function():
    """Test an async function."""
    result = await async_function_to_test()
    assert result is not None
```

### Mocking Discord Objects

Use `unittest.mock` to create mock Discord objects:

```python
from unittest.mock import MagicMock, AsyncMock

def test_message_handler():
    # Mock message
    message = MagicMock()
    message.content = "test message"
    message.author = MagicMock()
    message.author.id = 123456
    message.author.bot = False
    message.channel = MagicMock()
    message.channel.send = AsyncMock()

    # Test your handler
    await handle_message(message)
    message.channel.send.assert_called_once()
```

### Mocking Database Connections

```python
@pytest.fixture
async def mock_pool():
    """Provide a mock database pool."""
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


@pytest.mark.asyncio
async def test_with_mock_pool(mock_pool, monkeypatch):
    """Test function that uses database."""
    from gentlebot import db
    monkeypatch.setattr(db, "get_pool", AsyncMock(return_value=mock_pool))

    # Your test here
    result = await function_using_db()
    assert result is not None
```

### Testing Configuration

```python
def test_config_validation():
    """Test configuration validation."""
    import os

    # Save original
    original = os.environ.get("SOME_VAR")

    try:
        os.environ["SOME_VAR"] = "test_value"
        # Your test
        from gentlebot.config import settings
        assert settings.some_value == "test_value"
    finally:
        # Restore
        if original:
            os.environ["SOME_VAR"] = original
        else:
            del os.environ["SOME_VAR"]
```

### Testing Error Handling

```python
def test_error_handling():
    """Test that errors are handled correctly."""
    from gentlebot.errors import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        function_that_should_raise()

    assert "expected message" in str(exc_info.value)
```

## Best Practices

### 1. Use Descriptive Test Names

```python
# Good
def test_user_creation_with_valid_email():
    pass

# Bad
def test_user():
    pass
```

### 2. Follow AAA Pattern

Arrange - Act - Assert:

```python
def test_addition():
    # Arrange
    a = 5
    b = 3

    # Act
    result = a + b

    # Assert
    assert result == 8
```

### 3. Test One Thing at a Time

Each test should verify one specific behavior.

### 4. Use Fixtures for Common Setup

```python
@pytest.fixture
def sample_user():
    """Provide a sample user for tests."""
    return {"id": 123, "name": "TestUser"}


def test_user_name(sample_user):
    assert sample_user["name"] == "TestUser"
```

### 5. Mock External Dependencies

Don't make real API calls or database connections in unit tests. Use mocks:

```python
@patch('gentlebot.llm.router.router.generate')
def test_llm_call(mock_generate):
    mock_generate.return_value = "Mocked response"
    result = call_llm()
    assert result == "Mocked response"
```

### 6. Clean Up After Tests

Use try/finally or fixtures with cleanup:

```python
@pytest.fixture
async def test_pool():
    pool = await create_test_pool()
    yield pool
    await pool.close()
```

### 7. Test Edge Cases

Test boundary conditions, empty inputs, None values, etc.

```python
def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(10, 0)
```

## CI/CD Integration

### GitHub Actions

Create `.github/workflows/test.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: gentlebot_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov

      - name: Run tests
        env:
          DISCORD_TOKEN: test-token
          PG_DSN: postgresql+asyncpg://postgres:postgres@localhost:5432/gentlebot_test
        run: |
          pytest --cov=gentlebot --cov-report=xml tests/

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

## Coverage Goals

Aim for:
- **Unit tests**: 80%+ coverage
- **Integration tests**: Critical paths covered
- **Cogs**: All command handlers tested

Check current coverage:

```bash
pytest --cov=gentlebot --cov-report=term-missing tests/
```

## Troubleshooting

### Tests Hang

If async tests hang, ensure you're using `@pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_my_async_function():
    await my_function()
```

### Import Errors

Ensure Gentlebot package is importable:

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest tests/
```

### Database Connection Errors

Ensure test database is running and credentials are correct in `.env.test`.

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [unittest.mock](https://docs.python.org/3/library/unittest.mock.html)
- [Discord.py testing](https://discordpy.readthedocs.io/en/stable/ext/test/index.html)

## Contributing

When adding new features:

1. Write tests first (TDD approach)
2. Ensure tests pass locally
3. Verify coverage doesn't decrease
4. Document any new testing patterns
