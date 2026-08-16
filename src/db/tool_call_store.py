"""
Tool call idempotency store — adapted for official workshop schema.

Schema: tool_call_id UUID PK, idempotency_key TEXT UNIQUE, status, attempts, etc.

Lifecycle: pending -> running -> succeeded | failed
"""
from __future__ import annotations

import hashlib
import json
import uuid as _uuid

import psycopg


def make_key(conversation_id: str, seq: int, tool_name: str, args: dict) -> str:
    args_hash = hashlib.sha256(
        json.dumps(args, sort_keys=True).encode()
    ).hexdigest()[:16]
    return f"{conversation_id}:{seq}:{tool_name}:{args_hash}"


def reserve(
    conn: psycopg.Connection,
    idempotency_key: str,
    conversation_id: str,
    seq: int,
    tool_name: str,
    args: dict,
    message_id: str | None = None,
) -> bool:
    """Insert a 'pending' gate row. Returns True on first reservation, False if key exists."""
    tc_id = str(_uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tool_calls
              (tool_call_id, conversation_id, message_id, idempotency_key,
               tool_name, args, status, attempts)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s::jsonb, 'pending', 0)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                tc_id,
                conversation_id,
                message_id or tc_id,
                idempotency_key,
                tool_name,
                json.dumps(args),
            ),
        )
        return cur.rowcount == 1


def claim(conn: psycopg.Connection, idempotency_key: str) -> bool:
    """Advance pending -> running, increment attempts. Returns True on success."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tool_calls
            SET status = 'running', attempts = attempts + 1, updated_at = now()
            WHERE idempotency_key = %s AND status = 'pending'
            """,
            (idempotency_key,),
        )
        return cur.rowcount == 1


def complete(conn: psycopg.Connection, idempotency_key: str, result: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tool_calls
            SET status = 'succeeded', result = %s::jsonb,
                updated_at = now(), completed_at = now()
            WHERE idempotency_key = %s
            """,
            (json.dumps(result), idempotency_key),
        )


def fail(conn: psycopg.Connection, idempotency_key: str, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tool_calls
            SET status = 'failed', error = %s, updated_at = now()
            WHERE idempotency_key = %s
            """,
            (error, idempotency_key),
        )
    conn.commit()


def get_result(conn: psycopg.Connection, idempotency_key: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT result FROM tool_calls WHERE idempotency_key = %s AND status = 'succeeded'",
            (idempotency_key,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def get_status(conn: psycopg.Connection, idempotency_key: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM tool_calls WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        row = cur.fetchone()
    return row[0] if row else None


# Shims used by saga.py
def begin_call(
    conn: psycopg.Connection,
    idempotency_key: str,
    tool_name: str,
    args: dict,
    conversation_id: str = "",
    seq: int = 0,
) -> bool:
    first = reserve(conn, idempotency_key, conversation_id, seq, tool_name, args)
    if first:
        claim(conn, idempotency_key)
    return first


def complete_call(conn: psycopg.Connection, idempotency_key: str, result: dict) -> None:
    complete(conn, idempotency_key, result)
