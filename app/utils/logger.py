from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging

from .path_utils import project_root


def setup_logger(name: str = "midas_floorload_auto_v4") -> logging.Logger:
    root = project_root()
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    file_handler = logging.FileHandler(log_dir / f"floorload_{datetime.now():%Y%m%d}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger
