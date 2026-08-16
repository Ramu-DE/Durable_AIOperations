"""Integration tests for saga_store — requires a live DSQL connection."""
import os
import sys
import uuid
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.db.dsql_client import get_connection
from src.db import saga_store
from src.booking.models import StepStatus


@pytest.fixture
def conn():
    c = get_connection()
    yield c
    c.close()


@pytest.fixture
def booking_id():
    return f"TEST-{uuid.uuid4().hex[:8].upper()}"


def test_create_and_get_saga(conn, booking_id):
    payload = {"origin": "JFK", "destination": "LAX"}
    saga_store.create_saga(conn, booking_id, payload)
    saga = saga_store.get_saga(conn, booking_id)
    assert saga is not None
    assert saga["booking_id"] == booking_id
    assert saga["status"] == "in_progress"


def test_create_saga_idempotent(conn, booking_id):
    saga_store.create_saga(conn, booking_id, {})
    saga_store.create_saga(conn, booking_id, {})  # must not raise
    assert saga_store.get_saga(conn, booking_id) is not None


def test_upsert_and_get_completed_steps(conn, booking_id):
    saga_store.create_saga(conn, booking_id, {})
    saga_store.upsert_step(conn, booking_id, "hold_seat", StepStatus.COMPLETED, {"hold_id": "X"})
    saga_store.upsert_step(conn, booking_id, "authorize_payment", StepStatus.PENDING)

    completed = saga_store.get_completed_steps(conn, booking_id)
    assert "hold_seat" in completed
    assert completed["hold_seat"]["hold_id"] == "X"
    assert "authorize_payment" not in completed


def test_compensation_result_stored(conn, booking_id):
    saga_store.create_saga(conn, booking_id, {})
    saga_store.upsert_step(
        conn, booking_id, "hold_seat", StepStatus.COMPENSATED,
        result={"hold_id": "X"},
        compensation_result={"action": "released"},
    )
    # compensated steps are not returned by get_completed_steps (status != 'completed')
    completed = saga_store.get_completed_steps(conn, booking_id)
    assert "hold_seat" not in completed


def test_complete_and_fail_saga(conn, booking_id):
    saga_store.create_saga(conn, booking_id, {})
    saga_store.complete_saga(conn, booking_id)
    assert saga_store.get_saga(conn, booking_id)["status"] == "completed"

    bid2 = booking_id + "F"
    saga_store.create_saga(conn, bid2, {})
    saga_store.fail_saga(conn, bid2)
    assert saga_store.get_saga(conn, bid2)["status"] == "failed"
