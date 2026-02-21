"""Minimal local fallback for `from loguru import logger` when loguru is unavailable."""
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("polymarket_bot")
