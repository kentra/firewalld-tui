# firewalld-tui

A terminal user interface for managing firewalld, built with [Textual](https://github.com/Textualize/textual).

## Requirements

- Python 3.12+
- `firewalld` installed and running
- `firewall-cmd` available in PATH

## Installation

```bash
uv sync
```

## Usage

```bash
uv run firewalld-tui
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh |
| `d` | Set default zone |
| `a` | Add policy (PAN-OS style Security Policy Rule dialog) |
| `Delete` | Delete selected policy (with confirmation) |
| `c` | Clone selected policy (pre-filled dialog) |
| `e` / `Enter` | Edit selected policy (pre-filled dialog) |
| `Space` / `x` | Disable / Enable selected policy |
| `i` | Add interface |
| `I` | Remove interface |
| `t` | Toggle runtime/permanent mode |
| `F1` | Change theme (includes `panos-dark` / `panos-light`) |
| `1`–`4` | Switch tab: Dashboard / Monitor / Policies / Settings |
| `/` | Jump to Monitor and focus the filter bar |

The bottom toolbar mirrors these actions PanOS-style: `+ Add`, `- Delete`, `Clone`, `Edit`, `Disable`/`Enable`.

## Features

- **Security Policies** - PAN-OS style policy table (`#`, Name, Source Zone, Source, Dest Zone, Destination, Service, Action)
- **Add Policy dialog** - Tabbed modal (General / Source / Destination / Service / Action) with Name, validation, and Allow/Drop/Deny actions; reused for Clone (`Copy of …`) and Edit (pre-filled)
- **Disable / Enable** - Disabled policies are removed from firewalld but kept as dimmed rows; Enable re-adds them
- **Zone Management** - List zones, view details, set default zone
- **Interface Binding** - Bind interfaces to zones
- **Runtime vs Permanent** - Toggle between runtime and permanent configurations
- **Themes** - `panos-dark` and `panos-light` Palo Alto inspired themes alongside the built-in Textual themes

Policy names (plus disabled state) are stored in `~/.firewalld-tui/policies.json` keyed by firewalld ref (firewalld itself has no named or disabled rules).

## Tabs

- **Dashboard** - System resources, firewall info, top policies and top talkers (7-day hits from the traffic DB)
- **Monitor** - PAN-OS style traffic log table with a filter bar accepting Palo Alto syntax, e.g. `(addr.src in 10.0.0.0/24) and (action eq allow)`
- **Policies** - Zones sidebar + policy table (the main screen)
- **Settings** - Live editor for `~/.firewalld-tui/firewalld-tui.conf` (`[logging]`, `[ui]` theme, `[dashboard]` poll interval, `[monitor]` max rows)

Traffic events are logged to `~/.firewalld-tui/traffic.db` (SQLite, 7-day retention) by a background thread tailing kernel nftables logs while the app runs. The Monitor is empty until real traffic is logged (enable `LogDenied` or per-policy logging).
