"""End-to-end smoke test for firewalld-tui.

Runs inside the container against a live firewalld:

    docker exec -i firewalld-tui-test python3 /app/scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import sys

from textual.widgets import Button, Input, Static

from firewalld_tui import firewall
from firewalld_tui.app import (
    FirewalldTUI,
    InputModal,
    ServiceSelectScreen,
    ZoneSelectScreen,
)

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'ok' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)


def widget_text(widget) -> str:
    if hasattr(widget, "content"):
        return str(widget.content)
    if hasattr(widget, "renderable") and widget.renderable is not None:
        return str(widget.renderable)
    return str(widget)


async def pick(pilot, list_id: str, index: int) -> None:
    """Focus a ListView, highlight `index`, and press enter."""
    await pilot.pause()
    lv = pilot.app.screen.query_one(f"#{list_id}")
    lv.focus()
    await pilot.pause()
    lv.index = index
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


async def fill_input(pilot, value: str, submit: bool = True) -> None:
    """Set the InputModal field value and submit via enter or the OK button."""
    await pilot.pause()
    field = pilot.app.screen.query_one("#input-field", Input)
    field.value = value
    await pilot.pause()
    if submit:
        await pilot.press("enter")
    else:
        pilot.app.screen.query_one("#ok", Button).focus()
        await pilot.press("enter")
    await pilot.pause()


async def run() -> None:
    orig_default = firewall.get_default_zone()
    orig_iface_zone: str | None = None

    app = FirewalldTUI()
    async with app.run_test() as pilot:
        await pilot.pause()

        # --- initial load ---
        print("initial load")
        check(bool(app.zones), "zones loaded")
        check(app.current_zone in app.zones, f"initial current_zone={app.current_zone!r}")
        header = widget_text(app.query_one("#zone-header"))
        check(f"Zone: {app.current_zone}" in header, f"header shows current zone ({header!r})")

        # --- sidebar zone selection ---
        print("sidebar zone selection")
        target = "dmz" if "dmz" in app.zones else app.zones[1]
        # ListView items were appended in app.zones order (unsorted)
        await pick(pilot, "zone-list", app.zones.index(target))
        check(app.current_zone == target, f"selected zone is {target!r} (got {app.current_zone!r})")
        header = widget_text(app.query_one("#zone-header"))
        check(f"Zone: {target}" in header, f"header updated to {target} ({header!r})")

        # --- d: set default zone ---
        print("set default zone (d)")
        await pilot.press("d")
        await pilot.pause()
        check(isinstance(app.screen, ZoneSelectScreen), "zone select modal opened")
        new_default = "work" if "work" in app.zones else app.zones[-1]
        await pick(pilot, "select-list", sorted(app.zones).index(new_default))
        check(firewall.get_default_zone() == new_default, f"default zone is now {new_default}")
        check(app.current_zone == target, "current zone preserved after set-default")
        await pilot.press("d")
        await pilot.pause()
        await pick(pilot, "select-list", sorted(app.zones).index(orig_default))
        check(firewall.get_default_zone() == orig_default, "default zone restored")

        # --- a/x: add/remove service ---
        print("add/remove service (a/x)")
        zone_services = firewall.list_services(target)
        svc = next(s for s in sorted(firewall.get_services()) if s not in zone_services)
        await pilot.press("a")
        await pilot.pause()
        check(isinstance(app.screen, ServiceSelectScreen), "service select modal opened")
        await pick(pilot, "service-list", sorted(firewall.get_services()).index(svc))
        check(svc in firewall.list_services(target), f"service {svc} added to {target}")
        await pilot.press("x")
        await pilot.pause()
        zone_services = firewall.list_services(target)
        await pick(pilot, "service-list", sorted(zone_services).index(svc))
        check(svc not in firewall.list_services(target), f"service {svc} removed from {target}")

        # --- cancel path: a then cancel ---
        print("service modal cancel path")
        await pilot.press("a")
        await pilot.pause()
        check(isinstance(app.screen, ServiceSelectScreen), "service modal opened for cancel test")
        pilot.app.screen.query_one("#cancel", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, ServiceSelectScreen), "cancel closed the modal")
        check(app.current_zone == target, "current zone unchanged after cancel")

        # --- p: add port (InputModal must not crash) ---
        print("add port (p)")
        await pilot.press("p")
        await pilot.pause()
        check(isinstance(app.screen, InputModal), "input modal opened for add port")
        field = app.screen.query_one("#input-field", Input)
        check(field.value == "", f"input prefilled empty (got {field.value!r})")
        await fill_input(pilot, "8080/tcp")
        check("8080/tcp" in firewall.list_ports(target), f"port 8080/tcp added to {target}")

        # --- cancel path: p then cancel ---
        print("port modal cancel path")
        await pilot.press("p")
        await pilot.pause()
        pilot.app.screen.query_one("#cancel", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, InputModal), "cancel closed the port modal")

        # --- P: remove port (via OK button) ---
        print("remove port (P)")
        await pilot.press("P")
        await pilot.pause()
        check(isinstance(app.screen, InputModal), "input modal opened for remove port")
        await fill_input(pilot, "8080/tcp", submit=False)
        check("8080/tcp" not in firewall.list_ports(target), f"port 8080/tcp removed from {target}")

        # --- i/I: add/remove interface ---
        print("add/remove interface (i/I)")
        from pathlib import Path

        ifaces = [p.name for p in Path("/sys/class/net").iterdir() if p.name != "lo"]
        if ifaces:
            iface = ifaces[0]
            try:
                orig_iface_zone = firewall.get_zone_of_interface(iface) or None
            except RuntimeError:
                orig_iface_zone = None
            if orig_iface_zone and orig_iface_zone != target:
                firewall.remove_interface(iface, orig_iface_zone)
            await pilot.press("i")
            await pilot.pause()
            check(isinstance(app.screen, InputModal), "input modal opened for add interface")
            await fill_input(pilot, iface)
            check(iface in firewall.list_interfaces(target), f"interface {iface} added to {target}")
            await pilot.press("I")
            await pilot.pause()
            check(isinstance(app.screen, ZoneSelectScreen), "interface select modal opened")
            await pick(pilot, "select-list", sorted(firewall.list_interfaces(target)).index(iface))
            check(iface not in firewall.list_interfaces(target), f"interface {iface} removed from {target}")
        else:
            print("  [skip] no non-lo interface found")

        # --- s/S: add/remove source ---
        print("add/remove source (s/S)")
        source = "10.0.0.0/24"
        await pilot.press("s")
        await pilot.pause()
        check(isinstance(app.screen, InputModal), "input modal opened for add source")
        await fill_input(pilot, source)
        check(source in firewall.list_sources(target), f"source {source} added to {target}")
        await pilot.press("S")
        await pilot.pause()
        check(isinstance(app.screen, ZoneSelectScreen), "source select modal opened")
        await pick(pilot, "select-list", sorted(firewall.list_sources(target)).index(source))
        check(source not in firewall.list_sources(target), f"source {source} removed from {target}")

        # --- R/delete: add/remove rich rule ---
        print("add/remove rich rule (R/delete)")
        rule = "rule family='ipv4' source address='10.9.9.9' drop"
        await pilot.press("R")
        await pilot.pause()
        check(isinstance(app.screen, InputModal), "input modal opened for add rich rule")
        await fill_input(pilot, rule)
        # firewalld normalizes quotes ('ipv4' -> "ipv4"), so match on the address
        stored = [r for r in firewall.list_rich_rules(target) if "10.9.9.9" in r]
        check(bool(stored), "rich rule added")
        await pilot.press("delete")
        await pilot.pause()
        check(isinstance(app.screen, ZoneSelectScreen), "rich rule select modal opened")
        if stored:
            await pick(pilot, "select-list", sorted(firewall.list_rich_rules(target)).index(stored[0]))
        check(not [r for r in firewall.list_rich_rules(target) if "10.9.9.9" in r], "rich rule removed")

        # --- t: toggle runtime/permanent ---
        print("toggle mode (t)")
        await pilot.press("t")
        await pilot.pause()
        mode = widget_text(app.query_one("#mode-indicator"))
        check("Permanent" in mode, f"indicator shows Permanent ({mode!r})")
        perm_port = "9090/tcp"
        await pilot.press("p")
        await pilot.pause()
        await fill_input(pilot, perm_port)
        check(perm_port in firewall.list_ports(target, permanent=True), "port added in permanent mode")
        await pilot.press("P")
        await pilot.pause()
        await fill_input(pilot, perm_port, submit=False)
        check(perm_port not in firewall.list_ports(target, permanent=True), "port removed in permanent mode")
        await pilot.press("t")
        await pilot.pause()
        mode = widget_text(app.query_one("#mode-indicator"))
        check("Runtime" in mode, f"indicator shows Runtime ({mode!r})")

        # --- r: refresh preserves selection ---
        print("refresh (r)")
        await pilot.press("r")
        await pilot.pause()
        check(app.current_zone == target, f"selection preserved after refresh (got {app.current_zone!r})")
        check(bool(app.zones), "zones reloaded")

    # --- teardown: restore interface binding ---
    if orig_iface_zone and ifaces:
        firewall.add_interface(iface, orig_iface_zone)
    firewall.set_default_zone(orig_default)


asyncio.run(run())

if failures:
    print(f"\n{len(failures)} check(s) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll checks passed.")
