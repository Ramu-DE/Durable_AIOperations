"""
Demo 3 — Duplicate Requests / Idempotency

Proves that firing the same saga_id twice does not produce duplicate charges.

Flow:
  Two threads both call run_booking() with the same saga_id/conversation_id.
  The tool_calls table acts as an at-most-once gate: the first to reach
  authorize_payment stores the idempotency key and commits the booking row.
  The second thread finds status='succeeded' and returns the same payment_auth_id.

Verify:
    SELECT idempotency_key, status, result
    FROM tool_calls
    WHERE conversation_id = '33333333-bbbb-4000-8000-000000000003'::uuid;
    -- 3 rows (one per saga step), not 6.
    -- Both threads return the same payment_auth_id.
"""
import os
import sys
import json
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.agent.booking_agent import run_booking
from src.booking.models import BookingRequest

SAGA_ID = "33333333-aaaa-4000-8000-000000000003"
CONV_ID = "33333333-bbbb-4000-8000-000000000003"

request = BookingRequest(
    saga_id=SAGA_ID,
    conversation_id=CONV_ID,
    user_id="Carol Duplicate",
    origin="SEA",
    destination="JFK",
    date="2026-08-01",
)

results_store = {}
errors_store = {}

ep = os.environ.get("DSQL_ENDPOINT_A")
region = os.environ.get("REGION_A", "us-west-2")


def book(thread_id: str):
    try:
        result = run_booking(request, endpoint=ep, region=region)
        results_store[thread_id] = result
    except Exception as e:
        errors_store[thread_id] = str(e)


print("=== Demo 3: Firing two concurrent duplicate booking requests ===\n")

t1 = threading.Thread(target=book, args=("thread-A",), name="thread-A")
t2 = threading.Thread(target=book, args=("thread-B",), name="thread-B")

t1.start()
t2.start()
t1.join()
t2.join()

print("\n=== Results ===")
for tid, result in results_store.items():
    auth = result.get("authorize_payment", {})
    confirm = result.get("confirm_booking", {})
    print(f"  {tid}: payment_auth_id={auth.get('payment_auth_id','N/A')}  booking_id={confirm.get('booking_id','N/A')}")

for tid, err in errors_store.items():
    print(f"  {tid}: ERROR — {err}")

# Verify idempotency: both threads must return the same payment_auth_id
auth_ids = {
    r.get("authorize_payment", {}).get("payment_auth_id")
    for r in results_store.values()
    if r.get("authorize_payment", {}).get("payment_auth_id")
}
if len(auth_ids) == 1:
    print(f"\n[Demo 3 PASS] Both threads returned the same payment_auth_id: {auth_ids.pop()}")
elif len(auth_ids) > 1:
    print(f"\n[Demo 3 FAIL] Different payment_auth_ids: {auth_ids}")
else:
    print(f"\n[Demo 3 INFO] Results: {results_store}  Errors: {errors_store}")
