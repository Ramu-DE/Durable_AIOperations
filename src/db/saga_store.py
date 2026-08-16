"""
Saga persistence — adapted for official workshop schema.

Key differences from design doc:
- PK is saga_id (UUID), not booking_id
- saga_steps uses step_id UUID PK, step_index INT, direction (forward/backward)
- Results stored in sagas.state JSONB, not in saga_steps.result
- Compensation recorded as backward saga_steps
"""
from __future__ import annotations

import json
import uuid as _uuid

import psycopg


# ── Sagas ─────────────────────────────────────────────────────────────────────

def create_saga(
    conn: psycopg.Connection,
    saga_id: str,
    conversation_id: str,
    payload: dict,
    region: str = "",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sagas
              (saga_id, conversation_id, saga_type, status, current_step,
               state, last_touched_region, last_touched_at)
            VALUES (%s::uuid, %s::uuid, 'flight_booking', 'in_progress',
                    0, %s::jsonb, %s, now())
            ON CONFLICT (saga_id) DO NOTHING
            """,
            (saga_id, conversation_id, json.dumps(payload), region),
        )
    conn.commit()


def get_saga(conn: psycopg.Connection, saga_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT saga_id, conversation_id, status, current_step, state,
                   last_touched_region, created_at, updated_at
            FROM sagas WHERE saga_id = %s::uuid
            """,
            (saga_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "saga_id": str(row[0]),
        "conversation_id": str(row[1]),
        "status": row[2],
        "current_step": row[3],
        "state": row[4] or {},
        "last_touched_region": row[5],
    }


def touch_saga(conn: psycopg.Connection, saga_id: str, region: str) -> None:
    """Update last_touched_region so any region can see who last worked on this."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sagas
            SET last_touched_region = %s, last_touched_at = now(), updated_at = now()
            WHERE saga_id = %s::uuid
            """,
            (region, saga_id),
        )
    conn.commit()


def update_state(conn: psycopg.Connection, saga_id: str, state: dict, current_step: int) -> None:
    """Persist accumulated step results back to sagas.state."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sagas
            SET state = %s::jsonb, current_step = %s, updated_at = now()
            WHERE saga_id = %s::uuid
            """,
            (json.dumps(state), current_step, saga_id),
        )
    conn.commit()


def complete_saga(conn: psycopg.Connection, saga_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sagas SET status='completed', updated_at=now() WHERE saga_id=%s::uuid",
            (saga_id,),
        )
    conn.commit()


def fail_saga(conn: psycopg.Connection, saga_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sagas SET status='failed', updated_at=now() WHERE saga_id=%s::uuid",
            (saga_id,),
        )
    conn.commit()


# ── Saga steps ────────────────────────────────────────────────────────────────

def add_step(
    conn: psycopg.Connection,
    saga_id: str,
    step_index: int,
    step_name: str,
    direction: str = "forward",
    tool_call_id: str | None = None,
) -> str:
    """Insert a saga step row. Returns the new step_id."""
    step_id = str(_uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO saga_steps
              (step_id, saga_id, step_index, step_name, direction, tool_call_id, status)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::uuid, 'pending')
            ON CONFLICT DO NOTHING
            """,
            (step_id, saga_id, step_index, step_name, direction,
             tool_call_id if tool_call_id else None),
        )
    conn.commit()
    return step_id


def complete_step(conn: psycopg.Connection, step_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE saga_steps SET status='completed', completed_at=now() WHERE step_id=%s::uuid",
            (step_id,),
        )
    conn.commit()


def get_completed_step_names(conn: psycopg.Connection, saga_id: str) -> list[str]:
    """Return step_names of all completed forward steps, ordered by step_index."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT step_name FROM saga_steps
            WHERE saga_id = %s::uuid AND direction = 'forward' AND status = 'completed'
            ORDER BY step_index
            """,
            (saga_id,),
        )
        return [r[0] for r in cur.fetchall()]


# Backwards-compat shims used by older saga.py code
def upsert_step(
    conn: psycopg.Connection,
    booking_id: str,    # saga_id in new schema
    step_name: str,
    status: str,
    result: dict | None = None,
    compensation_result: dict | None = None,
) -> None:
    """Shim: accepts old-style booking_id/step_name calls."""
    if status == "completed":
        # Find the existing pending step and mark complete
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE saga_steps SET status='completed', completed_at=now()
                WHERE saga_id=%s::uuid AND step_name=%s AND direction='forward'
                  AND status='pending'
                """,
                (booking_id, step_name),
            )
        conn.commit()
    elif status == "compensated":
        add_step(conn, booking_id, 999, step_name, direction="backward")


def get_completed_steps(conn: psycopg.Connection, booking_id: str) -> dict[str, dict]:
    """Shim: return {step_name: state_slice} for completed forward steps."""
    saga = get_saga(conn, booking_id)
    if not saga:
        return {}
    completed_names = get_completed_step_names(conn, booking_id)
    state = saga.get("state", {})
    return {name: state.get(name, {}) for name in completed_names}
