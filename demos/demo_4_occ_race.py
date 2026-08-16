"""
Demo 4 — OCC Seat Race (Optimistic Concurrency Control)

Proves that two agents racing for the last seat produce exactly one hold.
Aurora DSQL's earliest-commit-wins OCC: when both agents read the same
availability count inside their transactions and try to commit, DSQL detects
the overlapping read-set and aborts the later committer.

Flow:
  1. Reset AA100 (SEA→JFK) to exactly 1 available seat.
  2. Two agents race to call hold_seat for that flight.
  3. DSQL OCC: one transaction commits, the other fails with SerializationFailure.
  4. The loser raises SeatConflict; the winner gets the confirmed booking.

Verify:
    SELECT hold_id, seat_number, expires_at
    FROM seat_holds
    WHERE flight_id = '11111111-1111-1111-1111-111111111111'::uuid
      AND released_at IS NULL AND expires_at > now();
    -- Exactly 1 row.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.agent.booking_agent import run_booking
from src.booking.models import BookingRequest, SeatConflict
from src.db.dsql_client import get_connection

# AA100 SEA→JFK pre-seeded UUID
FLIGHT_ID = "11111111-1111-1111-1111-111111111111"
ep = os.environ.get("DSQL_ENDPOINT_A")
region = os.environ.get("REGION_A", "us-west-2")


def _reset_seat_inventory():
    """Give AA100 exactly 1 available seat for a clean race."""
    conn = get_connection(ep)
    with conn.cursor() as cur:
        # Release all active holds
        cur.execute(
            "UPDATE seat_holds SET released_at = now() WHERE flight_id = %s::uuid AND released_at IS NULL",
            (FLIGHT_ID,),
        )
        # Cancel all bookings
        cur.execute(
            "UPDATE bookings SET status = 'cancelled', updated_at = now() WHERE flight_id = %s::uuid AND status NOT IN ('cancelled','void')",
            (FLIGHT_ID,),
        )
        # Set total_seats to 1 so only one agent can win
        cur.execute(
            "UPDATE flights SET total_seats = 1 WHERE flight_id = %s::uuid",
            (FLIGHT_ID,),
        )
    conn.commit()
    conn.close()
    print("[setup] Reset AA100 (SEA→JFK) to exactly 1 available seat.\n")


results_store = {}
errors_store = {}


def race_booking(agent_id: str, saga_id: str):
    request = BookingRequest(
        saga_id=saga_id,
        conversation_id=f"44444444-cccc-4000-8000-{agent_id[-12:].replace('-','')[:12].ljust(12,'0')}",
        user_id=f"Agent {agent_id}",
        origin="SEA",
        destination="JFK",
        date="2026-08-01",
    )
    try:
        result = run_booking(request, endpoint=ep, region=region)
        results_store[agent_id] = result
        booking_id = result.get("confirm_booking", {}).get("booking_id", "N/A")
        print(f"[{agent_id}] WINNER — booking_id={booking_id}")
    except SeatConflict as e:
        errors_store[agent_id] = f"SeatConflict: {e}"
        print(f"[{agent_id}] Lost OCC race: {e}")
    except Exception as e:
        errors_store[agent_id] = str(e)
        print(f"[{agent_id}] Error: {type(e).__name__}: {e}")


print("=== Demo 4: OCC Seat Race — two agents, one seat ===\n")
_reset_seat_inventory()

t1 = threading.Thread(
    target=race_booking,
    args=("agent-X", "44444444-aaaa-4000-8000-000000000004"),
    name="agent-X",
)
t2 = threading.Thread(
    target=race_booking,
    args=("agent-Y", "55555555-aaaa-4000-8000-000000000005"),
    name="agent-Y",
)

t1.start()
t2.start()
t1.join()
t2.join()

# Verify: only one active hold should exist
conn = get_connection(ep)
with conn.cursor() as cur:
    cur.execute(
        """
        SELECT COUNT(*) FROM seat_holds
        WHERE flight_id = %s::uuid
          AND released_at IS NULL AND expires_at > now()
        """,
        (FLIGHT_ID,),
    )
    held_count = cur.fetchone()[0]
conn.close()

print(f"\n[Verification] Active holds on AA100 (SEA→JFK): {held_count}")
winners = list(results_store.keys())
losers = list(errors_store.keys())

if held_count == 1 and len(winners) == 1 and len(losers) == 1:
    print(f"[Demo 4 PASS] {winners[0]} won; {losers[0]} received SeatConflict — no lost-update.")
elif held_count == 0:
    print("[Demo 4 FAIL] No seat was held — both agents failed.")
elif held_count > 1:
    print(f"[Demo 4 FAIL] {held_count} seats held — OCC did not protect against double-booking!")
else:
    print(f"[Demo 4 WARN] Winners: {winners}  Losers: {losers}")
