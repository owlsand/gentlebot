import logging
from logging.config import dictConfig


def configure_logging(level="INFO"):
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "std": {"format": "%(asctime)s %(name)s %(levelname)s: %(message)s"}
        },
        "handlers": {
            "stdout": {"class": "logging.StreamHandler", "formatter": "std"}
        },
        "root": {"handlers": ["stdout"], "level": level},
    })
