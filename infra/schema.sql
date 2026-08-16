-- Aurora DSQL schema — Agents That Don't Forget
-- Reference copy of the ACTUAL workshop schema (pre-provisioned via CloudFormation)
--
-- This file is for documentation and re-apply. The workshop cluster already
-- has all tables. Running this against a fresh cluster will recreate them.
--
-- IMPORTANT: Aurora DSQL does NOT support foreign key constraints.
-- All PKs are client-generated UUIDs (no SERIAL / sequences).

-- ── Group 1: Agent state ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id  UUID PRIMARY KEY,
    user_id          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    message_id       UUID PRIMARY KEY,
    conversation_id  UUID NOT NULL,
    seq              BIGINT NOT NULL,
    role             TEXT NOT NULL,    -- user | assistant | tool
    content          JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, seq)
);

-- ── Group 2: Idempotency ──────────────────────────────────────────────────────
-- Full lifecycle: pending -> running -> succeeded | failed
-- idempotency_key = "{conversation_id}:{seq}:{tool_name}:{args_hash}"

CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id     UUID PRIMARY KEY,
    conversation_id  UUID NOT NULL,
    message_id       UUID,
    idempotency_key  TEXT NOT NULL,
    tool_name        TEXT NOT NULL,
    args             JSONB NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending | running | succeeded | failed
    result           JSONB,
    error            TEXT,
    attempts         INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    UNIQUE (idempotency_key)
);

-- ── Group 3: Saga coordination ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sagas (
    saga_id              UUID PRIMARY KEY,
    conversation_id      UUID NOT NULL,
    saga_type            TEXT NOT NULL DEFAULT 'flight_booking',
    status               TEXT NOT NULL DEFAULT 'in_progress',  -- in_progress | completed | failed
    current_step         INTEGER NOT NULL DEFAULT 0,
    state                JSONB NOT NULL DEFAULT '{}',   -- accumulated step results
    last_touched_region  TEXT,
    last_touched_at      TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- direction: forward (execute) | backward (compensate)
CREATE TABLE IF NOT EXISTS saga_steps (
    step_id      UUID PRIMARY KEY,
    saga_id      UUID NOT NULL,
    step_index   INTEGER NOT NULL,
    step_name    TEXT NOT NULL,     -- hold_seat | authorize_payment | confirm_booking
    direction    TEXT NOT NULL DEFAULT 'forward',  -- forward | backward
    tool_call_id UUID,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | completed | failed
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- ── Group 4: Domain ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS flights (
    flight_id    UUID PRIMARY KEY,
    flight_code  TEXT NOT NULL,
    origin       TEXT NOT NULL,
    destination  TEXT NOT NULL,
    departs_at   TIMESTAMPTZ NOT NULL,
    total_seats  INTEGER NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Active hold: released_at IS NULL AND expires_at > now()
CREATE TABLE IF NOT EXISTS seat_holds (
    hold_id          UUID PRIMARY KEY,
    flight_id        UUID NOT NULL,
    seat_number      TEXT NOT NULL,
    conversation_id  UUID NOT NULL,
    expires_at       TIMESTAMPTZ NOT NULL,
    released_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id        UUID PRIMARY KEY,
    conversation_id   UUID NOT NULL,
    saga_id           UUID NOT NULL,
    flight_id         UUID NOT NULL,
    seat_number       TEXT NOT NULL,
    payment_auth_id   TEXT,
    payment_charge_id TEXT,
    amount_cents      BIGINT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'authorized',  -- authorized | confirmed | void | cancelled
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Group 5: Workshop chaos control ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS workshop_chaos (
    region      TEXT PRIMARY KEY,
    is_dead     BOOLEAN NOT NULL DEFAULT FALSE,
    killed_at   TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO workshop_chaos (region, is_dead) VALUES
  ('us-east-1', FALSE),
  ('us-west-2', FALSE)
ON CONFLICT (region) DO NOTHING;
