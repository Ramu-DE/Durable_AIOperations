"""
Booking agent — wires SagaOrchestrator to the step/compensation handlers.

The flights table has UUID PKs and pre-seeded data:
  AA100  SEA→JFK  11111111-1111-1111-1111-111111111111
  AA200  SEA→LHR  22222222-2222-2222-2222-222222222222
  AA300  SFO→NRT  33333333-3333-3333-3333-333333333333
"""
from __future__ import annotations

import os

import psycopg

from src.agent.tools import (
    hold_seat_handler,
    authorize_payment_handler,
    confirm_booking_handler,
    release_seat_handler,
    void_authorization_handler,
    cancel_booking_handler,
)
from src.booking.models import BookingRequest
from src.booking.saga import SagaOrchestrator
from src.db.dsql_client import get_connection

STEP_HANDLERS = {
    "hold_seat":          hold_seat_handler,
    "authorize_payment":  authorize_payment_handler,
    "confirm_booking":    confirm_booking_handler,
}

COMPENSATION_HANDLERS = {
    "release_seat":       release_seat_handler,
    "void_authorization": void_authorization_handler,
    "cancel_booking":     cancel_booking_handler,
}


def search(
    request: BookingRequest,
    endpoint: str | None = None,
) -> dict:
    """Find the best matching flight for the request. Returns {flight_id, flight_code, ...}."""
    conn = get_connection(endpoint)
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
            LIMIT 1
            """,
            (request.origin, request.destination, request.date),
        )
        row = cur.fetchone()
    conn.close()

    if row is None or int(row[6]) <= 0:
        raise ValueError(
            f"No available flights: {request.origin}→{request.destination} on {request.date}"
        )
    return {
        "flight_id": str(row[0]),
        "flight_code": row[1],
        "origin": row[2],
        "destination": row[3],
        "departs_at": row[4].isoformat(),
        "total_seats": row[5],
        "available_seats": int(row[6]),
        "price_usd": 199.0,   # placeholder — real system would have pricing table
    }


def run_booking(
    request: BookingRequest,
    endpoint: str | None = None,
    region: str = "",
    crash_injector=None,
) -> dict:
    """
    Run the full booking saga. Returns combined state dict from all steps.

    endpoint       — override DSQL_ENDPOINT (region-failover demo)
    region         — DSQL region label (written to sagas.last_touched_region)
    crash_injector — CrashInjector for chaos demo
    """
    flight = search(request, endpoint)
    initial_state = {"flight_id": flight["flight_id"], "flight_info": flight}

    conn = get_connection(endpoint)
    orchestrator = SagaOrchestrator(
        conn=conn,
        step_handlers=STEP_HANDLERS,
        compensation_handlers=COMPENSATION_HANDLERS,
        region=region or os.environ.get("AWS_DEFAULT_REGION", "us-west-2"),
        crash_injector=crash_injector,
    )
    state = orchestrator.run(request.saga_id, request, initial_state)
    conn.close()
    return state
