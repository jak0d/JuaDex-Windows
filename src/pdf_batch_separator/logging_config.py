"""Content-free local diagnostic logging.

The log records *what the app did*, never *what the documents contain*: no
page text, no barcode payloads beyond the configured marker, no metadata.
Logs stay on the machine; nothing is ever uploaded.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOG_FILENAME = "pdf-batch-separator.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 2


def log_directory() -> Path:
    """Per-user log directory (``%LOCALAPPDATA%`` on Windows)."""

    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "JuaDex PDFs Separator" / "logs"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "pdf-batch-separator" / "logs"


def configure_logging(level: int = logging.INFO, *, to_file: bool = True) -> Path | None:
    """Configure root logging and return the log file path, if any."""

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    # A packaged GUI build has no console; guard against a missing stderr.
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    if not to_file:
        return None

    try:
        directory = log_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / LOG_FILENAME
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        return path
    except OSError:  # pragma: no cover - read-only profile
        return None


__all__ = ["LOG_FILENAME", "configure_logging", "log_directory"]
