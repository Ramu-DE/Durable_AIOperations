"""
Executor — at-most-once tool execution via the tool_calls idempotency table.

Lifecycle per call:
  reserve  → INSERT pending row (ON CONFLICT DO NOTHING)
  claim    → UPDATE pending → running
  execute  → call the actual tool function
  complete → UPDATE running → succeeded (with result)
  on error → UPDATE → failed

If reserve() returns False (key already exists):
  - status=succeeded → return cached result (idempotency hit)
  - status=running   → another process is executing; caller may retry
  - status=failed    → prior attempt errored; caller may retry with same or new key
"""
from __future__ import annotations

import uuid

import psycopg

from src.db import tool_call_store, conversation_store


# Registry: maps tool_name → callable that takes (conn, args_dict) → dict
_TOOL_REGISTRY: dict[str, callable] = {}


def register(name: str):
    """Decorator to register a function as a named tool."""
    def decorator(fn):
        _TOOL_REGISTRY[name] = fn
        return fn
    return decorator


def execute(
    conn: psycopg.Connection,
    conversation_id: str,
    seq: int,
    tool_name: str,
    args: dict,
) -> dict:
    """
    Execute a tool with at-most-once semantics.

    Returns the tool result (from cache on idempotency hit, from execution on first call).
    Raises RuntimeError if the tool is unknown or is still running in another process.
    """
    if tool_name not in _TOOL_REGISTRY:
        raise RuntimeError(f"Unknown tool: {tool_name!r}")

    idem_key = tool_call_store.make_key(conversation_id, seq, tool_name, args)

    # ── Reserve ───────────────────────────────────────────────────────────────
    is_first = tool_call_store.reserve(conn, idem_key, conversation_id, seq, tool_name, args)
    conn.commit()

    if not is_first:
        # Key already exists — check what state it's in
        status = tool_call_store.get_status(conn, idem_key)
        if status == "succeeded":
            cached = tool_call_store.get_result(conn, idem_key)
            print(f"[executor] {tool_name}: idempotency hit — returning cached result")
            return cached
        if status in ("pending", "running"):
            raise RuntimeError(
                f"tool_call {idem_key!r} is already {status!r} — concurrent execution"
            )
        # failed — allow retry by falling through to claim+execute
        # (caller should use a new key for a true retry; same key = same attempt)

    # ── Claim ─────────────────────────────────────────────────────────────────
    tool_call_store.claim(conn, idem_key)
    conn.commit()

    # ── Execute ───────────────────────────────────────────────────────────────
    fn = _TOOL_REGISTRY[tool_name]
    try:
        result = fn(conn, args)
    except Exception as exc:
        tool_call_store.fail(conn, idem_key, str(exc))
        raise

    # ── Complete ──────────────────────────────────────────────────────────────
    tool_call_store.complete(conn, idem_key, result)
    conn.commit()

    return result


# ── Built-in tool implementations ─────────────────────────────────────────────

@register("search_flights")
def _search_flights(conn: psycopg.Connection, args: dict) -> dict:
    origin      = args["origin"]
    destination = args["destination"]
    date        = args["date"]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.flight_id, f.flight_code, f.origin, f.destination, f.departs_at,
                   f.total_seats
                   - (SELECT COUNT(*) FROM seat_holds sh
                      WHERE sh.flight_id = f.flight_id
                        AND sh.released_at IS NULL AND sh.expires_at > now())
                   - (SELECT COUNT(*) FROM bookings b
                      WHERE b.flight_id = f.flight_id
                        AND b.status NOT IN ('void','cancelled')) AS available
            FROM flights f
            WHERE f.origin = %s AND f.destination = %s
              AND DATE(f.departs_at AT TIME ZONE 'UTC') = %s::date
            ORDER BY f.departs_at
            """,
            (origin, destination, date),
        )
        rows = cur.fetchall()

    flights = [
        {
            "flight_id": str(r[0]),
            "flight_code": r[1],
            "origin": r[2],
            "destination": r[3],
            "departs_at": r[4].isoformat(),
            "available_seats": int(r[5]),
        }
        for r in rows
        if int(r[5]) > 0
    ]
    return {"flights": flights, "count": len(flights)}
