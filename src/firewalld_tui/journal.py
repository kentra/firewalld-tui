"""Tail kernel nftables logs into the TrafficLog table.

Source priority: ``journalctl -k -o json -f`` → ``/var/log/messages`` /
``/var/log/kern.log`` tail → give up gracefully (Monitor stays empty until
traffic arrives). Runs in a daemon thread owned by the app; never raises.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from . import db as dbmod

FIELD_RES = {
    "SRC": re.compile(r"\bSRC=([0-9a-fA-F:.]+)"),
    "DST": re.compile(r"\bDST=([0-9a-fA-F:.]+)"),
    "SPT": re.compile(r"\bSPT=(\d+)"),
    "DPT": re.compile(r"\bDPT=(\d+)"),
    "PROTO": re.compile(r"\bPROTO=([A-Za-z]+)"),
    "IN": re.compile(r"\bIN=([^\s]*)"),
    "OUT": re.compile(r"\bOUT=([^\s]*)"),
    "PREFIX": re.compile(r'PREFIX="([^"]*)"'),
    "LEN": re.compile(r"\bLEN=(\d+)"),
}

LOG_FILES = ("/var/log/messages", "/var/log/kern.log", "/var/log/nftables.log")


def parse_kernel_line(line: str, iface_zones: dict[str, str] | None = None) -> dict | None:
    """Parse one kernel log line into TrafficLog fields (None if not a packet log)."""
    if "SRC=" not in line or "DST=" not in line:
        return None

    def grab(key: str, default: str = "") -> str:
        m = FIELD_RES[key].search(line)
        return m.group(1) if m else default

    def grab_int(key: str) -> int | None:
        m = FIELD_RES[key].search(line)
        return int(m.group(1)) if m else None

    prefix = grab("PREFIX").strip().rstrip(":").strip()
    in_if = grab("IN")
    out_if = grab("OUT")
    zones = iface_zones or {}
    upper = line.upper()
    action = "reject" if "REJECT" in upper else "drop"
    return {
        "receive_time": datetime.now(timezone.utc).replace(tzinfo=None),
        "type": "TRAFFIC",
        "subtype": action,
        "src_ip": grab("SRC", "any"),
        "dst_ip": grab("DST", "any"),
        "src_port": grab_int("SPT"),
        "dst_port": grab_int("DPT"),
        "proto": grab("PROTO", "any").lower(),
        "src_zone": zones.get(in_if, "any") if in_if else "any",
        "dst_zone": zones.get(out_if, "any") if out_if else "any",
        "inbound_if": in_if,
        "outbound_if": out_if,
        "action": action,
        "rule": prefix or "log-denied",
        "app": "any",
    }


def _iface_zone_map() -> dict[str, str]:
    """Map interface -> zone via active zones (best effort, cached per batch)."""
    try:
        from . import firewall

        mapping: dict[str, str] = {}
        for zone, bindings in firewall.get_active_zones().items():
            for entry in bindings:
                # entries look like "interfaces: eth0" or "sources: ..."
                if ":" in entry:
                    kind, _, value = entry.partition(":")
                    if kind.strip() == "interfaces":
                        for iface in value.split():
                            mapping[iface.strip()] = zone
                elif entry and not entry.startswith(("interfaces", "sources")):
                    mapping[entry.strip()] = zone
        return mapping
    except Exception as e:
        logger.debug("iface zone map failed: {}", e)
        return {}


def _journal_lines(stop: threading.Event):
    """Yield kernel MESSAGE strings from journalctl -f (None if unavailable)."""
    if shutil.which("journalctl") is None:
        return
    proc = None
    try:
        proc = subprocess.Popen(
            ["journalctl", "-k", "-o", "json", "-f", "-n", "100"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert proc.stdout is not None
        while not stop.is_set():
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.2)
                continue
            try:
                yield json.loads(line).get("MESSAGE", "")
            except (ValueError, AttributeError):
                continue
    except OSError as e:
        logger.debug("journalctl unavailable: {}", e)
        return
    finally:
        if proc is not None:
            proc.terminate()


def _file_lines(stop: threading.Event, path: str):
    """Yield new lines appended to a kernel log file."""
    logger.info("tailing kernel logs from {}", path)
    try:
        with open(path, errors="replace") as f:
            f.seek(0, 2)
            while not stop.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                yield line
    except OSError as e:
        logger.debug("log file tail failed: {}", e)
        return


def tail_logs(stop: threading.Event, batch_size: int = 50) -> None:
    """Consume kernel logs into TrafficLog until stop is set. Never raises."""
    try:
        dbmod.init_db()
        # NOTE: generators are lazy, so pick the source eagerly here;
        # otherwise the file fallback would never trigger.
        log_file = next((p for p in LOG_FILES if Path(p).is_file()), None)
        if shutil.which("journalctl") is not None:
            lines = _journal_lines(stop)
        elif log_file is not None:
            lines = _file_lines(stop, log_file)
        else:
            logger.warning("no kernel log source; Monitor will stay empty")
            return
        batch: list[dict] = []
        zone_map: dict[str, str] = {}
        zone_map_ts = 0.0

        def flush() -> None:
            if not batch:
                return
            try:
                with dbmod.session_scope() as s:
                    s.add_all([dbmod.TrafficLog(**row) for row in batch])
                logger.debug("stored {} traffic rows", len(batch))
            except Exception as e:
                logger.warning("traffic batch insert failed: {}", e)
            finally:
                batch.clear()

        for line in lines:
            if stop.is_set():
                break
            if time.monotonic() - zone_map_ts > 60:
                zone_map = _iface_zone_map()
                zone_map_ts = time.monotonic()
            parsed = parse_kernel_line(line, zone_map)
            if parsed is None:
                continue
            batch.append(parsed)
            if len(batch) >= batch_size:
                flush()
        flush()
    except Exception as e:
        logger.warning("log tail loop ended: {}", e)


def ensure_log_denied() -> None:
    """Make sure firewalld logs denied packets (best effort)."""
    try:
        from . import firewall

        current = firewall._run(["--get-log-denied"])
        if current.strip().lower() in ("off", "no", ""):
            if firewall._run_quiet(["--set-log-denied", "all"]):
                logger.info("enabled LogDenied=all for traffic monitoring")
            else:
                logger.warning("could not enable LogDenied; Monitor may stay empty")
        else:
            logger.debug("LogDenied already {}", current.strip())
    except Exception as e:
        logger.debug("LogDenied check failed: {}", e)
