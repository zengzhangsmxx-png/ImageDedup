"""Logging setup — configures Python logging for the application."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_level: str = "INFO") -> None:
    """Configure application-wide logging with file rotation."""
    log_dir = Path.home() / ".cache" / "image_dedup" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "image_dedup.log"

    root = logging.getLogger("image_dedup")
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if not root.handlers:
        fh = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"image_dedup.{name}")
