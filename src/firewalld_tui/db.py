"""SQLite storage for dashboard metrics and monitor traffic logs.

Database lives next to the other TUI state: ``~/.firewalld-tui/traffic.db``.
WAL mode + short transactions so the background sampler thread and the UI
thread never block each other. Rows older than 7 days are pruned regularly.
"""

from __future__ import annotations

import ipaddress
import shutil
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from loguru import logger
from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    desc,
    event,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import CONFIG_DIR

DB_FILE = CONFIG_DIR / "traffic.db"
RETENTION_DAYS = 7


class Base(DeclarativeBase):
    pass


class TrafficLog(Base):
    """One row per kernel nftables log event (PAN-OS Monitor > Traffic)."""

    __tablename__ = "traffic_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receive_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    type: Mapped[str] = mapped_column(String(16), default="TRAFFIC")
    subtype: Mapped[str] = mapped_column(String(16), default="drop", index=True)
    src_ip: Mapped[str] = mapped_column(String(45), default="any", index=True)
    dst_ip: Mapped[str] = mapped_column(String(45), default="any", index=True)
    src_port: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    dst_port: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    proto: Mapped[str] = mapped_column(String(16), default="any", index=True)
    src_zone: Mapped[str] = mapped_column(String(64), default="any", index=True)
    dst_zone: Mapped[str] = mapped_column(String(64), default="any", index=True)
    inbound_if: Mapped[str] = mapped_column(String(32), default="")
    outbound_if: Mapped[str] = mapped_column(String(32), default="")
    action: Mapped[str] = mapped_column(String(32), default="drop", index=True)
    rule: Mapped[str] = mapped_column(String(128), default="", index=True)
    app: Mapped[str] = mapped_column(String(64), default="any", index=True)
    service: Mapped[str] = mapped_column(String(64), default="")
    src_user: Mapped[str] = mapped_column(String(128), default="")
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    packets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_end_reason: Mapped[str] = mapped_column(String(32), default="")

    __table_args__ = (
        Index("ix_traffic_time_src", "receive_time", "src_ip"),
        Index("ix_traffic_rule_action", "rule", "action"),
    )


class ZoneTraffic(Base):
    """Interface byte counters sampled periodically (dashboard fallback)."""

    __tablename__ = "zone_traffic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zone: Mapped[str] = mapped_column(String(64), index=True)
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    conntrack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)


class SystemSnapshot(Base):
    """System resource sample for the dashboard header."""

    __tablename__ = "system_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cpu_load1: Mapped[float] = mapped_column(default=0.0)
    mem_used_pct: Mapped[float] = mapped_column(default=0.0)
    disk_used_pct: Mapped[float] = mapped_column(default=0.0)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)


def _sql_in_cidr(ip: str | None, cidr: str | None) -> int:
    """SQLite scalar function: 1 when ip is inside cidr, else 0."""
    try:
        if not ip or not cidr:
            return 0
        return 1 if ipaddress.ip_address(ip) in ipaddress.ip_network(
            cidr, strict=False
        ) else 0
    except ValueError:
        return 0


_engine: Engine | None = None
_Session: sessionmaker | None = None


def _on_connect(dbapi_conn, _record) -> None:
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    dbapi_conn.create_function("in_cidr", 2, _sql_in_cidr)


def get_engine(db_file: Path = DB_FILE):
    """Return the process-wide engine, creating it on first use."""
    global _engine, _Session
    if _engine is None:
        from sqlalchemy import create_engine

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
        )
        event.listen(_engine, "connect", _on_connect)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope(db_file: Path = DB_FILE) -> Iterator[Session]:
    """Provide a transactional session (commit on success, rollback on error)."""
    global _Session
    get_engine(db_file)
    assert _Session is not None
    session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(db_file: Path = DB_FILE) -> None:
    """Create tables and prune rows older than the retention window."""
    get_engine(db_file)
    assert _engine is not None
    Base.metadata.create_all(_engine)
    prune_old_rows(db_file)


