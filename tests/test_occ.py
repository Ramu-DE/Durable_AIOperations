"""OCC seat hold tests — verify lost-update protection on seat_holds table."""
import os
import sys
import uuid
import threading
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.db.dsql_client import get_connection
from src.booking.models import SeatConflict


def _seed_test_seat(conn, flight_id: str, hold_id: str):
    """Insert a test flight and one available seat for OCC testing."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO flights (flight_id, origin, destination, departs_at) "
            "VALUES (%s, 'TST', 'TST', now() + interval '1 day') ON CONFLICT DO NOTHING",
            (flight_id,),
        )
        cur.execute(
            """
            INSERT INTO seat_holds (hold_id, flight_id, seat_number, seat_class, price_usd, status, version)
            VALUES (%s, %s, '1A', 'economy', 99.00, 'available', 0)
            ON CONFLICT (hold_id) DO UPDATE
              SET status='available', booking_id=NULL, version=0
            """,
            (hold_id, flight_id),
        )
    conn.commit()


def _attempt_hold(conn, hold_id: str, booking_id: str, results: dict, key: str):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version FROM seat_holds WHERE hold_id = %s AND status = 'available' "
                "FOR UPDATE SKIP LOCKED",
                (hold_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise SeatConflict(f"{hold_id} unavailable")
            version = row[0]
            cur.execute(
                "UPDATE seat_holds SET status='held', booking_id=%s, version=version+1 "
                "WHERE hold_id=%s AND version=%s AND status='available'",
                (booking_id, hold_id, version),
            )
            if cur.rowcount == 0:
                raise SeatConflict(f"OCC conflict on {hold_id}")
        conn.commit()
        results[key] = "won"
    except SeatConflict:
        results[key] = "conflict"
    finally:
        conn.close()


def test_occ_only_one_hold_wins():
    flight_id = f"TST-{uuid.uuid4().hex[:6].upper()}"
    hold_id = f"{flight_id}-E1"

    setup = get_connection()
    _seed_test_seat(setup, flight_id, hold_id)
    setup.close()

    results = {}
    c1, c2 = get_connection(), get_connection()

    t1 = threading.Thread(target=_attempt_hold, args=(c1, hold_id, "BK-X", results, "t1"))
    t2 = threading.Thread(target=_attempt_hold, args=(c2, hold_id, "BK-Y", results, "t2"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    winners = [k for k, v in results.items() if v == "won"]
    losers  = [k for k, v in results.items() if v == "conflict"]
    assert len(winners) == 1, f"Expected 1 winner, got {winners}"
    assert len(losers)  == 1, f"Expected 1 loser, got {losers}"

    verify = get_connection()
    with verify.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM seat_holds WHERE hold_id=%s AND status='held'",
            (hold_id,),
        )
        assert cur.fetchone()[0] == 1
    verify.close()
