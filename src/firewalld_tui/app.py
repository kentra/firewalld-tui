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
    Binding("delete", "remove_rich_rule", "Remove Rich Rule"),
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
        height: 1fr;
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
            with VerticalScroll(id="main-content"):
                yield Static("Select a zone", id="zone-header")
                yield Static("Mode: Runtime", id="mode-indicator")
                with VerticalScroll(id="zone-details"):
                    pass
        with Horizontal(id="action-bar"):
            yield Static("q:Quit r:Refresh d:Default a:Addsvc x:Rmsvc p:Rmport P:Rmport i:Rmiface I:Rmiface s:Rmsrc S:Rmsrc R:Richrule del:Rmrichrule t:Toggle f1:Theme")
        yield Footer()

    def on_mount(self) -> None:
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
        """Load and display zone details."""
        try:
            info = firewall.list_zone(zone, self.permanent_mode)
            details = self.query_one("#zone-details")
            details.remove_children()

            self.query_one("#zone-header").update(f"Zone: {info.name}")

            target = info.target if info.target else "(default)"
            details.mount(
                Static(f"{target}", classes="detail-row")
            )

            if info.services:
                details.mount(
                    Static("Services:", classes="detail-label")
                )
                for svc in info.services:
                    details.mount(Static(f"  {svc}", classes="detail-row"))

            if info.ports:
                details.mount(
                    Static("Ports:", classes="detail-label")
                )
                for port in info.ports:
                    details.mount(Static(f"  {port}", classes="detail-row"))

            if info.protocols:
                details.mount(
                    Static("Protocols:", classes="detail-label")
                )
                for proto in info.protocols:
                    details.mount(Static(f"  {proto}", classes="detail-row"))

            if info.interfaces:
                details.mount(
                    Static("Interfaces:", classes="detail-label")
                )
                for iface in info.interfaces:
                    details.mount(Static(f"  {iface}", classes="detail-row"))

            if info.sources:
                details.mount(
                    Static("Sources:", classes="detail-label")
                )
                for src in info.sources:
                    details.mount(Static(f"  {src}", classes="detail-row"))

            if info.source_ports:
                details.mount(
                    Static("Source Ports:", classes="detail-label")
                )
                for sp in info.source_ports:
                    details.mount(Static(f"  {sp}", classes="detail-row"))

            if info.forward_ports:
                details.mount(
                    Static("Forward Ports:", classes="detail-label")
                )
                for fp in info.forward_ports:
                    details.mount(Static(f"  {fp}", classes="detail-row"))

            if info.icmp_blocks:
                details.mount(
                    Static("ICMP Blocks:", classes="detail-label")
                )
                for icmp in info.icmp_blocks:
                    details.mount(Static(f"  {icmp}", classes="detail-row"))

            if info.rich_rules:
                details.mount(
                    Static("Rich Rules:", classes="detail-label")
                )
                for rule in info.rich_rules:
                    details.mount(Static(f"  {rule}", classes="detail-row"))

        except RuntimeError as e:
            logger.error("Error loading zone details: {}", e)
            self.notify(f"Error loading zone details: {e}", severity="error")

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

    def action_remove_rich_rule(self) -> None:
        """Remove a rich rule from the current zone."""
        if not self.current_zone:
            self.notify("No zone selected", severity="warning")
            return
        try:
            rules = firewall.list_rich_rules(self.current_zone, self.permanent_mode)
            if not rules:
                self.notify("No rich rules to remove", severity="warning")
                return
            # Use a list screen for rules
            self.push_screen(
                ZoneSelectScreen(rules, "Select rich rule to remove:"),
                self._handle_remove_rich_rule,
            )
        except RuntimeError as e:
            logger.error("{}", e)
            self.notify(str(e), severity="error")

    def _handle_remove_rich_rule(self, rule: str | None) -> None:
        if rule and self.current_zone:
            try:
                if firewall.remove_rich_rule(rule, self.current_zone, self.permanent_mode):
                    logger.info("removed rich rule from {}", self.current_zone)
                    self.notify(f"Removed rich rule from {self.current_zone}")
                    self.load_zone_details(self.current_zone)
                else:
                    self.notify("Failed to remove rich rule", severity="error")
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
