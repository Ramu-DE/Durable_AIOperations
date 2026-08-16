"""
Booking tool implementations — aligned with official workshop schema.

seat_holds: hold_id UUID, flight_id UUID, seat_number TEXT, conversation_id UUID,
            expires_at TIMESTAMPTZ, released_at TIMESTAMPTZ (NULL = active hold)

bookings:   booking_id UUID, saga_id UUID, flight_id UUID, seat_number TEXT,
            amount_cents BIGINT, status TEXT, payment_auth_id TEXT, payment_charge_id TEXT

Seat availability: total_seats - active_holds - confirmed_bookings
OCC: DSQL's optimistic concurrency means the count-then-insert read-set overlaps,
     so concurrent agents racing for the last seat will have one commit fail.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta

import psycopg
from strands import tool

from src.booking.models import BookingRequest, SeatConflict
from src.db.dsql_client import get_connection

HOLD_DURATION_MINUTES = 10


# ── Availability helper ────────────────────────────────────────────────────────

def _available_count(cur, flight_id_uuid: str) -> int:
    cur.execute(
        """
        SELECT f.total_seats
             - (SELECT COUNT(*) FROM seat_holds sh
                WHERE sh.flight_id = f.flight_id
                  AND sh.released_at IS NULL
                  AND sh.expires_at > now())
             - (SELECT COUNT(*) FROM bookings b
                WHERE b.flight_id = f.flight_id
                  AND b.status NOT IN ('void','cancelled'))
        FROM flights f WHERE f.flight_id = %s::uuid
        """,
        (flight_id_uuid,),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


# ── Forward step handlers ──────────────────────────────────────────────────────

def hold_seat_handler(
    conn: psycopg.Connection,
    saga_id: str,
    request: BookingRequest,
    prior: dict,
) -> dict:
    """
    Reserve a seat on the flight.
    OCC conflict: if two agents read 'available' concurrently, only the earliest
    commit succeeds — DSQL detects the overlapping read-set.
    """
    flight_id = prior.get("flight_id") or prior.get("hold_seat", {}).get("flight_id")
    if not flight_id:
        raise BookingError("hold_seat: flight_id missing from prior state")

    with conn.cursor() as cur:
        available = _available_count(cur, flight_id)
        if available <= 0:
            raise SeatConflict(f"No seats available on flight {flight_id}")

        # Assign seat number based on current hold count + 1
        cur.execute(
            "SELECT COUNT(*) FROM seat_holds WHERE flight_id=%s::uuid AND released_at IS NULL",
            (flight_id,),
        )
        seat_num = cur.fetchone()[0] + 1
        seat_number = f"{seat_num}A"

        hold_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=HOLD_DURATION_MINUTES)
        cur.execute(
            """
            INSERT INTO seat_holds (hold_id, flight_id, seat_number, conversation_id, expires_at)
            VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s)
            """,
            (hold_id, flight_id, seat_number, request.conversation_id, expires_at),
        )

    return {
        "hold_id": hold_id,
        "flight_id": flight_id,
        "seat_number": seat_number,
        "expires_at": expires_at.isoformat(),
    }


def authorize_payment_handler(
    conn: psycopg.Connection,
    saga_id: str,
    request: BookingRequest,
    prior: dict,
) -> dict:
    """Create a booking row with status='authorized'."""
    hold = prior.get("hold_seat", {})
    flight_info = prior.get("flight_info", {})
    amount_cents = int(flight_info.get("price_usd", 199.0) * 100)

    booking_id = str(uuid.uuid4())
    payment_auth_id = f"AUTH-{uuid.uuid4().hex[:12].upper()}"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bookings
              (booking_id, conversation_id, saga_id, flight_id,
               seat_number, payment_auth_id, amount_cents, status)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, 'authorized')
            ON CONFLICT (booking_id) DO NOTHING
            """,
            (
                booking_id,
                request.conversation_id,
                saga_id,
                hold.get("flight_id"),
                hold.get("seat_number"),
                payment_auth_id,
                amount_cents,
            ),
        )

    return {
        "booking_id": booking_id,
        "payment_auth_id": payment_auth_id,
        "amount_cents": amount_cents,
        "status": "authorized",
    }


def confirm_booking_handler(
    conn: psycopg.Connection,
    saga_id: str,
    request: BookingRequest,
    prior: dict,
) -> dict:
    """Finalize: capture payment and confirm booking."""
    auth = prior.get("authorize_payment", {})
    booking_id = auth.get("booking_id")
    payment_charge_id = f"CHG-{uuid.uuid4().hex[:12].upper()}"

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET status='confirmed', payment_charge_id=%s, updated_at=now()
            WHERE booking_id=%s::uuid
            """,
            (payment_charge_id, booking_id),
        )

    return {
        "booking_id": booking_id,
        "payment_charge_id": payment_charge_id,
        "status": "confirmed",
    }


# ── Compensation handlers ──────────────────────────────────────────────────────

def release_seat_handler(conn: psycopg.Connection, saga_id: str, results: dict) -> dict:
    hold_id = results.get("hold_seat", {}).get("hold_id")
    if hold_id:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE seat_holds SET released_at=now() WHERE hold_id=%s::uuid AND released_at IS NULL",
                (hold_id,),
            )
        conn.commit()
    return {"hold_id": hold_id, "action": "released"}


def void_authorization_handler(conn: psycopg.Connection, saga_id: str, results: dict) -> dict:
    booking_id = results.get("authorize_payment", {}).get("booking_id")
    if booking_id:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bookings SET status='void', updated_at=now() WHERE booking_id=%s::uuid",
                (booking_id,),
            )
        conn.commit()
    return {"booking_id": booking_id, "action": "void"}


def cancel_booking_handler(conn: psycopg.Connection, saga_id: str, results: dict) -> dict:
    booking_id = results.get("authorize_payment", {}).get("booking_id")
    hold_id = results.get("hold_seat", {}).get("hold_id")
    with conn.cursor() as cur:
        if booking_id:
            cur.execute(
                "UPDATE bookings SET status='cancelled', updated_at=now() WHERE booking_id=%s::uuid",
                (booking_id,),
            )
        if hold_id:
            cur.execute(
                "UPDATE seat_holds SET released_at=now() WHERE hold_id=%s::uuid",
                (hold_id,),
            )
    conn.commit()
    return {"booking_id": booking_id, "hold_id": hold_id, "action": "cancelled"}


# ── Strands @tool wrapper (used when LLM drives) ───────────────────────────────

@tool
def search_flights(origin: str, destination: str, date: str) -> str:
    """Search for available flights. Returns JSON list of flights with available seat counts."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.flight_id, f.flight_code, f.origin, f.destination,
                   f.departs_at, f.total_seats,
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
    conn.close()

    flights = [
        {
            "flight_id": str(r[0]),
            "flight_code": r[1],
            "origin": r[2],
            "destination": r[3],
            "departs_at": r[4].isoformat(),
            "total_seats": r[5],
            "available_seats": int(r[6]),
        }
        for r in rows
        if int(r[6]) > 0
    ]
    return json.dumps(flights)
