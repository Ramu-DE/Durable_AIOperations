"""
Demo 1 — Agent Crash Mid-Saga

Run 1: CRASH_AFTER_STEP=hold_seat in .env  → process dies after hold commits.
Run 2: CRASH_AFTER_STEP= (blank)           → resumes from authorize_payment.

Verify:
    SELECT step_name, status, direction FROM saga_steps WHERE saga_id='<saga_id>';
    -- All three forward steps completed; no seat held twice.
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import uuid
from src.agent.booking_agent import run_booking
from src.booking.models import BookingRequest
from src.chaos.crash import CrashInjector

SAGA_ID = "11111111-aaaa-4000-8000-000000000001"   # fixed UUID for repeatability
CONV_ID = "11111111-bbbb-4000-8000-000000000001"

request = BookingRequest(
    saga_id=SAGA_ID,
    conversation_id=CONV_ID,
    user_id="Alice Demo",
    origin="SEA",
    destination="JFK",
    date="2026-08-01",
)

crash_after = os.environ.get("CRASH_AFTER_STEP", "").strip() or None
injector = CrashInjector(crash_after_step=crash_after)

if crash_after:
    print(f"=== Demo 1: RUN 1 — will crash after '{crash_after}' ===\n")
else:
    print(f"=== Demo 1: RUN 2 — resuming saga {SAGA_ID} ===\n")

try:
    results = run_booking(
        request,
        endpoint=os.environ.get("DSQL_ENDPOINT_A"),
        region=os.environ.get("REGION_A", "us-west-2"),
        crash_injector=injector,
    )
    print("\n=== Booking complete ===")
    print(json.dumps(results, indent=2, default=str))
except SystemExit:
    print(f"\n[Demo 1] Process killed by crash injector.")
    print(f"         Re-run without CRASH_AFTER_STEP to resume saga {SAGA_ID}.")
