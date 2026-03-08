"""Logging setup: file + stderr output."""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("tidyup")
    logger.setLevel(logging.DEBUG)

    # File handler — always DEBUG
    fh = logging.FileHandler(log_dir / "tidyup.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(fh)

    # Stderr handler — INFO or DEBUG based on verbose flag
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(sh)

    return logger
