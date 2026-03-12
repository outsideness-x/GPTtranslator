"""Centralized logging setup."""

from __future__ import annotations

import logging

LOG_NAMESPACE = "gpttranslator"


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure shared logging once for the whole app."""

    logger = logging.getLogger(LOG_NAMESPACE)
    logger.setLevel(level.upper())

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return namespaced logger instance."""

    full_name = LOG_NAMESPACE if not name else f"{LOG_NAMESPACE}.{name}"
    return logging.getLogger(full_name)
