"""Firewalld TUI - A terminal interface for managing firewalld."""

from .config import setup_logging

setup_logging()

from .app import FirewalldTUI, main

__all__ = ["FirewalldTUI", "main"]
