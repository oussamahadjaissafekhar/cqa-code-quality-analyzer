"""Logging configuration.

All logs go to stderr so stdout remains a clean report channel for JSON, SARIF,
or GitHub workflow commands.
"""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "cqa"


def configure_logging(verbosity: int = 0, quiet: bool = False) -> logging.Logger:
    """Configure the ``cqa`` logger once and return it.

    ``verbosity`` is the Click ``-v`` count: 0 = WARNING, 1 = INFO, 2+ = DEBUG.
    ``quiet`` suppresses everything below ERROR.
    """

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.propagate = False

    if quiet:
        level = logging.ERROR
    elif verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the configured ``cqa`` logger."""

    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)
