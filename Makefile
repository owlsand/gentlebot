.PHONY: test test-verbose harness clean

test:
	python -m pytest -q

test-verbose:
	python -m pytest -v

harness:
	env=TEST GEMINI_API_KEY=dummy DISCORD_TOKEN=dummy PG_DSN= python test_harness.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
