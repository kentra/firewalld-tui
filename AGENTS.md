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
├── app.py        # Textual TUI app (main UI, screens, modals incl. AddPolicyModal)
├── firewall.py   # Subprocess wrapper for firewall-cmd commands
├── config.py     # loguru setup + policies.json store; ~/.firewalld-tui/firewalld-tui.conf
├── themes.py     # panos-dark / panos-light Textual Theme objects
└── __init__.py   # Entry point, exports main(); calls setup_logging()
scripts/
├── docker-start.sh  # Container entrypoint (dbus + firewalld)
└── smoke_test.py    # Pilot-based e2e test of all TUI bindings
```

- `firewall.py` calls `firewall-cmd` via subprocess, not D-Bus; `policy_rows_from_info()` synthesizes table rows (rich rules → services → ports → sources), resolving service protocols/ports from `/usr/lib/firewalld/services/*.xml` (`RuleRow`/`rule_rows_from_info`/`build_rule_rows` are backwards-compat aliases)
- `app.py` contains all Textual widgets, screens, and keyboard bindings; terminology is PAN-OS ("policies", not "rules"); bottom toolbar is `+ Add` / `- Delete` / `Clone` / `Edit` / `Disable|Enable` (`tb-add-policy`, `tb-del-policy`, `tb-clone-policy`, `tb-edit-policy`, `tb-toggle-policy`) — no top toolbar
- Policy names + disabled state live in `~/.firewalld-tui/policies.json` keyed by firewalld ref (`config.load_policies`/`save_policy`/`set_policy_enabled`/`is_policy_disabled`/`delete_policy`); firewalld has no native named/disabled rules
- `AddPolicyModal` is reused for Add/Clone/Edit via `initial` dict + `title`; `_apply_policy_result()` does the firewalld write (returns ref), callers handle notify/reload; edit is add-then-delete (delete skipped when ref unchanged)
- Disabled policies are removed from firewalld but kept as dimmed rows (`rich.text.Text(style="dim")` — DataTable has no per-row disabled); merged in `load_zone_details` via `_disabled_rows_for_zone`, filtered by stored `zone` + `permanent` mode
- No test suite exists yet (smoke_test.py is the e2e coverage)

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
- `#rule-table` rows are parallel to `app._policy_rows` (both rebuilt in `load_zone_details`, now including disabled rows); the Delete key opens a `ConfirmModal` then removes the selected row's firewall object via `action_delete_policy`/`_do_delete_policy` — keep them in sync
- Enter on the table opens Edit via `App.on_key` (focus-scoped, modals excluded) — don't use `DataTable.RowSelected` for this, it also fires on click
- `Select(value=...)` must match an option; `AddPolicyModal` falls back to `"any"` for unknown initial values
- Textual 8 gotchas: `str(widget)` returns `"Label()"` not the text (use `ListItem(..., name=value)` / `event.item.name`); `ListView` uses `.index` not `.highlighted`; widget content is `.content` not `.renderable`
- Don't call `query_one()` inside `compose()` — widgets aren't mounted yet; pass values via `Input(value=...)` instead

## Logging

- loguru writes to `~/.firewalld-tui/firewalld-tui.log` (in Docker: `/root/.firewalld-tui/`)
- `level`, `rotation`, `retention` are set in `~/.firewalld-tui/firewalld-tui.conf` (`[logging]` section, created with defaults on first run)
- `[ui] theme` in the same conf stores the Textual theme name; F1 opens Textual's fuzzy theme picker, `FirewalldTUI.watch_theme` persists changes (unknown names fall back to `textual-dark` with a logged warning)
- Config/logging setup lives in `config.py`; `firewall.py` logs every `firewall-cmd` call (DEBUG) and failures, `app.py` logs errors + successful mutations (INFO)
