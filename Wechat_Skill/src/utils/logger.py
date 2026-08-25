"""Logger setup using loguru.

Usage:
    from src.utils.logger import setup_logger
    logger = setup_logger(config)
    logger.info("message")
"""
from __future__ import annotations

import os
import sys

from loguru import logger


def setup_logger(config: dict):
    """Configure loguru from config dict.

    Expects config["logging"] with keys:
        level (str): "DEBUG" | "INFO" | "WARNING" | "ERROR"
        file (str): log file path
        rotation (str): e.g. "10 MB" or "1 day"
    """
    log_config = config.get("logging", {})
    level = log_config.get("level", "INFO")
    log_file = log_config.get("file", "./data/logs/wechat_rpa.log")
    rotation = log_config.get("rotation", "10 MB")

    # Ensure directory exists
    os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else ".", exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True)
    logger.add(
        log_file,
        level=level,
        rotation=rotation,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )
    return logger
