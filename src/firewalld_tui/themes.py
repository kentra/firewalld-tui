"""Custom Palo Alto PAN-OS style themes for firewalld-tui."""

from __future__ import annotations

from textual.theme import Theme

PANOS_DARK_THEME = Theme(
    name="panos-dark",
    primary="#2d3e50",
    secondary="#3a4f63",
    accent="#ff6b35",
    foreground="#e6eef6",
    background="#0f1e2e",
    surface="#1a2e44",
    panel="#24344e",
    success="#4caf7d",
    warning="#e0a63c",
    error="#e05252",
    dark=True,
)

PANOS_LIGHT_THEME = Theme(
    name="panos-light",
    primary="#2d3e50",
    secondary="#7a8ca3",
    accent="#ff6b35",
    foreground="#1a202c",
    background="#f4f6f8",
    surface="#ffffff",
    panel="#e9eef3",
    success="#2e7d4f",
    warning="#b0791f",
    error="#c0392b",
    dark=False,
)
