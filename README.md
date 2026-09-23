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
| `Delete` | Remove selected rule row |
| `t` | Toggle runtime/permanent mode |
| `F1` | Change theme (fuzzy picker) |

## Features

- **Zone Management** - List zones, view details, set default zone
- **Rules Table** - PanOS-style table of Source, Destination, Protocol, Service/Port, and Action, synthesized from services, ports, sources, and rich rules
- **Toolbar** - One-click buttons for adding services, ports, sources, and rich rules
- **Detail Panel** - Lower panel shows the selected rule's detail plus zone metadata
- **Service/Port Rules** - Add, remove, list services and ports
- **Interface/Source Binding** - Bind interfaces or source IPs to zones
- **Rich Rules** - View and manage rich language rules
- **Runtime vs Permanent** - Toggle between runtime and permanent configurations
