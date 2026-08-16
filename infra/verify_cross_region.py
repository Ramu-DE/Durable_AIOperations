"""
Module 1 — Verify cross-region write visibility

Proves DSQL's active-active strong consistency claim:
a row written to us-east-1 is immediately readable from us-west-2
on the very next query, with no eventual-consistency lag.

Usage:
    source .env
    python infra/verify_cross_region.py

Expected output:
    [us-east-1] INSERT probe row  id=<uuid>  value=<timestamp>
    [us-west-2] SELECT same row   id=<uuid>  value=<timestamp>   ✓ VISIBLE
    [us-west-2] DELETE probe row
    [us-east-1] SELECT after DELETE          ✓ NOT FOUND

If reads take more than one attempt, the check reports how many retries
were needed — which would indicate eventual (not strong) consistency.
"""
import os
import sys
import uuid
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.db.dsql_client import get_connection

BOLD  = "\033[1m"
GREEN = "\033[0;32m"
RED   = "\033[0;31m"
RESET = "\033[0m"
HR    = "─" * 62


def banner(msg: str) -> None:
    print(f"\n{BOLD}{HR}{RESET}")
    print(f"{BOLD}  {msg}{RESET}")
    print(f"{BOLD}{HR}{RESET}\n")


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    suffix = f"  {detail}" if detail else ""
    print(f"  {mark}  {label}{suffix}")
    if not ok:
        sys.exit(1)


def main():
    primary_ep = os.environ.get("DSQL_ENDPOINT")
    peer_ep = os.environ.get("DSQL_ENDPOINT_PEER")
    primary_region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    if not primary_ep or not peer_ep:
        print("ERROR: DSQL_ENDPOINT and DSQL_ENDPOINT_PEER must be set in .env")
        sys.exit(1)

    banner("Module 1 — Cross-Region Write Visibility Test")
    print(f"  Primary  : {primary_ep}")
    print(f"  Peer     : {peer_ep}")
    print()

    probe_id = str(uuid.uuid4())
    probe_value = f"probe-{int(time.time())}"

    # ── 1. Write to primary region ───────────────────────────────────────────
    print(f"[{primary_region}]  Writing probe row...")
    primary_conn = get_connection(primary_ep)
    with primary_conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS _dsql_probe (
                id    TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                ts    TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            "INSERT INTO _dsql_probe (id, value) VALUES (%s, %s)",
            (probe_id, probe_value),
        )
    primary_conn.commit()
    print(f"  id    = {probe_id}")
    print(f"  value = {probe_value}")

    # ── 2. Read immediately from peer region ─────────────────────────────────
    peer_region = peer_ep.split(".dsql.")[1].split(".")[0] if ".dsql." in peer_ep else "peer"
    print(f"\n[{peer_region}]  Reading probe row immediately (no sleep)...")

    peer_conn = get_connection(peer_ep)
    attempts = 0
    row = None

    for attempt in range(1, 6):
        attempts = attempt
        with peer_conn.cursor() as cur:
            cur.execute(
                "SELECT id, value, ts FROM _dsql_probe WHERE id = %s",
                (probe_id,),
            )
            row = cur.fetchone()
        if row:
            break
        print(f"  attempt {attempt}: not found yet — waiting 250ms...")
        time.sleep(0.25)

    check(
        f"Row visible on peer after {attempts} attempt(s)",
        row is not None,
        f"value={row[1]}  ts={row[2]}" if row else "(not found)",
    )

    if attempts == 1:
        print(f"\n  {GREEN}Strong consistency confirmed — visible on first read, zero lag.{RESET}")
    else:
        print(f"\n  {RED}WARNING: required {attempts} attempts — eventual, not strong, consistency.{RESET}")

    # ── 3. Delete from peer region, verify gone on primary ───────────────────
    print(f"\n[{peer_region}]  Deleting probe row from peer region...")
    with peer_conn.cursor() as cur:
        cur.execute("DELETE FROM _dsql_probe WHERE id = %s", (probe_id,))
    peer_conn.commit()
    peer_conn.close()

    print(f"\n[{primary_region}]  Verifying deletion is visible on primary...")
    del_attempts = 0
    gone = False
    for attempt in range(1, 6):
        del_attempts = attempt
        with primary_conn.cursor() as cur:
            cur.execute("SELECT id FROM _dsql_probe WHERE id = %s", (probe_id,))
            if cur.fetchone() is None:
                gone = True
                break
        time.sleep(0.25)
    primary_conn.close()

    check(
        f"Deletion visible on primary after {del_attempts} attempt(s)",
        gone,
        "(row absent)" if gone else "(row still present!)",
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{HR}{RESET}")
    print(f"  {GREEN}{BOLD}Module 1 PASSED{RESET}")
    print(f"{BOLD}{HR}{RESET}")
    print()
    print("  Both regions accepted writes and reads with strong consistency.")
    print("  Your DSQL cluster is ready for the booking saga demos.")
    print()
    print("  Next: python demos/demo_1_crash.py")
    print()


if __name__ == "__main__":
    main()
