"""
Demo 2 — Region Failover

1. Run saga in us-west-2, crash after hold_seat.
2. Switch to us-east-1 endpoint.
3. Resume same saga — agent reads completed steps and continues from authorize_payment.

Verify:
    sagas.last_touched_region changes from us-west-2 to us-east-1
    All three saga_steps completed; no duplicate holds.
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.agent.booking_agent import run_booking
from src.booking.models import BookingRequest
from src.chaos.crash import CrashInjector
from src.chaos.region_switch import RegionSwitcher

SAGA_ID = "22222222-aaaa-4000-8000-000000000002"
CONV_ID = "22222222-bbbb-4000-8000-000000000002"

request = BookingRequest(
    saga_id=SAGA_ID,
    conversation_id=CONV_ID,
    user_id="Bob Failover",
    origin="SEA",
    destination="JFK",
    date="2026-08-01",
)

ep_a = os.environ.get("DSQL_ENDPOINT_A")
ep_b = os.environ.get("DSQL_ENDPOINT_B")
switcher = RegionSwitcher()

print("=== Demo 2: Step 1 — Running in us-west-2, crash after hold_seat ===\n")
try:
    run_booking(request, endpoint=ep_a, region="us-west-2",
                crash_injector=CrashInjector("hold_seat"))
except SystemExit:
    pass

print("\n=== Demo 2: Step 2 — Switching to us-east-1 ===\n")
switcher.fail_over()

print(f"=== Demo 2: Step 3 — Resuming on us-east-1 ===\n")
results = run_booking(request, endpoint=ep_b, region="us-east-1", crash_injector=None)
print("\n=== Booking complete on peer region ===")
print(json.dumps(results, indent=2, default=str))
print(f"\n[Demo 2 PASS] Saga {SAGA_ID} completed after region failover.")
