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


def load_config() -> tuple[dict[str, str], list[str]]:
    """Load logging settings, creating the config dir/file if needed.

    Returns the settings plus any warnings (emitted later, once the file
    sink exists, so loguru never writes to stderr).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(_DEFAULT_CONF)

    settings = dict(DEFAULT_LOGGING)
    warnings: list[str] = []
    parser = ConfigParser()
    section = None
    try:
        parser.read(CONFIG_FILE)
        if parser.has_section("logging"):
            section = parser["logging"]
        else:
            warnings.append(
                f"Missing [logging] section in {CONFIG_FILE}, using defaults"
            )
    except ConfigParserError as e:
        warnings.append(f"Invalid config file {CONFIG_FILE}: {e}")

    if section is not None:
        for key in settings:
            if key in section:
                settings[key] = section[key]
    return settings, warnings


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
    """Configure the loguru file sink from the config file (idempotent).

    The file is the only destination: the default stderr sink is removed so
    log output cannot bleed into the TUI.
    """
    global _setup_done
    if _setup_done:
        return

    settings, config_warnings = load_config()

    # Drop loguru's default stderr sink so the file is the only destination.
    logger.remove()

    sink_ok = False
    try:
        logger.add(
            LOG_FILE,
            level=settings["level"],
            rotation=settings["rotation"],
            retention=settings["retention"],
        )
        sink_ok = True
    except (ValueError, TypeError, OSError) as e:
        try:
            logger.add(
                LOG_FILE,
                level=DEFAULT_LOGGING["level"],
                rotation=DEFAULT_LOGGING["rotation"],
                retention=DEFAULT_LOGGING["retention"],
            )
            sink_ok = True
            logger.warning(
                "Invalid logging settings in {} ({}), using defaults",
                CONFIG_FILE,
                e,
            )
        except (ValueError, TypeError, OSError) as e2:
            print(f"firewalld-tui: could not open log file {LOG_FILE}: {e2}")

    if sink_ok:
        for message in config_warnings:
            logger.warning(message)
    else:
        for message in config_warnings:
            print(f"firewalld-tui: {message}")

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    _setup_done = True
