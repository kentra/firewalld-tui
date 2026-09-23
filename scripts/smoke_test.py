"""End-to-end smoke test for firewalld-tui.

Runs inside the container against a live firewalld:

    docker exec -i firewalld-tui-test python3 /app/scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import sys

from textual.command import CommandPalette
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Select, Static

from rich.text import Text

from firewalld_tui import firewall
from firewalld_tui.app import (
    AddPolicyModal,
    ConfirmModal,
    FirewalldTUI,
    InputModal,
    ZoneSelectScreen,
)
from firewalld_tui.config import CONFIG_FILE, LOG_FILE, load_policies, load_theme

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


def policy_dict(name: str, **overrides) -> dict:
    """Build an AddPolicyModal result dict with PAN-OS defaults."""
    result = {
        "name": name,
        "description": "",
        "source_zone": "any",
        "source": "any",
        "dest_addr": "any",
        "service": "any",
        "port": "any",
        "action": "allow",
        "log": False,
    }
    result.update(overrides)
    return result


async def run() -> None:
    orig_default = firewall.get_default_zone()
    orig_iface_zone: str | None = None
    dmz_orig_services = (
        firewall.list_services("dmz") if "dmz" in firewall.get_zones() else []
    )

    app = FirewalldTUI()
    async with app.run_test() as pilot:
        await pilot.pause()

        # --- initial load ---
        print("initial load")
        check(bool(app.zones), "zones loaded")
        check(app.current_zone in app.zones, f"initial current_zone={app.current_zone!r}")
        header = widget_text(app.query_one("#zone-header"))
        check(f"Zone: {app.current_zone}" in header, f"header shows current zone ({header!r})")
        check("panos-dark" in app.available_themes, "panos-dark theme registered")
        check("panos-light" in app.available_themes, "panos-light theme registered")

        # --- policies table structure ---
        print("policies table structure")
        table = app.query_one("#rule-table", DataTable)
        headers = [str(col.label) for col in table.columns.values()]
        check(
            headers
            == [
                "#",
                "Name",
                "Source Zone",
                "Source",
                "Dest Zone",
                "Destination",
                "Service",
                "Action",
            ],
            f"table headers ({headers})",
        )
        check(
            len(app._policy_rows) == table.row_count,
            f"table row_count matches _policy_rows ({table.row_count} vs {len(app._policy_rows)})",
        )
        panel_text = "\n".join(
            widget_text(w) for w in app.query_one("#zone-details").children
        )
        check("Zone:" in panel_text, "lower panel shows zone meta")
        if app._policy_rows:
            check(
                app._policy_rows[0].detail in panel_text,
                "lower panel shows selected policy detail",
            )
        check(
            firewall._target_action("%%REJECT%%") == "reject"
            and firewall._target_action("%%DROP%%") == "drop"
            and firewall._target_action("default") == "allow",
            "block/drop/default zone targets map to actions",
        )

        # --- header tabs: dashboard / monitor / settings ---
        print("header tabs")
        check(app.active_tab == "policies", "default tab is policies")
        await pilot.press("2")
        await pilot.pause()
        check(app.active_tab == "monitor", "key 2 switches to monitor")
        check(
            app.query_one("#log-filter", Input) is not None,
            "filter bar present",
        )
        # Seed deterministic traffic rows (TEST-NET-3). Wipe previous test
        # rows first so exact-match counts hold across reruns.
        from datetime import datetime

        from firewalld_tui import db as dbmod

        with dbmod.session_scope() as _s:
            _s.query(dbmod.TrafficLog).filter(
                dbmod.TrafficLog.src_ip.in_(["203.0.113.7", "203.0.113.8"])
            ).delete()
        now = datetime.now()
        dbmod.add_traffic_log(
            receive_time=now,
            src_ip="203.0.113.7",
            dst_ip="198.51.100.9",
            dst_port=53,
            proto="udp",
            action="allow",
            rule="Test-DNS",
            app="dns",
            service="dns",
        )
        dbmod.add_traffic_log(
            receive_time=now,
            src_ip="203.0.113.8",
            dst_ip="198.51.100.9",
            dst_port=22,
            proto="tcp",
            action="drop",
            rule="Test-Block",
            app="ssh",
            service="ssh",
        )
        field = app.query_one("#log-filter", Input)
        field.value = ""
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        traffic = app.query_one("#traffic-table", DataTable)
        check(traffic.row_count >= 2, f"monitor shows seeded rows ({traffic.row_count})")
        # PAN-OS filter narrows to one row.
        field.value = "(addr.src in 203.0.113.7) and (action eq allow)"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        check(traffic.row_count == 1, f"filter narrows to 1 row ({traffic.row_count})")
        status = widget_text(app.query_one("#filter-status"))
        check("Filter: OK" in status, f"filter status ok ({status!r})")
        # Invalid filter keeps previous rows and reports the error.
        field.value = "(bogus"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        check(traffic.row_count == 1, "invalid filter keeps previous rows")
        status = widget_text(app.query_one("#filter-status"))
        check("Filter error" in status, "invalid filter reported in status")
        # No-match filter is deterministic across reruns.
        field.value = "(addr.src in 198.51.100.99)"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        check(traffic.row_count == 0, "no-match filter shows 0 rows")

        print("dashboard tab")
        await pilot.click("#htab-dashboard")
        await pilot.pause()
        check(app.active_tab == "dashboard", "header button switches to dashboard")
        await app._refresh_dashboard()
        await pilot.pause()
        sys_text = widget_text(app.query_one("#dash-system"))
        check(
            "CPU" in sys_text and "Memory" in sys_text,
            f"dashboard system line ({sys_text!r})",
        )
        fw_text = widget_text(app.query_one("#dash-fw"))
        check("firewalld" in fw_text, f"dashboard firewall line ({fw_text!r})")
        dash_pol = app.query_one("#dash-policies", DataTable)
        check(
            dash_pol.row_count >= 1,
            f"dashboard top policies populated ({dash_pol.row_count})",
        )

        print("settings tab")
        await pilot.press("4")
        await pilot.pause()
        check(app.active_tab == "settings", "key 4 switches to settings")
        poll_field = app.query_one("#sett-poll", Input)
        check(poll_field.value == "5", f"poll interval loaded ({poll_field.value!r})")
        poll_field.value = "10"
        app.query_one("#sett-save", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check("poll_interval = 10" in CONFIG_FILE.read_text(), "poll interval saved")
        poll_field.value = "5"
        app.query_one("#sett-save", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check("poll_interval = 5" in CONFIG_FILE.read_text(), "poll interval restored")

        print("back to policies")
        await pilot.press("3")
        await pilot.pause()
        check(app.active_tab == "policies", "key 3 switches back to policies")

        # --- toolbar buttons ---
        print("toolbar buttons")
        await pilot.click("#tb-add-policy")
        await pilot.pause()
        check(isinstance(app.screen, AddPolicyModal), "tb-add-policy opens AddPolicyModal")
        app.screen.query_one("#cancel", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, AddPolicyModal), "add policy modal cancelled")
        # Empty table: clone/edit/toggle warn instead of opening modals.
        for btn_id in ("#tb-clone-policy", "#tb-edit-policy", "#tb-toggle-policy"):
            await pilot.click(btn_id)
            await pilot.pause()
            check(
                not isinstance(app.screen, ModalScreen),
                f"{btn_id} no-ops without selection",
            )

        # --- sidebar zone selection ---
        print("sidebar zone selection")
        target = "dmz" if "dmz" in app.zones else app.zones[1]
        # ListView items were appended in app.zones order (unsorted)
        await pick(pilot, "zone-list", app.zones.index(target))
        check(app.current_zone == target, f"selected zone is {target!r} (got {app.current_zone!r})")
        header = widget_text(app.query_one("#zone-header"))
        check(f"Zone: {target}" in header, f"header updated to {target} ({header!r})")
        check(
            table.row_count == len(app._policy_rows) and table.row_count >= 1,
            f"dmz table populated ({table.row_count} rows)",
        )
        panel_text = "\n".join(
            widget_text(w) for w in app.query_one("#zone-details").children
        )
        if app._policy_rows:
            check(
                app._policy_rows[0].detail in panel_text,
                "lower panel shows selected policy detail after zone switch",
            )

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

        # --- a: add policy modal validation (empty name stays open) ---
        print("add policy modal validation (a)")
        await pilot.press("a")
        await pilot.pause()
        check(isinstance(app.screen, AddPolicyModal), "add policy modal opened")
        modal = app.screen
        assert isinstance(modal, AddPolicyModal)
        modal.query_one("#ok", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(isinstance(app.screen, AddPolicyModal), "empty name keeps modal open")
        modal.query_one("#policy-name", Input).value = "Test-Validate"
        modal.query_one("#policy-port", Input).value = "bogus"
        modal.query_one("#ok", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(isinstance(app.screen, AddPolicyModal), "invalid port keeps modal open")
        modal.query_one("#cancel", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, AddPolicyModal), "modal cancelled")

        # --- add service policy via modal submit ---
        print("add service policy via modal")
        all_services = firewall.get_services()
        zone_services = firewall.list_services(target)
        svc = "ssh"
        if svc in zone_services:
            # dmz ships with ssh; remove it first so the add flow is exercised
            firewall.remove_service(svc, target)
            zone_services = firewall.list_services(target)
        if svc not in all_services:
            svc = next(s for s in sorted(all_services) if s not in zone_services)
        await pilot.press("a")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, AddPolicyModal)
        modal.query_one("#policy-name", Input).value = "Test-SSH"
        modal.query_one("#policy-service", Select).value = svc
        modal.query_one("#ok", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, AddPolicyModal), "modal submitted")
        check(svc in firewall.list_services(target), f"service {svc} added to {target}")
        svc_rows = [r for r in app._policy_rows if r.kind == "service" and r.ref == svc]
        check(bool(svc_rows), f"service {svc} policy present in table")
        if svc == "ssh" and svc_rows:
            check(
                svc_rows[0].protocol == "tcp"
                and svc_rows[0].service_port == "ssh (22)"
                and svc_rows[0].action == "allow",
                f"ssh policy resolved ({svc_rows[0].protocol}|{svc_rows[0].service_port}|{svc_rows[0].action})",
            )
        if svc_rows:
            panel_text = "\n".join(
                widget_text(w) for w in app.query_one("#zone-details").children
            )
            check(
                svc_rows[0].detail in panel_text,
                "lower panel tracks selected policy after add",
            )

        # --- tb-del-policy: toolbar delete opens confirm, cancel keeps it ---
        print("toolbar delete button (tb-del-policy)")
        await pilot.click("#tb-del-policy")
        await pilot.pause()
        check(isinstance(app.screen, ConfirmModal), "tb-del-policy opens confirm modal")
        app.screen.query_one("#no", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, ConfirmModal), "delete confirm cancelled")
        check(svc in firewall.list_services(target), "policy kept after cancel")

        # --- c: clone policy (prefilled Copy of, tweak, submit) ---
        print("clone policy (c)")
        table = app.query_one("#rule-table", DataTable)
        svc_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "service" and r.ref == svc
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=svc_idx, animate=False)
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        check(isinstance(app.screen, AddPolicyModal), "clone opens policy dialog")
        modal = app.screen
        assert isinstance(modal, AddPolicyModal)
        check(
            modal.query_one("#policy-name", Input).value == "Copy of Test-SSH",
            "clone name prefilled as Copy of",
        )
        check(
            modal.query_one("#policy-service", Select).value == svc,
            "clone service prefilled",
        )
        # Tweak to a port so the clone does not collide with the original.
        modal.query_one("#policy-service", Select).value = "any"
        modal.query_one("#policy-port", Input).value = "9999/tcp"
        modal.query_one("#ok", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, AddPolicyModal), "clone submitted")
        check("9999/tcp" in firewall.list_ports(target), f"cloned port added to {target}")
        check(
            any(r.kind == "port" and r.ref == "9999/tcp" for r in app._policy_rows),
            "cloned policy present in table",
        )
        check(
            load_policies().get("9999/tcp", {}).get("name") == "Copy of Test-SSH",
            "clone name stored",
        )

        # --- e: edit policy (prefilled, rename, submit) ---
        print("edit policy (e)")
        table = app.query_one("#rule-table", DataTable)
        svc_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "service" and r.ref == svc
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=svc_idx, animate=False)
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        check(isinstance(app.screen, AddPolicyModal), "edit opens policy dialog")
        modal = app.screen
        assert isinstance(modal, AddPolicyModal)
        check(
            modal.query_one("#policy-name", Input).value == "Test-SSH",
            "edit name prefilled",
        )
        modal.query_one("#policy-name", Input).value = "Test-SSH-Renamed"
        modal.query_one("#ok", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, AddPolicyModal), "edit submitted")
        check(
            load_policies().get(svc, {}).get("name") == "Test-SSH-Renamed",
            "rename stored",
        )
        check(
            svc in firewall.list_services(target),
            "service still present after rename-only edit",
        )

        # --- enter on table opens edit dialog ---
        print("enter opens edit (table focus)")
        table = app.query_one("#rule-table", DataTable)
        table.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        check(isinstance(app.screen, AddPolicyModal), "enter opens edit dialog")
        app.screen.query_one("#cancel", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, AddPolicyModal), "edit cancelled")

        # --- space: disable policy (removed, dimmed) then enable ---
        print("disable/enable policy (space)")
        table = app.query_one("#rule-table", DataTable)
        svc_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "service" and r.ref == svc
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=svc_idx, animate=False)
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        check(svc not in firewall.list_services(target), "service removed on disable")
        dim_rows = [r for r in app._policy_rows if r.kind == "service" and r.ref == svc]
        check(len(dim_rows) == 1, "disabled row kept in table")
        dim_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "service" and r.ref == svc
        )
        cells = list(table.get_row_at(dim_idx))
        check(
            isinstance(cells[1], Text) and "dim" in str(cells[1].style),
            "disabled row rendered dimmed",
        )
        # Reload shifted rows; re-select the disabled row before enabling.
        table = app.query_one("#rule-table", DataTable)
        dim_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "service" and r.ref == svc
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=dim_idx, animate=False)
        await pilot.pause()
        check(
            "Enable" in str(app.query_one("#tb-toggle-policy", Button).label),
            "toggle button flips to Enable",
        )
        await pilot.press("space")
        await pilot.pause()
        check(svc in firewall.list_services(target), "service re-added on enable")
        check(
            "Disable" in str(app.query_one("#tb-toggle-policy", Button).label),
            "toggle button flips back to Disable",
        )

        # --- cleanup cloned port via delete key ---
        print("cleanup cloned port")
        table = app.query_one("#rule-table", DataTable)
        clone_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "port" and r.ref == "9999/tcp"
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=clone_idx, animate=False)
        await pilot.pause()
        await pilot.press("delete")
        await pilot.pause()
        check(isinstance(app.screen, ConfirmModal), "delete opens confirm modal")
        app.screen.query_one("#yes", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check("9999/tcp" not in firewall.list_ports(target), "cloned port removed")
        check(
            not any(r.kind == "port" and r.ref == "9999/tcp" for r in app._policy_rows),
            "cloned policy removed from table",
        )

        # --- delete key: remove service policy with confirm ---
        print("delete service policy (delete + confirm)")
        table = app.query_one("#rule-table", DataTable)
        svc_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "service" and r.ref == svc
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=svc_idx, animate=False)
        await pilot.pause()
        await pilot.press("delete")
        await pilot.pause()
        check(isinstance(app.screen, ConfirmModal), "delete opens confirm modal")
        app.screen.query_one("#yes", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(not isinstance(app.screen, ConfirmModal), "confirm closed")
        check(svc not in firewall.list_services(target), f"service {svc} removed from {target}")
        check(
            not any(r.kind == "service" and r.ref == svc for r in app._policy_rows),
            "service policy removed from table",
        )

        # --- add/remove port policy via handler ---
        print("add/remove port policy")
        app._handle_add_policy(policy_dict("Test-Port", port="8080/tcp"))
        await pilot.pause()
        check("8080/tcp" in firewall.list_ports(target), f"port 8080/tcp added to {target}")
        port_rows = [r for r in app._policy_rows if r.kind == "port" and r.ref == "8080/tcp"]
        check(
            bool(port_rows)
            and port_rows[0].protocol == "tcp"
            and port_rows[0].service_port == "8080"
            and port_rows[0].action == "allow",
            f"port policy in table ({port_rows[0] if port_rows else None})",
        )
        table = app.query_one("#rule-table", DataTable)
        port_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "port" and r.ref == "8080/tcp"
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=port_idx, animate=False)
        await pilot.pause()
        await pilot.press("delete")
        await pilot.pause()
        app.screen.query_one("#yes", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check("8080/tcp" not in firewall.list_ports(target), f"port 8080/tcp removed from {target}")
        check(
            not any(r.kind == "port" and r.ref == "8080/tcp" for r in app._policy_rows),
            "port policy removed from table",
        )

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

        # --- add/remove source policy via handler ---
        print("add/remove source policy")
        source = "10.0.0.0/24"
        app._handle_add_policy(policy_dict("Test-Source", source=source))
        await pilot.pause()
        check(source in firewall.list_sources(target), f"source {source} added to {target}")
        src_rows = [r for r in app._policy_rows if r.kind == "source" and r.ref == source]
        check(bool(src_rows), "source policy present in table")
        if src_rows:
            expected = firewall._target_action(firewall.list_zone(target).target)
            check(
                src_rows[0].action == expected,
                f"source policy action matches zone target ({src_rows[0].action} vs {expected})",
            )
        table = app.query_one("#rule-table", DataTable)
        src_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "source" and r.ref == source
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=src_idx, animate=False)
        await pilot.pause()
        await pilot.press("delete")
        await pilot.pause()
        app.screen.query_one("#yes", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        check(source not in firewall.list_sources(target), f"source {source} removed from {target}")
        check(
            not any(r.kind == "source" and r.ref == source for r in app._policy_rows),
            "source policy removed from table",
        )

        # --- add rich policy with drop, delete its table row ---
        print("add/remove drop policy (rich)")
        app._handle_add_policy(
            policy_dict("Test-Drop", source="10.9.9.9", action="drop")
        )
        await pilot.pause()
        # firewalld normalizes quotes ('ipv4' -> "ipv4"), so match on the address
        stored = [r for r in firewall.list_rich_rules(target) if "10.9.9.9" in r]
        check(bool(stored), "drop policy added")
        rich_idx = next(
            (
                i
                for i, r in enumerate(app._policy_rows)
                if r.kind == "rich" and "10.9.9.9" in r.ref
            ),
            None,
        )
        check(rich_idx is not None, "drop policy present in table")
        if rich_idx is not None:
            rr = app._policy_rows[rich_idx]
            check(
                rr.source == "10.9.9.9" and rr.action == "drop",
                f"drop policy parsed ({rr.source}|{rr.action})",
            )
            table = app.query_one("#rule-table", DataTable)
            table.focus()
            await pilot.pause()
            table.move_cursor(row=rich_idx, animate=False)
            await pilot.pause()
            await pilot.press("delete")
            await pilot.pause()
            check(isinstance(app.screen, ConfirmModal), "delete opens confirm modal")
            app.screen.query_one("#yes", Button).focus()
            await pilot.press("enter")
            await pilot.pause()
            check(
                not [r for r in firewall.list_rich_rules(target) if "10.9.9.9" in r],
                "drop policy removed",
            )
            check(
                not any(
                    r.kind == "rich" and "10.9.9.9" in r.ref
                    for r in app._policy_rows
                ),
                "drop policy removed from table",
            )

        # --- t: toggle runtime/permanent ---
        print("toggle mode (t)")
        await pilot.press("t")
        await pilot.pause()
        mode = widget_text(app.query_one("#mode-indicator"))
        check("Permanent" in mode, f"indicator shows Permanent ({mode!r})")
        perm_port = "9090/tcp"
        app._handle_add_policy(policy_dict("Test-Perm", port=perm_port))
        await pilot.pause()
        check(perm_port in firewall.list_ports(target, permanent=True), "port added in permanent mode")
        table = app.query_one("#rule-table", DataTable)
        perm_idx = next(
            i
            for i, r in enumerate(app._policy_rows)
            if r.kind == "port" and r.ref == perm_port
        )
        table.focus()
        await pilot.pause()
        table.move_cursor(row=perm_idx, animate=False)
        await pilot.pause()
        await pilot.press("delete")
        await pilot.pause()
        app.screen.query_one("#yes", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
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

        # --- f1: theme picker + persistence ---
        print("theme picker (f1)")
        orig_theme = app.theme
        await pilot.press("f1")
        await pilot.pause()
        check(isinstance(app.screen, CommandPalette), "theme picker opened on f1")
        await pilot.press("escape")
        await pilot.pause()
        check(not isinstance(app.screen, CommandPalette), "theme picker closed on escape")
        check(app.theme == orig_theme, "theme unchanged after open/close")

        test_theme = "panos-dark"
        app.theme = test_theme
        await pilot.pause()
        check(app.theme == test_theme, f"theme applied ({test_theme})")
        conf_text = CONFIG_FILE.read_text()
        check(f"theme = {test_theme}" in conf_text, "theme saved to conf file")
        check("[logging]" in conf_text, "logging section preserved on theme save")
        check(load_theme() == test_theme, "load_theme returns saved theme")

        app.theme = orig_theme
        await pilot.pause()
        check(f"theme = {orig_theme}" in CONFIG_FILE.read_text(), "original theme restored in conf")

    # --- invalid theme name falls back to default ---
    print("invalid theme fallback")
    good_conf = CONFIG_FILE.read_text()
    CONFIG_FILE.write_text(
        good_conf.replace(f"theme = {load_theme()}", "theme = bogus-theme")
    )
    app2 = FirewalldTUI()
    check(app2.theme == "textual-dark", f"invalid theme falls back to default (got {app2.theme!r})")
    check("bogus-theme" in LOG_FILE.read_text(), "fallback warning logged to file")
    CONFIG_FILE.write_text(good_conf)

    # --- teardown: restore interface binding, default zone, dmz services ---
    if orig_iface_zone and ifaces:
        firewall.add_interface(iface, orig_iface_zone)
    firewall.set_default_zone(orig_default)
    for s in dmz_orig_services:
        if s not in firewall.list_services("dmz"):
            firewall.add_service(s, "dmz")


asyncio.run(run())

if failures:
    print(f"\n{len(failures)} check(s) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll checks passed.")
