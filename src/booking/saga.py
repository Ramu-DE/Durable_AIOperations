"""
SagaOrchestrator — adapted for official workshop schema.

State lives in sagas.state JSONB. Steps are recorded in saga_steps with
step_index and direction (forward/backward for compensation).
"""
from __future__ import annotations

import psycopg

from src.booking.models import BookingRequest, STEP_NAMES, COMPENSATION_MAP
from src.db import saga_store, tool_call_store


class SagaOrchestrator:
    def __init__(
        self,
        conn: psycopg.Connection,
        step_handlers: dict[str, callable],
        compensation_handlers: dict[str, callable],
        region: str = "",
        crash_injector=None,
    ):
        self.conn = conn
        self.step_handlers = step_handlers
        self.compensation_handlers = compensation_handlers
        self.region = region
        self.crash_injector = crash_injector

    def run(self, saga_id: str, request: BookingRequest, initial_state: dict | None = None) -> dict:
        saga_store.create_saga(self.conn, saga_id, request.conversation_id, request.to_dict(), self.region)
        saga = saga_store.get_saga(self.conn, saga_id)
        state: dict = saga.get("state", {}) or {}

        # Merge any initial state (e.g. search results passed in)
        if initial_state:
            state.update(initial_state)

        completed_names = saga_store.get_completed_step_names(self.conn, saga_id)
        completed_set = set(completed_names)

        print(f"\n[saga] {'Resuming' if completed_set else 'Starting'} saga {saga_id}")
        if completed_set:
            print(f"[saga] Completed steps: {completed_names}")

        saga_store.touch_saga(self.conn, saga_id, self.region)
        completed_steps: list[str] = list(completed_names)

        try:
            for idx, step_name in enumerate(STEP_NAMES):
                if step_name in completed_set:
                    print(f"[saga] {step_name}: skip")
                    continue

                result = self._execute_step(saga_id, idx, step_name, request, state)
                state[step_name] = result
                completed_steps.append(step_name)
                saga_store.update_state(self.conn, saga_id, state, idx + 1)

                if self.crash_injector:
                    self.crash_injector.maybe_crash(step_name)

        except Exception as exc:
            print(f"\n[saga] Failed: {exc}")
            print(f"[saga] Compensating: {completed_steps[::-1]}")
            self._compensate(saga_id, completed_steps, state)
            saga_store.fail_saga(self.conn, saga_id)
            raise

        saga_store.complete_saga(self.conn, saga_id)
        print(f"[saga] Saga {saga_id} completed\n")
        return state

    def _execute_step(
        self,
        saga_id: str,
        idx: int,
        step_name: str,
        request: BookingRequest,
        state: dict,
    ) -> dict:
        print(f"[saga] {step_name}: executing (step {idx})")
        idem_key = f"{saga_id}:{step_name}"

        cached = tool_call_store.get_result(self.conn, idem_key)
        if cached is not None:
            print(f"[saga] {step_name}: idempotency hit")
            saga_store.add_step(self.conn, saga_id, idx, step_name, direction="forward")
            saga_store.complete_step(self.conn, _get_step_id(self.conn, saga_id, step_name))
            return cached

        first = tool_call_store.begin_call(
            self.conn, idem_key, step_name, {},
            conversation_id=request.conversation_id, seq=idx,
        )
        if not first:
            cached = tool_call_store.get_result(self.conn, idem_key)
            if cached:
                return cached
            raise RuntimeError(f"tool_call {idem_key!r} is running concurrently")

        result = self.step_handlers[step_name](self.conn, saga_id, request, state)
        tool_call_store.complete_call(self.conn, idem_key, result)
        self.conn.commit()

        step_id = saga_store.add_step(self.conn, saga_id, idx, step_name)
        saga_store.complete_step(self.conn, step_id)
        print(f"[saga] {step_name}: committed — {result}")
        return result

    def _compensate(self, saga_id: str, completed_steps: list[str], state: dict) -> None:
        for step_name in reversed(completed_steps):
            comp_name = COMPENSATION_MAP.get(step_name)
            if not comp_name or comp_name not in self.compensation_handlers:
                continue
            try:
                print(f"[saga] compensate: {comp_name}")
                self.compensation_handlers[comp_name](self.conn, saga_id, state)
                saga_store.add_step(self.conn, saga_id, 999, step_name, direction="backward")
            except Exception as e:
                print(f"[saga] {comp_name}: compensation failed — {e}")


def _get_step_id(conn: psycopg.Connection, saga_id: str, step_name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT step_id FROM saga_steps WHERE saga_id=%s::uuid AND step_name=%s AND direction='forward' ORDER BY created_at DESC LIMIT 1",
            (saga_id, step_name),
        )
        row = cur.fetchone()
    return str(row[0]) if row else ""
