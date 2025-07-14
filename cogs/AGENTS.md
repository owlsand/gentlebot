# Cog Development Guide

This directory houses all feature cogs for Gentlebot. Each file should be
named `*_cog.py` and define one or more `commands.Cog` subclasses.

## Guidelines
- Use a hierarchical logger: `log = logging.getLogger(f"gentlebot.{__name__}")`.
- Keep async Discord responses under 1900 characters.
- Provide a short module-level docstring describing commands.
- Include type hints where practical.
- Add related tests under `tests/`.
