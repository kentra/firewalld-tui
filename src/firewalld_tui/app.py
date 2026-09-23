"""Firewalld TUI - PAN-OS style security policy management for firewalld."""

from __future__ import annotations

import ipaddress
import re

from textual import on
from textual.app import App, ComposeResult, InvalidThemeError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    TabbedContent,
    TabPane,
)
from loguru import logger
from rich.text import Text

from . import firewall
from .config import (
    CONFIG_FILE,
    delete_policy as delete_policy_entry,
    is_policy_disabled,
    load_policies,
    load_theme,
    save_policy as save_policy_entry,
    save_theme,
)
from .themes import PANOS_DARK_THEME, PANOS_LIGHT_THEME

BINDINGS = [
    Binding("q", "quit", "Quit"),
    Binding("r", "refresh", "Refresh"),
    Binding("d", "set_default", "Set Default Zone"),
    Binding("a", "add_policy", "Add Policy"),
    Binding("delete", "delete_policy", "Delete Policy"),
    Binding("c", "clone_policy", "Clone Policy"),
    Binding("e", "edit_policy", "Edit Policy"),
    Binding("space", "toggle_policy", "Enable/Disable Policy"),
    Binding("x", "toggle_policy", "Enable/Disable Policy", show=False),
    Binding("i", "add_interface", "Add Interface"),
    Binding("I", "remove_interface", "Remove Interface"),
    Binding("t", "toggle_mode", "Toggle Runtime/Permanent"),
    Binding("f1", "change_theme", "Change Theme"),
]

PORT_RE = re.compile(r"^\d+(-\d+)?/(tcp|udp|sctp|dccp)$")


class InputModal(ModalScreen[str | None]):
    """A modal screen for text input."""

    CSS = """
    InputModal {
        align: center middle;
    }

    #input-container {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #input-label {
        margin-bottom: 1;
    }

    #input-field {
        width: 100%;
        margin-bottom: 1;
    }

    .buttons {
        layout: horizontal;
        height: 3;
        align: center middle;
    }

    .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, title: str, placeholder: str = "", default: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.placeholder = placeholder
        self.default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="input-container"):
            yield Static(self.title_text, id="input-label")
            yield Input(
                placeholder=self.placeholder, value=self.default, id="input-field"
            )
            with Horizontal(classes="buttons"):
                yield Button("OK", id="ok", variant="primary")
                yield Button("Cancel", id="cancel", variant="error")

    @on(Input.Submitted)
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            value = self.query_one("#input-field").value
            self.dismiss(value)
        else:
            self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """A modal screen for confirmation."""

    CSS = """
    ConfirmModal {
        align: center middle;
    }

    #confirm-container {
        width: 50;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
        text-align: center;
    }

    .buttons {
        layout: horizontal;
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    .buttons Button {
        margin: 0 2;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Static(self.message)
            with Horizontal(classes="buttons"):
                yield Button("Yes", id="yes", variant="primary")
                yield Button("No", id="no", variant="error")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class ZoneSelectScreen(ModalScreen[str | None]):
    """Modal to select a zone."""

    CSS = """
    ZoneSelectScreen {
        align: center middle;
    }

    #zone-container {
        width: 50;
        height: 30;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }

    #select-list {
        height: 1fr;
        margin: 1 0;
    }
    """

    def __init__(self, zones: list[str], title: str = "Select a zone:") -> None:
        super().__init__()
        self.zones = sorted(zones)
        self.title_text = title

    def compose(self) -> ComposeResult:
        with Vertical(id="zone-container"):
            yield Static(self.title_text)
            with ListView(id="select-list"):
                for zone in self.zones:
                    yield ListItem(Label(zone), name=zone)
            yield Button("Cancel", id="cancel", variant="error")

    @on(ListView.Selected)
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ListItem) and event.item.name:
            self.dismiss(event.item.name)

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)


