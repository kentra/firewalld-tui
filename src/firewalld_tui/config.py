"""Configuration and logging setup for firewalld-tui."""

from __future__ import annotations

import logging
from configparser import ConfigParser, Error as ConfigParserError
from pathlib import Path

from loguru import logger

CONFIG_DIR = Path.home() / ".firewalld-tui"
CONFIG_FILE = CONFIG_DIR / "firewalld-tui.conf"
LOG_FILE = CONFIG_DIR / "firewalld-tui.log"

DEFAULT_LOGGING: dict[str, str] = {
    "level": "INFO",
    "rotation": "10 MB",
    "retention": "7 days",
}

_DEFAULT_CONF = """\
[logging]
level = INFO
rotation = 10 MB
retention = 7 days
"""


def load_config() -> dict[str, str]:
    """Load logging settings, creating the config dir/file if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(_DEFAULT_CONF)

    settings = dict(DEFAULT_LOGGING)
    parser = ConfigParser()
    try:
        parser.read(CONFIG_FILE)
        section = parser["logging"] if parser.has_section("logging") else None
    except ConfigParserError as e:
        logger.warning("Invalid config file {}: {}", CONFIG_FILE, e)
        section = None

    if section is None:
        logger.warning("Missing [logging] section in {}, using defaults", CONFIG_FILE)
        return settings

    for key in settings:
        if key in section:
            settings[key] = section[key]
    return settings


class InterceptHandler(logging.Handler):
    """Route stdlib logging (e.g. Textual's) through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


_setup_done = False


def setup_logging() -> None:
    """Configure the loguru file sink from the config file (idempotent)."""
    global _setup_done
    if _setup_done:
        return

    settings = load_config()
    try:
        logger.add(
            LOG_FILE,
            level=settings["level"],
            rotation=settings["rotation"],
            retention=settings["retention"],
        )
    except (ValueError, TypeError, OSError) as e:
        logger.warning(
            "Invalid logging settings in {} ({}), using defaults",
            CONFIG_FILE,
            e,
        )
        logger.add(
            LOG_FILE,
            level=DEFAULT_LOGGING["level"],
            rotation=DEFAULT_LOGGING["rotation"],
            retention=DEFAULT_LOGGING["retention"],
        )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    _setup_done = True
