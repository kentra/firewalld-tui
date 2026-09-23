"""PAN-OS Monitor filter syntax parsed into SQLAlchemy WHERE clauses.

Supported grammar (subset of the real PAN-OS filter bar)::

    (addr.src in 10.0.0.0/24) and (action eq allow)
    (zone.src eq public) or (port.dst leq 1024)
    !(addr in 1.1.1.1)

Fields: addr.src, addr.dst, addr (= either), zone.src, zone.dst,
port.src, port.dst, proto, app, service, action, rule, receive_time,
interface.src, interface.dst.
Operators: eq, neq, in, notin, leq, geq, lt, gt. ``!`` negates.
"""

from __future__ import annotations

from datetime import datetime

from lark import Lark, Transformer
from sqlalchemy import and_, func, not_, or_

from .db import TrafficLog

_GRAMMAR = r"""
    ?start: expr
    ?expr: or_expr
    ?or_expr: and_expr (OR and_expr)*
    ?and_expr: not_expr (AND not_expr)*
    ?not_expr: NOT? atom
    ?atom: "(" expr ")" | predicate
    predicate: FIELD OP VALUE
    AND: "and"
    OR: "or"
    NOT: "!"
    FIELD: /[a-zA-Z_][a-zA-Z0-9_.]*/
    OP: "eq" | "neq" | "in" | "notin" | "leq" | "geq" | "lt" | "gt"
    VALUE: /'[^']*'/ | /"[^"]*"/ | /[^()\s]+/
    %import common.WS_INLINE
    %ignore WS_INLINE
"""

_parser = Lark(_GRAMMAR, parser="lalr")


class FilterError(ValueError):
    """Raised when a PAN-OS filter string cannot be parsed or mapped."""


FIELD_MAP = {
    "addr.src": TrafficLog.src_ip,
    "addr.dst": TrafficLog.dst_ip,
    "zone.src": TrafficLog.src_zone,
    "zone.dst": TrafficLog.dst_zone,
    "port.src": TrafficLog.src_port,
    "port.dst": TrafficLog.dst_port,
    "proto": TrafficLog.proto,
    "app": TrafficLog.app,
    "service": TrafficLog.service,
    "action": TrafficLog.action,
    "rule": TrafficLog.rule,
    "receive_time": TrafficLog.receive_time,
    "interface.src": TrafficLog.inbound_if,
    "interface.dst": TrafficLog.outbound_if,
}


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _coerce(column, raw: str):
    """Convert a filter value to the column's Python type."""
    if column in (TrafficLog.src_port, TrafficLog.dst_port):
        try:
            return int(raw)
        except ValueError:
            raise FilterError(f"port must be a number, got {raw!r}")
    if column is TrafficLog.receive_time:
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            raise FilterError(f"cannot parse time {raw!r}")
    return raw


def _ip_clause(column, op: str, raw: str):
    """Build an IP predicate; CIDR-aware via the in_cidr SQLite function."""
    import ipaddress

    try:
        net = ipaddress.ip_network(raw, strict=False)
        expr = func.in_cidr(column, str(net)) == 1
    except ValueError:
        expr = column == raw
    return ~expr if op == "notin" else expr


class _WhereTransformer(Transformer):
    def predicate(self, items):
        field_tok, op_tok, value_tok = items
        field = str(field_tok).lower()
        op = str(op_tok).lower()
        raw = _unquote(str(value_tok))
        if field == "addr":
            clauses = [
                _single(TrafficLog.src_ip, op, raw),
                _single(TrafficLog.dst_ip, op, raw),
            ]
            return or_(*clauses) if op != "notin" else and_(*clauses)
        column = FIELD_MAP.get(field)
        if column is None:
            raise FilterError(f"unknown field {field!r}")
        return _single(column, op, raw)

    def and_expr(self, items):
        operands = [i for i in items if not _is_logic_token(i, ("and",))]
        return and_(*operands) if len(operands) > 1 else operands[0]

    def or_expr(self, items):
        operands = [i for i in items if not _is_logic_token(i, ("or",))]
        return or_(*operands) if len(operands) > 1 else operands[0]

    def not_expr(self, items):
        if len(items) == 2:
            return not_(items[1])
        return items[0]


def _is_logic_token(item, words: tuple[str, ...]) -> bool:
    return hasattr(item, "value") and str(item.value).lower() in words or (
        isinstance(item, str) and item.lower() in words
    )


def _single(column, op: str, raw: str):
    if column in (TrafficLog.src_ip, TrafficLog.dst_ip) and op in ("in", "notin"):
        return _ip_clause(column, op, raw)
    value = _coerce(column, raw)
    if op == "eq":
        return column == value
    if op == "neq":
        return column != value
    if op == "leq":
        return column <= value
    if op == "geq":
        return column >= value
    if op == "lt":
        return column < value
    if op == "gt":
        return column > value
    if op == "in":
        return column == value
    if op == "notin":
        return column != value
    raise FilterError(f"unknown operator {op!r}")


def parse_filter(text: str) -> list:
    """Parse a PAN-OS filter string into SQLAlchemy WHERE clauses.

    Returns [] for an empty filter (match everything).
    Raises FilterError on syntax or mapping errors.
    """
    text = text.strip()
    if not text:
        return []
    try:
        tree = _parser.parse(text)
    except Exception as e:
        raise FilterError(f"cannot parse filter: {e}")
    try:
        result = _WhereTransformer().transform(tree)
    except FilterError:
        raise
    except Exception as e:
        raise FilterError(f"cannot build query: {e}")
    return [result]
