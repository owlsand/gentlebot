import logging

import gentlebot.__main__ as main


def test_console_logging_remains_verbose(monkeypatch):
    """Ensure raising LOG_LEVEL does not disable INFO logs for gentlebot."""

    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    main.configure_logging()

    log = logging.getLogger("gentlebot.test_console")
    assert log.isEnabledFor(logging.INFO)

    # Restore default configuration for subsequent tests.
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    main.configure_logging()
