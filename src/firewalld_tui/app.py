"""Firewalld TUI - A terminal interface for managing firewalld."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult, InvalidThemeError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)
from loguru import logger

from . import firewall
from .config import CONFIG_FILE, load_theme, save_theme

BINDINGS = [
    Binding("q", "quit", "Quit"),
    Binding("r", "refresh", "Refresh"),
    Binding("d", "set_default", "Set Default Zone"),
    Binding("a", "add_service", "Add Service"),
    Binding("x", "remove_service", "Remove Service"),
    Binding("p", "add_port", "Add Port"),
    Binding("P", "remove_port", "Remove Port"),
    Binding("i", "add_interface", "Add Interface"),
    Binding("I", "remove_interface", "Remove Interface"),
    Binding("s", "add_source", "Add Source"),
    Binding("S", "remove_source", "Remove Source"),
    Binding("R", "add_rich_rule", "Add Rich Rule"),
    Binding("delete", "remove_selected_row", "Remove Rule"),
    Binding("t", "toggle_mode", "Toggle Runtime/Permanent"),
    Binding("f1", "change_theme", "Change Theme"),
]


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


class ServiceSelectScreen(ModalScreen[str | None]):
    """Modal to select a service from predefined list."""

    CSS = """
    ServiceSelectScreen {
        align: center middle;
    }

    #service-container {
        width: 60;
        height: 40;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }

    #service-list {
        height: 1fr;
        margin: 1 0;
    }
    """

    def __init__(self, services: list[str]) -> None:
        super().__init__()
        self.services = sorted(services)

    def compose(self) -> ComposeResult:
        with Vertical(id="service-container"):
            yield Static("Select a service:")
            with ListView(id="service-list"):
                for svc in self.services:
                    yield ListItem(Label(svc), name=svc)
            yield Button("Cancel", id="cancel", variant="error")

    @on(ListView.Selected)
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ListItem) and event.item.name:
            self.dismiss(event.item.name)

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)


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


class FirewalldTUI(App):
    """Firewalld TUI application."""

    TITLE = "Firewalld TUI"
    SUB_TITLE = "Manage your firewall zones"

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

    #toolbar {
        height: auto;
        margin-bottom: 1;
    }

    #toolbar Button {
        margin-right: 1;
    }

    #toolbar Button:last-child {
        margin-right: 0;
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
    }

    #action-bar Static {
        margin: 0 1;
    }
    """

    BINDINGS = BINDINGS

    current_zone: reactive[str | None] = reactive(None)
    permanent_mode: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self.zones: list[str] = []
        self._rule_rows: list[firewall.RuleRow] = []
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
                with Horizontal(id="toolbar"):
                    yield Button("Add Service", id="tb-add-service", variant="primary")
                    yield Button("Add Port", id="tb-add-port", variant="primary")
                    yield Button("Add Source", id="tb-add-source", variant="primary")
                    yield Button("Add Rich Rule", id="tb-add-rich", variant="primary")
                yield DataTable(
                    id="rule-table", cursor_type="row", zebra_stripes=True
                )
                with VerticalScroll(id="zone-details"):
                    pass
        with Horizontal(id="action-bar"):
            yield Static("q:Quit r:Refresh d:Default a:Addsvc x:Rmsvc p:Addport P:Rmport i:Addiface I:Rmiface s:Addsrc S:Rmsrc R:Richrule del:Rmrule t:Toggle f1:Theme")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#rule-table", DataTable)
        for label in ("Source", "Destination", "Protocol", "Service/Port", "Action"):
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

    def load_zone_details(self, zone: str) -> None:
        """Load zone info and rebuild the rules table."""
        try:
            info = firewall.list_zone(zone, self.permanent_mode)
            self._zone_info = info
            rows = firewall.rule_rows_from_info(info)
            self._rule_rows = rows

            self.query_one("#zone-header").update(f"Zone: {info.name}")

            table = self.query_one("#rule-table", DataTable)
            cursor_row = table.cursor_row
            table.clear()
            for row in rows:
                table.add_row(
                    row.source,
                    row.destination,
                    row.protocol,
                    row.service_port,
                    row.action,
                )
            if rows:
                table.move_cursor(
                    row=min(max(cursor_row, 0), len(rows) - 1),
                    column=0,
                    animate=False,
                )

            selected: firewall.RuleRow | None = None
            idx = table.cursor_row
            if rows and 0 <= idx < len(rows):
                selected = rows[idx]
            self._render_details_panel(selected)

        except RuntimeError as e:
            logger.error("Error loading zone details: {}", e)
            self.notify(f"Error loading zone details: {e}", severity="error")

    def _render_details_panel(
        self, selected: firewall.RuleRow | None
    ) -> None:
        """Render the lower panel: selected row detail + zone meta."""
        panel = self.query_one("#zone-details")
        panel.remove_children()
        info = self._zone_info
        if info is None:
            return

        if selected is not None:
            panel.mount(
                Static(f"Selected ({selected.kind}):", classes="detail-label")
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
        """Show the highlighted rule's detail in the lower panel."""
        if event.data_table.id != "rule-table":
            return
        idx = event.cursor_row
        selected = (
            self._rule_rows[idx] if 0 <= idx < len(self._rule_rows) else None
        )
        self._render_details_panel(selected)

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route toolbar button presses to their actions."""
        action = {
            "tb-add-service": self.action_add_service,
            "tb-add-port": self.action_add_port,
            "tb-add-source": self.action_add_source,
            "tb-add-rich": self.action_add_rich_rule,
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

    def action_add_service(self) -> None:
        """Add a service to the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        try:
            services = firewall.get_services()
            self.push_screen(ServiceSelectScreen(services), self._handle_add_service)
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")

    def _handle_add_service(self, service: str | None) -> None:
        if service and self.current_zone:
            try:
                if firewall.add_service(service, self.current_zone, self.permanent_mode):
                    logger.info("added service {} to {}", service, self.current_zone)
                    self.notify(f"Added {service} to {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify(f"Failed to add {service}", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

    def action_remove_service(self) -> None:
        """Remove a service from the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        try:
            services = firewall.list_services(self.current_zone, self.permanent_mode)
            if not services:
                self.notify("No services to remove", severity="warning")
                return
            self.push_screen(ServiceSelectScreen(services), self._handle_remove_service)
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")

    def _handle_remove_service(self, service: str | None) -> None:
        if service and self.current_zone:
            try:
                if firewall.remove_service(service, self.current_zone, self.permanent_mode):
                    logger.info("removed service {} from {}", service, self.current_zone)
                    self.notify(f"Removed {service} from {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify(f"Failed to remove {service}", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

    def action_add_port(self) -> None:
        """Add a port to the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        self.push_screen(
            InputModal("Add Port", "Format: port/proto (e.g., 8080/tcp)"),
            self._handle_add_port,
        )

    def _handle_add_port(self, port: str | None) -> None:
        if port and self.current_zone:
            try:
                if firewall.add_port(port, self.current_zone, self.permanent_mode):
                    logger.info("added port {} to {}", port, self.current_zone)
                    self.notify(f"Added port {port} to {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify(f"Failed to add port {port}", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

    def action_remove_port(self) -> None:
        """Remove a port from the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        try:
            ports = firewall.list_ports(self.current_zone, self.permanent_mode)
            if not ports:
                self.notify("No ports to remove", severity="warning")
                return
            self.push_screen(InputModal("Remove Port", "Port to remove (e.g., 8080/tcp)"), self._handle_remove_port)
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")

    def _handle_remove_port(self, port: str | None) -> None:
        if port and self.current_zone:
            try:
                if firewall.remove_port(port, self.current_zone, self.permanent_mode):
                    logger.info("removed port {} from {}", port, self.current_zone)
                    self.notify(f"Removed port {port} from {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify(f"Failed to remove port {port}", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

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

    def action_add_source(self) -> None:
        """Add a source to the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        self.push_screen(
            InputModal("Add Source", "Source (e.g., 192.168.1.0/24)"),
            self._handle_add_source,
        )

    def _handle_add_source(self, source: str | None) -> None:
        if source and self.current_zone:
            try:
                if firewall.add_source(source, self.current_zone, self.permanent_mode):
                    logger.info("added source {} to {}", source, self.current_zone)
                    self.notify(f"Added source {source} to {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify(f"Failed to add source {source}", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

    def action_remove_source(self) -> None:
        """Remove a source from the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        try:
            sources = firewall.list_sources(self.current_zone, self.permanent_mode)
            if not sources:
                self.notify("No sources to remove", severity="warning")
                return
            self.push_screen(ZoneSelectScreen(sources, "Select source to remove:"), self._handle_remove_source)
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")

    def _handle_remove_source(self, source: str | None) -> None:
        if source and self.current_zone:
            try:
                if firewall.remove_source(source, self.current_zone, self.permanent_mode):
                    logger.info("removed source {} from {}", source, self.current_zone)
                    self.notify(f"Removed source {source} from {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify(f"Failed to remove source {source}", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

    def action_add_rich_rule(self) -> None:
        """Add a rich rule to the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        self.push_screen(
            InputModal(
                "Add Rich Rule",
                "Rich rule (e.g., rule family='ipv4' source address='10.0.0.1' accept)",
            ),
            self._handle_add_rich_rule,
        )

    def _handle_add_rich_rule(self, rule: str | None) -> None:
        if rule and self.current_zone:
            try:
                if firewall.add_rich_rule(rule, self.current_zone, self.permanent_mode):
                    logger.info("added rich rule to {}", self.current_zone)
                    self.notify(f"Added rich rule to {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify("Failed to add rich rule", severity="error")
            except RuntimeError as e:
                logger.error("{}", e)
                self.notify(str(e), severity="error")

    def action_remove_selected_row(self) -> None:
        """Remove the firewall object behind the selected table row."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        table = self.query_one("#rule-table", DataTable)
        idx = table.cursor_row
        if not (0 <= idx < len(self._rule_rows)):
            self.notify("No rule selected", severity="warning")
            return
        row = self._rule_rows[idx]
        removers = {
            "service": firewall.remove_service,
            "port": firewall.remove_port,
            "source": firewall.remove_source,
            "rich": firewall.remove_rich_rule,
        }
        remover = removers[row.kind]
        try:
            if remover(row.ref, self.current_zone, self.permanent_mode):
                logger.info(
                    "removed {} {} from {}", row.kind, row.ref, self.current_zone
                )
                self.notify(f"Removed {row.ref} from {self.current_zone}")
                self.load_zone_details(self.current_zone)
            else:
                self.notify(f"Failed to remove {row.ref}", severity="error")
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
