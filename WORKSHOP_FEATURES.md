# Workshop Features: Agents That Don't Forget
## Durable AI Operations with Amazon Aurora DSQL

---

## What Problem This Workshop Solves

AI agents that execute multi-step workflows fail silently.
A booking agent that crashes after charging a credit card but before confirming the seat
leaves the customer charged with no ticket — with no way to know where it stopped.

This workshop solves that by showing three core guarantees:

1. **Crash safety** — if the agent dies mid-saga, the next run resumes from the exact step it left off, without re-executing completed steps
2. **Cross-region durability** — all saga state lives in Aurora DSQL, which is active-active across two AWS regions; if one region's agent dies, the peer region's agent reads the same state and continues
3. **Idempotency** — firing the same booking request twice (network retry, duplicate click, restart) produces one charge and one confirmation, never two

---

## Module 1 — Set Up Aurora DSQL Multi-Region

**What it teaches:**
- Aurora DSQL is serverless, PostgreSQL-compatible, and active-active across regions
- No SERIAL/sequences — all PKs are UUIDs (no single-point sequence generator)
- No foreign key constraints — each table is independent; cross-table consistency is the application's responsibility
- OCC (Optimistic Concurrency Control) instead of locks — earliest-commit-wins; conflicting transactions get a serialization error, not a deadlock
- Strong consistency across regions — a write committed in us-west-2 is immediately visible in us-east-1

**What gets built:**
- Multi-region DSQL cluster (us-west-2 + us-east-1)
- IAM token authentication via `boto3.client("dsql").generate_db_connect_admin_auth_token()`
- Connection factory in `src/db/dsql_client.py`

**Key DSQL behaviors demonstrated:**
- `psycopg.errors.SerializationFailure` — raised when OCC detects a conflicting transaction (Demo 4)
- Active-active writes — both regions accept writes; DSQL handles conflict resolution
- Serverless — no instances to manage, scales to zero

---

## Module 2 — Design a Crash-Safe Schema

**What it teaches:**
- Why naive "write-then-confirm" patterns create phantom charges on restart
- The saga pattern: each mutating step has a compensating transaction
- Atomic idempotency: gate INSERT (pending) + domain mutation + gate UPDATE (succeeded) in ONE transaction

**Schema tables built:**

| Table | Purpose |
|---|---|
| `conversations` | One row per user session; UUID PK |
| `messages` | Every user/assistant/tool message with JSONB content |
| `tool_calls` | Idempotency gate — pending → running → succeeded/failed |
| `sagas` | One row per booking; `state` JSONB accumulates step results; `current_step` INT tracks position |
| `saga_steps` | One row per step execution; `direction` (forward/backward for compensation) |
| `flights` | Pre-seeded flight inventory |
| `seat_holds` | Active holds: `released_at IS NULL AND expires_at > now()` = active |
| `bookings` | Confirmed bookings with payment auth/charge IDs |
| `workshop_chaos` | Kill-switch: `is_dead = TRUE` causes worker to return 503 |

**Saga step lifecycle:**
```
hold_seat → authorize_payment → confirm_booking
    ↓              ↓                  ↓
release_seat  void_authorization  cancel_booking
(compensate)     (compensate)       (compensate)
```

**Idempotency key format:**
```
{saga_id}:{step_name}
```
Same key = same saga step. On conflict: check status, return cached result if succeeded.

**What gets built:**
- `src/db/saga_store.py` — saga CRUD, step tracking
- `src/db/tool_call_store.py` — 4-state gate (pending/running/succeeded/failed)
- `src/db/conversation_store.py` — message persistence
- `src/booking/saga.py` — SagaOrchestrator that drives steps and handles resume
- `src/agent/tools.py` — hold_seat, authorize_payment, confirm_booking handlers
- CLI: `python -m src.scripts.run_agent --region us-west-2 --input "find me a flight to JFK"`

---

## Module 3 — Resume Operations from Another Region

**What it teaches:**
- The chaos flag (`workshop_chaos.is_dead`) simulates a regional outage without killing infrastructure
- When a worker returns 503, the UI routes the same saga_id to the peer region
- The peer reads `sagas.state` JSONB + `saga_steps` to find exactly where the failed region stopped
- Completed steps are skipped; the saga continues from the first incomplete step
- `sagas.last_touched_region` tracks which region last worked on the saga

**What gets built:**
- `src/api/server.py` — FastAPI dual-region worker
- `src/db/chaos_store.py` — read/write `workshop_chaos.is_dead`
- Web UI at `http://localhost:8080` — rich SPA with:
  - Live region health indicators (polls `/health` every 3s)
  - Booking form with crash injection selector
  - Real-time saga step progress (hold → authorize → confirm)
  - Chaos kill/restore buttons per region
  - Auto-failover: 503 from primary → retries on peer with same saga_id
  - DB verify SQL auto-generated for each saga

---

## The Four Demo Scenarios

### Demo 1 — Crash Mid-Saga (`demos/demo_1_crash.py`)

**What it proves:** saga state survives process death

```
Run 1:  CRASH_AFTER_STEP=hold_seat
        Agent runs: search → hold_seat → CRASH
        DB state: sagas.current_step=1, saga_steps has 1 completed row

Run 2:  CRASH_AFTER_STEP= (blank)
        Agent runs: [hold_seat SKIPPED] → authorize_payment → confirm_booking
        DB state: sagas.status='completed', 3 saga_steps rows
```

Verify: `SELECT step_name, status FROM saga_steps WHERE saga_id='...' ORDER BY step_index;`
Expected: 3 rows, all status='completed', no duplicate hold

---

