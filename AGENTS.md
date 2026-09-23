# AGENTS.md

## Setup

Requires Python 3.12+ and firewalld running. Uses `uv` for package management.

```bash
uv sync              # Install dependencies
uv run firewalld-tui # Run the TUI (needs firewall-cmd in PATH)
```

## Project Structure

```
src/firewalld_tui/
├── app.py        # Textual TUI app (main UI, screens, modals)
├── firewall.py   # Subprocess wrapper for firewall-cmd commands
└── __init__.py   # Entry point, exports main()
scripts/
├── docker-start.sh  # Container entrypoint (dbus + firewalld)
└── smoke_test.py    # Pilot-based e2e test of all TUI bindings
```

- `firewall.py` calls `firewall-cmd` via subprocess, not D-Bus
- `app.py` contains all Textual widgets, screens, and keyboard bindings
- No test suite exists yet

## Docker Testing

```bash
docker compose build
docker compose up -d
docker exec -it firewalld-tui-test firewalld-tui
```

After changing `app.py`, run the smoke test (exercises every binding end-to-end against live firewalld):

```bash
docker compose build && docker compose up -d --force-recreate
docker exec -i firewalld-tui-test python3 /app/scripts/smoke_test.py
```

Container starts dbus + firewalld directly (no systemd). Requires `NET_ADMIN` capability.

## Key Commands

```bash
uv add <pkg>       # Add dependency
uv run python -m py_compile src/firewalld_tui/app.py  # Syntax check
```

No linter or formatter is configured.

## Gotchas

- `firewall-cmd` must be available and firewalld must be running for the TUI to work
- `app.py` uses reactive properties (`current_zone`, `permanent_mode`) to drive UI updates
- Widget IDs must be unique; mounting a duplicate ID causes Textual errors
- The `#zone-header` widget is created in `compose()` and updated in-place via `.update()` — don't mount a new one
- Textual 8 gotchas: `str(widget)` returns `"Label()"` not the text (use `ListItem(..., name=value)` / `event.item.name`); `ListView` uses `.index` not `.highlighted`; widget content is `.content` not `.renderable`
- Don't call `query_one()` inside `compose()` — widgets aren't mounted yet; pass values via `Input(value=...)` instead
