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
| `a` | Add service |
| `x` | Remove service |
| `p` | Add port |
| `P` | Remove port |
| `i` | Add interface |
| `I` | Remove interface |
| `s` | Add source |
| `S` | Remove source |
| `R` | Add rich rule |
| `Delete` | Remove rich rule |
| `t` | Toggle runtime/permanent mode |
| `F1` | Toggle dark mode |

## Features

- **Zone Management** - List zones, view details, set default zone
- **Service/Port Rules** - Add, remove, list services and ports
- **Interface/Source Binding** - Bind interfaces or source IPs to zones
- **Rich Rules** - View and manage rich language rules
- **Runtime vs Permanent** - Toggle between runtime and permanent configurations