### Demo 2 — Region Failover (`demos/demo_2_region_failover.py`)

**What it proves:** any region can resume any saga

```
Step 1: Run booking in us-west-2, crash after hold_seat
Step 2: us-west-2 agent disabled (or dead)
Step 3: Resume same saga_id on us-east-1

us-east-1 reads sagas.state from DSQL (same data, active-active)
Resumes from authorize_payment — no re-hold, no double-charge
sagas.last_touched_region changes from us-west-2 → us-east-1
```

---

### Demo 3 — Duplicate Requests (`demos/demo_3_duplicate.py`)

**What it proves:** idempotency prevents double-charges

```
Two threads fire run_booking() with the same saga_id simultaneously.
Both reach authorize_payment.
First writer: INSERT tool_calls (pending) → commit → execute → succeeded
Second writer: INSERT ON CONFLICT DO NOTHING → finds status=succeeded → returns cached result

Result: one booking row, one payment_auth_id, both threads return identical result
```

Verify: `SELECT COUNT(*) FROM tool_calls WHERE conversation_id='...'` → 3 rows, not 6

---

### Demo 4 — OCC Seat Race (`demos/demo_4_occ_race.py`)

**What it proves:** DSQL OCC prevents double-seat-booking without locks

```
Setup: AA100 flight reset to exactly 1 available seat

Agent X and Agent Y both:
  1. SELECT COUNT(*) FROM seat_holds WHERE flight_id=... (reads availability)
  2. INSERT INTO seat_holds (tries to hold the seat)

DSQL detects overlapping read-sets across concurrent transactions.
One commit wins. The other gets SerializationFailure → raises SeatConflict.
```

No `SELECT FOR UPDATE`. No advisory locks. Pure OCC.

Verify: `SELECT COUNT(*) FROM seat_holds WHERE released_at IS NULL AND expires_at > now()` → exactly 1

---

## API Endpoints (FastAPI Worker)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Web UI (SPA) |
| GET | `/health` | 200 if healthy, 503 if chaos flag set |
| POST | `/chat` | One-turn agent conversation (search only) |
| POST | `/book` | Full saga: search → hold → authorize → confirm |
| GET | `/saga/{saga_id}` | Inspect saga state + completed steps |
| GET | `/chaos` | List `is_dead` state for all regions |
| POST | `/chaos/disable` | Set `is_dead=TRUE` for a region |
| POST | `/chaos/enable` | Set `is_dead=FALSE` for a region |
| GET | `/docs` | FastAPI auto-generated Swagger UI |

### `/book` request body
```json
{
  "user_id": "Alice Workshop",
  "origin": "SEA",
  "destination": "JFK",
  "date": "2026-08-01",
  "saga_id": "<uuid-or-blank>",
  "crash_after_step": "hold_seat"
}
```
Supply the same `saga_id` on retry to resume rather than restart.

### `/saga/{id}` response
```json
{
  "saga": {
    "saga_id": "...",
    "status": "in_progress | completed | failed",
    "current_step": 1,
    "state": { "flight_id": "...", "hold_seat": {...}, "authorize_payment": {...} },
    "last_touched_region": "us-west-2"
  },
  "completed_steps": ["hold_seat", "authorize_payment"]
}
```

---

## Pre-Seeded Workshop Data

### Flights
| flight_code | route | flight_id (UUID) |
|---|---|---|
| AA100 | SEA → JFK | `11111111-1111-1111-1111-111111111111` |
| AA200 | SEA → LHR | `22222222-2222-2222-2222-222222222222` |
| AA300 | SFO → NRT | `33333333-3333-3333-3333-333333333333` |

### Chaos rows
```sql
INSERT INTO workshop_chaos (region, is_dead) VALUES
  ('us-west-2', FALSE),
  ('us-east-1', FALSE);
```

---

## Local Setup

### Prerequisites
```
pip install strands-agents boto3 psycopg[binary] python-dotenv fastapi "uvicorn[standard]"
```

### Environment (`.env`)
```
DSQL_ENDPOINT_A=<us-west-2 cluster endpoint>
DSQL_ENDPOINT_B=<us-east-1 cluster endpoint>
REGION_A=us-west-2
REGION_B=us-east-1
AWS_DEFAULT_REGION=us-west-2
BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001:0
WORKER_REGION=us-west-2
PEER_URL=http://localhost:8081
PEER_REGION=us-east-1
```

### Start both workers
```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts\start_workers.ps1

# Bash
bash scripts/start_workers.sh
```

### CLI (Lab 2.2 exact command)
```bash
python -m src.scripts.run_agent --region us-west-2 --input "find me a flight to JFK"
# Output: {"conversation_id": "<uuid>", "answer": "Top match: AA100 (SEA→JFK) departing ..."}
```

---

## Key Technical Concepts (Conference Level 300)

| Concept | How it's shown |
|---|---|
| Aurora DSQL active-active | Both workers write to the same cluster; reads on either region are consistent |
| OCC (earliest-commit-wins) | Demo 4: two agents race, DSQL picks one, the other gets SerializationFailure |
| Saga with compensation | Failed sagas run backward: cancel_booking → void_authorization → release_seat |
| Atomic idempotency | One transaction: INSERT pending + domain write + UPDATE succeeded |
| Chaos flag (not process kill) | `UPDATE workshop_chaos SET is_dead=TRUE` — no infra change, pure application-level gate |
| Cross-region resume | `sagas.state` JSONB is the single source of truth; any region reads and continues |
| Strands Agents SDK | `@tool` decorator wires Python functions to Bedrock Claude tool calls |
| psycopg3 + IAM auth | `generate_db_connect_admin_auth_token()` → password field in conninfo |