def prune_old_rows(db_file: Path = DB_FILE) -> int:
    """Delete rows older than RETENTION_DAYS; return total removed."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=RETENTION_DAYS
    )
    removed = 0
    with session_scope(db_file) as s:
        for model in (TrafficLog, ZoneTraffic, SystemSnapshot):
            removed += (
                s.query(model).filter(model.receive_time < cutoff).delete()
                if model is TrafficLog
                else s.query(model).filter(model.ts < cutoff).delete()
            )
    if removed:
        logger.info("pruned {} rows older than {} days", removed, RETENTION_DAYS)
    return removed


def add_traffic_log(db_file: Path = DB_FILE, **fields) -> int:
    """Insert one TrafficLog row; return its id."""
    with session_scope(db_file) as s:
        row = TrafficLog(**fields)
        s.add(row)
        s.flush()
        return row.id


def query_logs(clauses: list, limit: int, db_file: Path = DB_FILE) -> list[TrafficLog]:
    """Return the newest matching TrafficLog rows (bounded by limit)."""
    with session_scope(db_file) as s:
        stmt = select(TrafficLog)
        if clauses:
            stmt = stmt.where(*clauses)
        stmt = stmt.order_by(desc(TrafficLog.receive_time)).limit(max(limit, 1))
        return list(s.scalars(stmt).all())


def count_logs(clauses: list | None = None, db_file: Path = DB_FILE) -> int:
    """Count matching TrafficLog rows."""
    with session_scope(db_file) as s:
        stmt = select(func.count()).select_from(TrafficLog)
        if clauses:
            stmt = stmt.where(*clauses)
        return int(s.scalar(stmt) or 0)


def top_by_column(
    column, since_days: int = 7, limit: int = 5, db_file: Path = DB_FILE
) -> list[tuple[str, int]]:
    """Top values of a TrafficLog column by event count (dashboard widgets)."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=since_days
    )
    with session_scope(db_file) as s:
        rows = (
            s.query(column, func.count().label("hits"))
            .filter(TrafficLog.receive_time >= cutoff)
            .group_by(column)
            .order_by(desc("hits"))
            .limit(limit)
            .all()
        )
        return [(str(value or "any"), int(hits)) for value, hits in rows]


def sample_system() -> dict:
    """Read CPU load, memory and disk usage from /proc (no extra deps)."""
    load1 = 0.0
    try:
        load1 = float(Path("/proc/loadavg").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    mem_pct = 0.0
    try:
        meminfo: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            meminfo[key.strip()] = int(rest.strip().split()[0])
        total = meminfo.get("MemTotal", 0)
        avail = meminfo.get("MemAvailable", 0)
        if total:
            mem_pct = round(100.0 * (total - avail) / total, 1)
    except (OSError, ValueError):
        pass
    disk_pct = 0.0
    try:
        usage = shutil.disk_usage("/")
        disk_pct = round(100.0 * usage.used / usage.total, 1)
    except OSError:
        pass
    return {"cpu_load1": load1, "mem_used_pct": mem_pct, "disk_used_pct": disk_pct}


def sample_netdev() -> dict[str, dict[str, int]]:
    """Read per-interface rx/tx bytes from /proc/net/dev."""
    result: dict[str, dict[str, int]] = {}
    try:
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
    except OSError:
        return result
    for line in lines:
        if ":" not in line:
            continue
        iface, _, rest = line.partition(":")
        parts = rest.split()
        if len(parts) < 16:
            continue
        try:
            result[iface.strip()] = {
                "rx_bytes": int(parts[0]),
                "tx_bytes": int(parts[8]),
            }
        except ValueError:
            continue
    return result


def sample_conntrack() -> int | None:
    """Return the current conntrack count, or None when unavailable."""
    try:
        return int(
            Path("/proc/sys/net/netfilter/nf_conntrack_count").read_text().strip()
        )
    except (OSError, ValueError):
        return None