class AddPolicyModal(ModalScreen[dict | None]):
    """PAN-OS style Security Policy Rule dialog.

    Tabs: General | Source | Destination | Service | Action.
    Dismisses with a dict describing the policy, or None on cancel.
    """

    CSS = """
    AddPolicyModal {
        align: center middle;
    }

    #policy-container {
        width: 84;
        height: auto;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #policy-title {
        text-style: bold;
        text-align: center;
        color: $accent;
        margin-bottom: 1;
    }

    #policy-tabs {
        height: auto;
        max-height: 42;
        margin-bottom: 1;
    }

    .policy-label {
        text-style: bold;
        margin-top: 1;
    }

    .policy-hint {
        color: $text-muted;
    }

    .buttons {
        layout: horizontal;
        height: 3;
        align: center middle;
    }

    .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        zone: str,
        zones: list[str],
        services: list[str],
        initial: dict | None = None,
        title: str = "Security Policy Rule",
    ) -> None:
        super().__init__()
        self.zone = zone
        self.zones = sorted(zones)
        self.services = sorted(services)
        self.initial = initial or {}
        self.dialog_title = title

    def _initial_value(self, key: str, default: str = "any") -> str:
        value = self.initial.get(key, default)
        return value if isinstance(value, str) and value else default

    def compose(self) -> ComposeResult:
        src_zone = self._initial_value("source_zone")
        if src_zone not in self.zones and src_zone != "any":
            src_zone = "any"
        service = self._initial_value("service")
        if service not in self.services and service != "any":
            service = "any"
        action = self._initial_value("action", "allow")
        if action not in ("allow", "drop", "reject"):
            action = "allow"
        log = self.initial.get("log", False)
        with Vertical(id="policy-container"):
            yield Static(self.dialog_title, id="policy-title")
            with TabbedContent(id="policy-tabs"):
                with TabPane("General", id="tab-general"):
                    yield Static("Name *", classes="policy-label")
                    yield Input(
                        placeholder="e.g. Allow-Web",
                        value=self.initial.get("name", ""),
                        id="policy-name",
                    )
                    yield Static("Description", classes="policy-label")
                    yield Input(
                        placeholder="Optional description",
                        value=self.initial.get("description", ""),
                        id="policy-desc",
                    )
                    yield Static("Type: Security", classes="policy-hint")
                with TabPane("Source", id="tab-source"):
                    yield Static("Source Zone", classes="policy-label")
                    yield Select(
                        [("any", "any")]
                        + [(z, z) for z in self.zones],
                        value=src_zone,
                        id="policy-src-zone",
                    )
                    yield Static("Source Address", classes="policy-label")
                    yield Input(
                        placeholder="any or 10.0.0.0/24",
                        value=self._initial_value("source"),
                        id="policy-src-addr",
                    )
                with TabPane("Destination", id="tab-dest"):
                    yield Static("Destination Zone", classes="policy-label")
                    yield Static(self.zone, id="policy-dst-zone")
                    yield Static("Destination Address", classes="policy-label")
                    yield Input(
                        placeholder="any",
                        value=self._initial_value("dest_addr"),
                        id="policy-dst-addr",
                    )
                with TabPane("Service", id="tab-service"):
                    yield Static("Service", classes="policy-label")
                    yield Select(
                        [("any", "any")]
                        + [(s, s) for s in self.services],
                        value=service,
                        id="policy-service",
                    )
                    yield Static("Port/Protocol", classes="policy-label")
                    yield Input(
                        placeholder="any or 8080/tcp",
                        value=self._initial_value("port"),
                        id="policy-port",
                    )
                    yield Static(
                        "Fill either Service or Port (Port wins if both set).",
                        classes="policy-hint",
                    )
                    yield Static("Application: any", classes="policy-hint")
                with TabPane("Action", id="tab-action"):
                    yield Static("Action", classes="policy-label")
                    yield Select(
                        [
                            ("Allow", "allow"),
                            ("Drop", "drop"),
                            ("Deny (reject)", "reject"),
                        ],
                        value=action,
                        id="policy-action",
                    )
                    yield Checkbox("Enable logging", value=bool(log), id="policy-log")
            with Horizontal(classes="buttons"):
                yield Button("OK", id="ok", variant="primary")
                yield Button("Cancel", id="cancel", variant="error")

    def _invalid(self, message: str) -> None:
        self.notify(message, severity="error")

    def _valid_cidr_or_any(self, value: str, field: str) -> bool:
        if value == "any" or not value:
            return True
        try:
            ipaddress.ip_network(value, strict=False)
            return True
        except ValueError:
            self._invalid(f"Invalid {field}: {value!r} (use 'any' or CIDR)")
            return False

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id != "ok":
            return

        name = self.query_one("#policy-name", Input).value.strip()
        if not name:
            self._invalid("Policy name is required")
            return

        src = self.query_one("#policy-src-addr", Input).value.strip() or "any"
        dst = self.query_one("#policy-dst-addr", Input).value.strip() or "any"
        if not self._valid_cidr_or_any(src, "source address"):
            return
        if not self._valid_cidr_or_any(dst, "destination address"):
            return

        port = self.query_one("#policy-port", Input).value.strip() or "any"
        if port != "any" and not PORT_RE.match(port):
            self._invalid(
                f"Invalid port: {port!r} (use 'any' or PORT/PROTO like 8080/tcp)"
            )
            return

        action = self.query_one("#policy-action", Select).value
        svc = self.query_one("#policy-service", Select).value
        if (
            action != "allow"
            and src == "any"
            and dst == "any"
            and svc == "any"
            and port == "any"
        ):
            self._invalid("Drop/Deny needs a source, destination, or service")
            return

        self.dismiss(
            {
                "name": name,
                "description": self.query_one("#policy-desc", Input).value.strip(),
                "source_zone": self.query_one("#policy-src-zone", Select).value,
                "source": src,
                "dest_addr": dst,
                "service": svc,
                "port": port,
                "action": action,
                "log": self.query_one("#policy-log", Checkbox).value,
            }
        )


class FirewalldTUI(App):
    """Firewalld TUI application."""

    TITLE = "Firewalld TUI"
    SUB_TITLE = "Security Policy Rules"

    CSS = """
    Screen {
        layout: horizontal;
    }

    #sidebar {
        width: 25;
        height: 100%;
        border-right: solid $primary;
        padding: 1;
    }

    #sidebar-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #zone-list {
        height: 1fr;
    }

    #main-content {
        width: 1fr;
        height: 100%;
        padding: 1;
    }

    #zone-header {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
        color: $primary;
    }

    #mode-indicator {
        text-align: center;
        margin-bottom: 1;
        padding: 0 2;
        width: auto;
        min-width: 20;
    }

    #rule-table {
        height: 1fr;
        margin-bottom: 1;
    }

    .detail-row {
        height: auto;
        min-height: 1;
    }

    .detail-label {
        text-style: bold;
        color: $accent;
        min-width: 20;
    }

    #zone-details {
        height: auto;
        max-height: 40%;
        border-top: solid $primary;
        padding-top: 1;
    }

    #action-bar {
        height: auto;
        min-height: 3;
        dock: bottom;
        align: center middle;
        background: $panel;
        border-top: solid $primary;
        padding: 0 1;
    }

    #action-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = BINDINGS

    current_zone: reactive[str | None] = reactive(None)
    permanent_mode: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self.zones: list[str] = []
        self._policy_rows: list[firewall.PolicyRow] = []
        self._zone_info: firewall.ZoneInfo | None = None
        saved_theme = load_theme()
        try:
            self.theme = saved_theme
        except InvalidThemeError:
            logger.warning(
                "Unknown theme {!r} in {}, using default",
                saved_theme,
                CONFIG_FILE,
            )

    def watch_theme(self, theme_name: str) -> None:
        """Persist theme changes (e.g. from the F1 picker) to the config."""
        save_theme(theme_name)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("Zones", id="sidebar-title")
                yield ListView(id="zone-list")
            with Vertical(id="main-content"):
                yield Static("Select a zone", id="zone-header")
                yield Static("Mode: Runtime", id="mode-indicator")
                yield DataTable(
                    id="rule-table", cursor_type="row", zebra_stripes=True
                )
                with VerticalScroll(id="zone-details"):
                    pass
        with Horizontal(id="action-bar"):
            yield Button("+ Add", id="tb-add-policy", variant="primary")
            yield Button("- Delete", id="tb-del-policy", variant="error")
            yield Button("Clone", id="tb-clone-policy")
            yield Button("Edit", id="tb-edit-policy")
            yield Button("Disable", id="tb-toggle-policy", variant="warning")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(PANOS_DARK_THEME)
        self.register_theme(PANOS_LIGHT_THEME)
        table = self.query_one("#rule-table", DataTable)
        for label in (
            "#",
            "Name",
            "Source Zone",
            "Source",
            "Dest Zone",
            "Destination",
            "Service",
            "Action",
        ):
            table.add_column(label)
        self.load_zones()

    def load_zones(self) -> None:
        """Load all zones and display them."""
        try:
            self.zones = firewall.get_zones()
            list_view = self.query_one("#zone-list", ListView)
            list_view.clear()
            for zone in self.zones:
                list_view.append(ListItem(Label(zone), name=zone))
            if self.current_zone not in self.zones:
                self.current_zone = self.zones[0] if self.zones else None
        except RuntimeError as e:
            logger.error("Error loading zones: {}", e)
            self.notify(f"Error loading zones: {e}", severity="error")

    def watch_current_zone(self, new_zone: str | None) -> None:
        """Update details when zone selection changes."""
        if new_zone:
            self.load_zone_details(new_zone)

    def watch_permanent_mode(self, new_val: bool) -> None:
        """Update mode indicator."""
        mode = "Permanent" if new_val else "Runtime"
        self.query_one("#mode-indicator").update(f"Mode: {mode}")
        if self.current_zone:
            self.load_zone_details(self.current_zone)

    @on(ListView.Selected)
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle zone selection."""
        if event.list_view.id != "zone-list" or event.list_view.screen is not self.screen:
            return
        if isinstance(event.item, ListItem) and event.item.name:
            self.current_zone = event.item.name

    def _selected_row(self) -> firewall.PolicyRow | None:
        """Return the currently highlighted policy row, if any."""
        table = self.query_one("#rule-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._policy_rows):
            return self._policy_rows[idx]
        return None

    def _update_toggle_button(self) -> None:
        """Flip the bottom toggle button between Enable/Disable."""
        row = self._selected_row()
        disabled = bool(row and is_policy_disabled(row.ref))
        self.query_one("#tb-toggle-policy", Button).label = (
            "Enable" if disabled else "Disable"
        )

    def _disabled_rows_for_zone(
        self, zone: str, live_refs: set[str], policies: dict
    ) -> list[firewall.PolicyRow]:
        """Rebuild PolicyRows for disabled (TUI-owned) entries of a zone."""
        rows: list[firewall.PolicyRow] = []
        for ref, entry in policies.items():
            if not entry.get("disabled"):
                continue
            if ref in live_refs:
                continue
            if entry.get("zone", zone) != zone:
                continue
            if bool(entry.get("permanent", False)) != self.permanent_mode:
                continue
            if not entry.get("kind"):
                continue
            rows.append(
                firewall.PolicyRow(
                    source=entry.get("source", "any"),
                    destination=entry.get("destination", "any"),
                    protocol=entry.get("protocol", "any"),
                    service_port=entry.get("service_port", "any"),
                    action=entry.get("action", "allow"),
                    kind=entry.get("kind"),
                    ref=ref,
                    detail=entry.get("detail", ref),
                )
            )
        return rows

    def load_zone_details(self, zone: str) -> None:
        """Load zone info and rebuild the policies table."""
        try:
            info = firewall.list_zone(zone, self.permanent_mode)
            self._zone_info = info
            rows = firewall.policy_rows_from_info(info)
            policies = load_policies()
            rows.extend(
                self._disabled_rows_for_zone(
                    zone, {r.ref for r in rows}, policies
                )
            )
            self._policy_rows = rows

            self.query_one("#zone-header").update(f"Zone: {info.name}")

            table = self.query_one("#rule-table", DataTable)
            cursor_row = table.cursor_row
            table.clear()
            for i, row in enumerate(rows, start=1):
                disabled = is_policy_disabled(row.ref)
                name = policies.get(row.ref, {}).get("name", row.ref)
                if disabled:
                    name = f"⏸ {name}"
                if row.protocol not in ("any", ""):
                    service_cell = f"{row.protocol}/{row.service_port}"
                else:
                    service_cell = row.service_port
                cells = [
                    str(i),
                    name,
                    "any",
                    row.source,
                    info.name,
                    row.destination,
                    service_cell,
                    row.action,
                ]
                if disabled:
                    table.add_row(*[Text(c, style="dim") for c in cells])
                else:
                    table.add_row(*cells)
            if rows:
                table.move_cursor(
                    row=min(max(cursor_row, 0), len(rows) - 1),
                    column=0,
                    animate=False,
                )

            self._render_details_panel(self._selected_row())
            self._update_toggle_button()

        except RuntimeError as e:
            logger.error("Error loading zone details: {}", e)
            self.notify(f"Error loading zone details: {e}", severity="error")

    def _render_details_panel(
        self, selected: firewall.PolicyRow | None
    ) -> None:
        """Render the lower panel: selected policy detail + zone meta."""
        panel = self.query_one("#zone-details")
        panel.remove_children()
        info = self._zone_info
        if info is None:
            return

        if selected is not None:
            policies = load_policies()
            name = policies.get(selected.ref, {}).get("name", selected.ref)
            state = "disabled" if is_policy_disabled(selected.ref) else selected.kind
            panel.mount(
                Static(f"Policy '{name}' ({state}):", classes="detail-label")
            )
            panel.mount(Static(selected.detail, classes="detail-row"))

        panel.mount(Static("Zone:", classes="detail-label"))
        target = info.target if info.target else "(default)"
        panel.mount(Static(f"  target: {target}", classes="detail-row"))
        if info.interfaces:
            panel.mount(
                Static(
                    f"  interfaces: {', '.join(info.interfaces)}",
                    classes="detail-row",
                )
            )
        if info.protocols:
            panel.mount(
                Static(
                    f"  protocols: {', '.join(info.protocols)}",
                    classes="detail-row",
                )
            )
        if info.source_ports:
            panel.mount(
                Static(
                    f"  source ports: {', '.join(info.source_ports)}",
                    classes="detail-row",
                )
            )
        if info.forward_ports:
            panel.mount(
                Static(
                    f"  forward ports: {', '.join(info.forward_ports)}",
                    classes="detail-row",
                )
            )
        if info.icmp_blocks:
            panel.mount(
                Static(
                    f"  icmp blocks: {', '.join(info.icmp_blocks)}",
                    classes="detail-row",
                )
            )

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Show the highlighted policy's detail in the lower panel."""
        if event.data_table.id != "rule-table":
            return
        idx = event.cursor_row
        selected = (
            self._policy_rows[idx] if 0 <= idx < len(self._policy_rows) else None
        )
        self._render_details_panel(selected)
        self._update_toggle_button()

    def on_key(self, event) -> None:
        """Open the edit dialog on Enter when the policies table is focused."""
        if event.key != "enter":
            return
        if isinstance(self.screen, ModalScreen):
            return
        focused = self.focused
        if isinstance(focused, DataTable) and focused.id == "rule-table":
            event.prevent_default()
            self.action_edit_policy()

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route bottom toolbar button presses to their actions."""
        action = {
            "tb-add-policy": self.action_add_policy,
            "tb-del-policy": self.action_delete_policy,
            "tb-clone-policy": self.action_clone_policy,
            "tb-edit-policy": self.action_edit_policy,
            "tb-toggle-policy": self.action_toggle_policy,
        }.get(event.button.id or "")
        if action:
            action()

    def action_refresh(self) -> None:
        """Refresh zones and details."""
        self.load_zones()
        if self.current_zone:
            self.load_zone_details(self.current_zone)

    def action_toggle_mode(self) -> None:
        """Toggle between runtime and permanent mode."""
        self.permanent_mode = not self.permanent_mode

    def action_set_default(self) -> None:
        """Set the default zone."""
        self.push_screen(ZoneSelectScreen(self.zones, "Select new default zone:"), self._handle_set_default)

    def _handle_set_default(self, zone: str | None) -> None:
        if zone:
            try:
                if firewall.set_default_zone(zone):
                    logger.info("default zone set to {}", zone)
                    self.notify(f"Default zone set to {zone}")
                    self.action_refresh()
                else:
                    self.notify("Failed to set default zone", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

    def action_add_policy(self) -> None:
        """Open the PAN-OS style Security Policy Rule dialog."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        try:
            zones = firewall.get_zones()
            services = firewall.get_services()
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")
            return
        self.push_screen(
            AddPolicyModal(
                zone=self.current_zone, zones=zones, services=services
            ),
            self._handle_add_policy,
        )

    def _apply_policy_result(self, result: dict) -> str | None:
        """Translate a policy dialog result into firewalld calls.

        Returns the new firewalld ref on success, None on failure.
        Does not touch the table; callers reload afterwards.
        """
        assert self.current_zone is not None
        zone = self.current_zone
        perm = self.permanent_mode
        name = result["name"].strip()
        src = result.get("source", "any") or "any"
        dst = result.get("dest_addr", "any") or "any"
        svc = result.get("service", "any") or "any"
        port = result.get("port", "any") or "any"
        action = result.get("action", "allow")
        log = result.get("log", False)
        try:
            ref: str | None = None
            # A rich rule is only needed when a single firewalld object
            # cannot express the policy: a destination, a non-Allow action,
            # or a source combined with a service/port. A lone source with
            # Allow is a plain zone source binding.
            needs_rich = (
                dst != "any"
                or action != "allow"
                or (src != "any" and (svc != "any" or port != "any"))
            )
            if needs_rich:
                verb = {"allow": "accept", "drop": "drop", "reject": "reject"}[
                    action
                ]
                parts = ["rule family='ipv4'"]
                if src != "any":
                    parts.append(f"source address='{src}'")
                if dst != "any":
                    parts.append(f"destination address='{dst}'")
                if port != "any":
                    pnum, _, proto = port.partition("/")
                    parts.append(f"port port='{pnum}' protocol='{proto or 'tcp'}'")
                elif svc != "any":
                    parts.append(f"service name='{svc}'")
                if log:
                    parts.append(f"log prefix='{name}: '")
                parts.append(verb)
                rule = " ".join(parts)
                before = set(firewall.list_rich_rules(zone, perm))
                if not firewall.add_rich_rule(rule, zone, perm):
                    self.notify(f"Failed to add policy {name}", severity="error")
                    return None
                after = firewall.list_rich_rules(zone, perm)
                new = [r for r in after if r not in before]
                ref = new[0] if new else rule
            elif svc != "any":
                if not firewall.add_service(svc, zone, perm):
                    self.notify(f"Failed to add policy {name}", severity="error")
                    return None
                ref = svc
            elif port != "any":
                if not firewall.add_port(port, zone, perm):
                    self.notify(f"Failed to add policy {name}", severity="error")
                    return None
                ref = port
            elif src != "any":
                if not firewall.add_source(src, zone, perm):
                    self.notify(f"Failed to add policy {name}", severity="error")
                    return None
                ref = src
            else:
                self.notify(
                    "Policy has no effect: everything is 'any' with Allow",
                    severity="warning",
                )
                return None
            save_policy_entry(
                ref, name, result.get("description", "").strip()
            )
            logger.info("added policy {} ({}) to {}", name, ref, zone)
            return ref
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")
            return None

    def _handle_add_policy(self, result: dict | None) -> None:
        """Handle the Add dialog result: apply, notify, reload."""
        if not result:
            return
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        ref = self._apply_policy_result(result)
        if ref is not None:
            self.notify(f"Added policy {result['name'].strip()} to {self.current_zone}")
            assert self.current_zone is not None
            self.load_zone_details(self.current_zone)

    def action_delete_policy(self) -> None:
        """Delete the firewall object behind the selected policy row."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        table = self.query_one("#rule-table", DataTable)
        idx = table.cursor_row
        if not (0 <= idx < len(self._policy_rows)):
            self.notify("No policy selected", severity="warning")
            return
        row = self._policy_rows[idx]
        policies = load_policies()
        name = policies.get(row.ref, {}).get("name", row.ref)
        self.push_screen(
            ConfirmModal(f"Delete policy '{name}'?"),
            lambda confirmed: self._do_delete_policy(bool(confirmed), row),
        )

    def _do_delete_policy(
        self, confirmed: bool, row: firewall.PolicyRow
    ) -> None:
        """Remove the policy after confirmation."""
        if not confirmed or not self.current_zone:
            return
        # Disabled rows are TUI-owned only; nothing to remove from firewalld.
        if is_policy_disabled(row.ref):
            delete_policy_entry(row.ref)
            logger.info("deleted disabled policy {} from {}", row.ref, self.current_zone)
            self.notify(f"Deleted policy from {self.current_zone}")
            self.load_zone_details(self.current_zone)
            return
        removers = {
            "service": firewall.remove_service,
            "port": firewall.remove_port,
            "source": firewall.remove_source,
            "rich": firewall.remove_rich_rule,
        }
        remover = removers[row.kind]
        try:
            if remover(row.ref, self.current_zone, self.permanent_mode):
                delete_policy_entry(row.ref)
                logger.info(
                    "deleted policy {} ({}) from {}",
                    load_policies().get(row.ref, {}).get("name", row.ref),
                    row.ref,
                    self.current_zone,
                )
                self.notify(f"Deleted policy from {self.current_zone}")
                self.load_zone_details(self.current_zone)
            else:
                self.notify(f"Failed to delete {row.ref}", severity="error")
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")

    def _row_to_initial(
        self, row: firewall.PolicyRow, services: list[str]
    ) -> dict:
        """Convert a table row back into AddPolicyModal field values."""
        entry = load_policies().get(row.ref, {})
        initial: dict = {
            "name": entry.get("name", row.ref),
            "description": entry.get("description", ""),
            "source_zone": "any",
            "source": row.source,
            "dest_addr": row.destination,
            "service": "any",
            "port": "any",
            "action": row.action,
            "log": False,
        }
        if row.kind == "service":
            initial["service"] = row.ref if row.ref in services else "any"
        elif row.kind == "port":
            initial["port"] = row.ref
        elif row.kind == "source":
            initial["source"] = row.ref
        elif row.kind == "rich":
            if row.service_port in services:
                initial["service"] = row.service_port
            elif row.service_port not in ("any", ""):
                proto = row.protocol if row.protocol != "any" else "tcp"
                initial["port"] = f"{row.service_port}/{proto}"
        return initial

    def _unique_copy_name(self, name: str) -> str:
        """Generate 'Copy of <name>' uniquified against stored policy names."""
        existing = {
            entry.get("name", "") for entry in load_policies().values()
        }
        candidate = f"Copy of {name}"
        n = 2
        while candidate in existing:
            candidate = f"Copy of {name} ({n})"
            n += 1
        return candidate

    def _open_policy_dialog(
        self, title: str, initial: dict | None, callback
    ) -> None:
        """Push the policy dialog, fetching zones/services first."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        try:
            zones = firewall.get_zones()
            services = firewall.get_services()
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")
            return
        self.push_screen(
            AddPolicyModal(
                zone=self.current_zone,
                zones=zones,
                services=services,
                initial=initial,
                title=title,
            ),
            callback,
        )

    def action_clone_policy(self) -> None:
        """Clone the selected policy via a pre-filled dialog."""
        row = self._selected_row()
        if not row or not self.current_zone:
            self.notify("No policy selected", severity="warning")
            return
        try:
            services = firewall.get_services()
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")
            return
        initial = self._row_to_initial(row, services)
        policies = load_policies()
        initial["name"] = self._unique_copy_name(
            policies.get(row.ref, {}).get("name", row.ref)
        )
        self._open_policy_dialog(
            "Clone Security Policy Rule", initial, self._handle_add_policy
        )

    def action_edit_policy(self) -> None:
        """Edit the selected policy in a pre-filled dialog."""
        row = self._selected_row()
        if not row or not self.current_zone:
            self.notify("No policy selected", severity="warning")
            return
        try:
            services = firewall.get_services()
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")
            return
        initial = self._row_to_initial(row, services)
        self._open_policy_dialog(
            "Edit Security Policy Rule",
            initial,
            lambda result: self._handle_edit_policy(result, row),
        )

    def _handle_edit_policy(
        self, result: dict | None, old_row: firewall.PolicyRow
    ) -> None:
        """Replace the old policy with the edited dialog result."""
        if not result:
            return
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        zone = self.current_zone
        was_disabled = is_policy_disabled(old_row.ref)
        new_ref = self._apply_policy_result(result)
        if new_ref is None:
            return
        try:
            if new_ref == old_row.ref:
                # Same backend object (e.g. rename only); the entry was
                # already updated by _apply_policy_result.
                pass
            else:
                if not was_disabled:
                    # Add succeeded; now remove the old firewalld object.
                    removers = {
                        "service": firewall.remove_service,
                        "port": firewall.remove_port,
                        "source": firewall.remove_source,
                        "rich": firewall.remove_rich_rule,
                    }
                    if not removers[old_row.kind](
                        old_row.ref, zone, self.permanent_mode
                    ):
                        self.notify(
                            f"New policy added but old {old_row.ref} could not be removed",
                            severity="warning",
                        )
                        self.load_zone_details(zone)
                        return
                if new_ref != old_row.ref:
                    delete_policy_entry(old_row.ref)
            logger.info(
                "edited policy {} -> {} in {}", old_row.ref, new_ref, zone
            )
            if was_disabled:
                # Preserve the disabled state: the new object is live,
                # so reload and disable it again.
                self.load_zone_details(zone)
                new_row = next(
                    (
                        r
                        for r in self._policy_rows
                        if r.ref == new_ref
                        and not is_policy_disabled(r.ref)
                    ),
                    None,
                )
                if new_row is not None:
                    self._disable_policy(new_row)
                    return
            self.notify(f"Updated policy {result['name'].strip()}")
            self.load_zone_details(zone)
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")

    def action_toggle_policy(self) -> None:
        """Disable (remove, keep dimmed) or re-enable the selected policy."""
        row = self._selected_row()
        if not row or not self.current_zone:
            self.notify("No policy selected", severity="warning")
            return
        if is_policy_disabled(row.ref):
            self._enable_policy(row)
        else:
            self._disable_policy(row)

    def _disable_policy(self, row: firewall.PolicyRow) -> None:
        """Remove the rule from firewalld but keep a dimmed row."""
        assert self.current_zone is not None
        zone = self.current_zone
        entry = load_policies().get(row.ref, {})
        removers = {
            "service": firewall.remove_service,
            "port": firewall.remove_port,
            "source": firewall.remove_source,
            "rich": firewall.remove_rich_rule,
        }
        try:
            if not removers[row.kind](row.ref, zone, self.permanent_mode):
                self.notify(f"Failed to disable {row.ref}", severity="error")
                return
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")
            return
        save_policy_entry(
            row.ref,
            entry.get("name", row.ref),
            entry.get("description", ""),
            disabled=True,
            kind=row.kind,
            detail=row.detail,
            action=row.action,
            source=row.source,
            destination=row.destination,
            protocol=row.protocol,
            service_port=row.service_port,
            zone=zone,
            permanent=self.permanent_mode,
        )
        logger.info("disabled policy {} in {}", row.ref, zone)
        self.notify(f"Disabled policy in {zone}")
        self.load_zone_details(zone)

    def _enable_policy(self, row: firewall.PolicyRow) -> None:
        """Re-add a disabled policy to firewalld from the stored detail."""
        assert self.current_zone is not None
        zone = self.current_zone
        entry = load_policies().get(row.ref, {})
        kind = entry.get("kind", row.kind)
        try:
            if kind == "service":
                ok = firewall.add_service(row.ref, zone, self.permanent_mode)
            elif kind == "port":
                ok = firewall.add_port(row.ref, zone, self.permanent_mode)
            elif kind == "source":
                ok = firewall.add_source(row.ref, zone, self.permanent_mode)
            else:
                ok = firewall.add_rich_rule(
                    entry.get("detail", row.detail), zone, self.permanent_mode
                )
            if not ok:
                self.notify(f"Failed to enable {row.ref}", severity="error")
                return
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")
            return
        save_policy_entry(
            row.ref,
            entry.get("name", row.ref),
            entry.get("description", ""),
            disabled=False,
        )
        logger.info("enabled policy {} in {}", row.ref, zone)
        self.notify(f"Enabled policy in {zone}")
        self.load_zone_details(zone)

    def action_add_interface(self) -> None:
        """Add an interface to the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        self.push_screen(
            InputModal("Add Interface", "Interface name (e.g., eth0)"),
            self._handle_add_interface,
        )

    def _handle_add_interface(self, interface: str | None) -> None:
        if interface and self.current_zone:
            try:
                if firewall.add_interface(interface, self.current_zone, self.permanent_mode):
                    logger.info("added interface {} to {}", interface, self.current_zone)
                    self.notify(f"Added interface {interface} to {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify(f"Failed to add interface {interface}", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

    def action_remove_interface(self) -> None:
        """Remove an interface from the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        try:
            interfaces = firewall.list_interfaces(self.current_zone, self.permanent_mode)
            if not interfaces:
                self.notify("No interfaces to remove", severity="warning")
                return
            self.push_screen(ZoneSelectScreen(interfaces, "Select interface to remove:"), self._handle_remove_interface)
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")

    def _handle_remove_interface(self, interface: str | None) -> None:
        if interface and self.current_zone:
            try:
                if firewall.remove_interface(interface, self.current_zone, self.permanent_mode):
                    logger.info("removed interface {} from {}", interface, self.current_zone)
                    self.notify(f"Removed interface {interface} from {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify(f"Failed to remove interface {interface}", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")


def main() -> None:
    """Entry point for the TUI."""
    logger.info("firewalld-tui starting")
    app = FirewalldTUI()
    app.run()


if __name__ == "__main__":
    main()
