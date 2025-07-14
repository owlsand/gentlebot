# Testing Guide

Place unit tests in this folder and run them with:
```
python -m pytest -q
```
Tests should avoid network calls; rely on fixtures or sample data. Use the
`test_harness.py` script to ensure all cogs load offline.
