"""Subprocess wrapper for firewall-cmd commands."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field


@dataclass
class ZoneInfo:
    """Parsed information about a firewall zone."""

    name: str
    target: str = ""
    services: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    forward_ports: list[str] = field(default_factory=list)
    icmp_blocks: list[str] = field(default_factory=list)
    rich_rules: list[str] = field(default_factory=list)
    source_ports: list[str] = field(default_factory=list)


def _run(args: list[str], check: bool = True) -> str:
    """Run a firewall-cmd command and return stdout."""
    cmd = ["firewall-cmd"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"firewall-cmd failed: {cmd}")
    return result.stdout.strip()


def _run_quiet(args: list[str]) -> bool:
    """Run a firewall-cmd command and return True on success."""
    cmd = ["firewall-cmd"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def is_active() -> bool:
    """Check if firewalld is running."""
    return _run_quiet(["--state"])


def get_version() -> str:
    """Get firewalld version."""
    return _run(["--version"])


def get_default_zone() -> str:
    """Get the default zone name."""
    return _run(["--get-default-zone"])


def get_zones() -> list[str]:
    """Get list of all available zones."""
    output = _run(["--get-zones"])
    return output.split()


def get_services() -> list[str]:
    """Get list of all predefined services."""
    output = _run(["--get-services"])
    return output.split()


def get_active_zones() -> dict[str, list[str]]:
    """Get active zones with their interfaces and sources.

    Returns:
        Dict mapping zone name to list of interfaces/sources.
    """
    output = _run(["--get-active-zones"])
    result: dict[str, list[str]] = {}
    current_zone = None
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line and current_zone is None:
            current_zone = line
            result[current_zone] = []
        elif current_zone is not None:
            result[current_zone].append(line)
    return result


def list_zone(zone: str | None = None, permanent: bool = False) -> ZoneInfo:
    """List all configuration for a zone."""
    args = ["--zone"] if zone else []
    if zone:
        args.append(zone)
    args.append("--list-all")

    if permanent:
        args.append("--permanent")

    output = _run(args)

    info = ZoneInfo(name=zone or get_default_zone())
    current_key = None

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("interfaces:"):
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else ""
            info.interfaces = [s.strip() for s in val.split() if s.strip()]
        elif line.startswith("sources:"):
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else ""
            info.sources = [s.strip() for s in val.split() if s.strip()]
        elif line.startswith("services:"):
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else ""
            info.services = [s.strip() for s in val.split() if s.strip()]
        elif line.startswith("ports:"):
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else ""
            info.ports = [s.strip() for s in val.split() if s.strip()]
        elif line.startswith("protocols:"):
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else ""
            info.protocols = [s.strip() for s in val.split() if s.strip()]
        elif line.startswith("source-ports:"):
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else ""
            info.source_ports = [s.strip() for s in val.split() if s.strip()]
        elif line.startswith("forward-ports:"):
            current_key = "forward-ports"
        elif line.startswith("icmp-blocks:"):
            parts = line.split(":", 1)
            val = parts[1].strip() if len(parts) > 1 else ""
            info.icmp_blocks = [s.strip() for s in val.split() if s.strip()]
            current_key = None
        elif line.startswith("rich rules:"):
            current_key = "rich_rules"
        elif current_key == "forward-ports":
            if line and not line.startswith(("services:", "ports:")):
                info.forward_ports.append(line)
        elif current_key == "rich_rules":
            if line and not line.startswith(("icmp-blocks:", "rich rules:")):
                info.rich_rules.append(line)
        elif "target" in line.lower() and "=" in line:
            parts = line.split("=", 1)
            if len(parts) > 1:
                info.target = parts[1].strip()

    return info


def list_services(zone: str | None = None, permanent: bool = False) -> list[str]:
    """List services for a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args.append("--list-services")
    output = _run(args)
    return [s.strip() for s in output.split() if s.strip()]


def add_service(service: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Add a service to a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--add-service", service]
    return _run_quiet(args)


def remove_service(service: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Remove a service from a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--remove-service", service]
    return _run_quiet(args)


def list_ports(zone: str | None = None, permanent: bool = False) -> list[str]:
    """List ports for a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args.append("--list-ports")
    output = _run(args)
    return [p.strip() for p in output.split() if p.strip()]


def add_port(port: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Add a port to a zone. Port format: port/proto (e.g., 8080/tcp)."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--add-port", port]
    return _run_quiet(args)


def remove_port(port: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Remove a port from a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--remove-port", port]
    return _run_quiet(args)


def list_interfaces(zone: str | None = None, permanent: bool = False) -> list[str]:
    """List interfaces bound to a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args.append("--list-interfaces")
    output = _run(args)
    return [i.strip() for i in output.split() if i.strip()]


def add_interface(interface: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Bind an interface to a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--add-interface", interface]
    return _run_quiet(args)


def remove_interface(interface: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Unbind an interface from a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--remove-interface", interface]
    return _run_quiet(args)


def list_sources(zone: str | None = None, permanent: bool = False) -> list[str]:
    """List sources bound to a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args.append("--list-sources")
    output = _run(args)
    return [s.strip() for s in output.split() if s.strip()]


def add_source(source: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Bind a source to a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--add-source", source]
    return _run_quiet(args)


def remove_source(source: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Unbind a source from a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--remove-source", source]
    return _run_quiet(args)


def list_rich_rules(zone: str | None = None, permanent: bool = False) -> list[str]:
    """List rich rules for a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args.append("--list-rich-rules")
    output = _run(args)
    return [r.strip() for r in output.splitlines() if r.strip()]


def add_rich_rule(rule: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Add a rich rule to a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--add-rich-rule", rule]
    return _run_quiet(args)


def remove_rich_rule(rule: str, zone: str | None = None, permanent: bool = False) -> bool:
    """Remove a rich rule from a zone."""
    args = []
    if permanent:
        args.append("--permanent")
    if zone:
        args += ["--zone", zone]
    args += ["--remove-rich-rule", rule]
    return _run_quiet(args)


def set_default_zone(zone: str) -> bool:
    """Set the default zone."""
    return _run_quiet(["--set-default-zone", zone])


def get_zone_of_interface(interface: str) -> str:
    """Get the zone an interface is bound to."""
    return _run(["--get-zone-of-interface", interface])


def reload() -> bool:
    """Reload firewalld."""
    return _run_quiet(["--reload"])


def runtime_to_permanent() -> bool:
    """Save runtime config to permanent config."""
    return _run_quiet(["--runtime-to-permanent"])
