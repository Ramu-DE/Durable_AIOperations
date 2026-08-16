"""
Agent loop — load history → ask planner → persist decision → execute → loop.

Every step is wrapped in a transaction against DSQL. The loop is resumable:
if the process crashes after persisting the planner's decision (seq N) but
before persisting the tool result (seq N+1), recovery re-runs from seq N,
finds the tool_call in 'succeeded' state via the idempotency key, and
returns the cached result without re-executing.

Two planner modes:
  use_mock=True  — deterministic mock planner (Lab 2.2, no Bedrock cost)
  use_mock=False — real LLM planner via Amazon Bedrock (Module 3)
"""
from __future__ import annotations

import json
import re
import uuid

import psycopg

from src.db import conversation_store
from src.tools.executor import execute


# ── Mock planner (Lab 2.2) ────────────────────────────────────────────────────

def _mock_plan(user_input: str, history: list[dict]) -> dict:
    """
    Deterministic planner for Lab 2.2. Recognises search requests and maps
    them to search_flights tool calls.  All other input gets a canned response.
    """
    text = user_input.lower()

    if any(kw in text for kw in ["flight", "fly", "find", "search", "travel"]):
        # Extract destination: "to JFK", "to LAX", etc.
        dest_match = re.search(r"\bto\s+([A-Z]{3})\b", user_input, re.IGNORECASE)
        origin_match = re.search(r"\bfrom\s+([A-Z]{3})\b", user_input, re.IGNORECASE)
        date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", user_input)

        return {
            "tool": "search_flights",
            "args": {
                "origin": origin_match.group(1).upper() if origin_match else "SEA",
                "destination": dest_match.group(1).upper() if dest_match else "JFK",
                "date": date_match.group(1) if date_match else "2026-08-01",
            },
        }

    return {"answer": "I can help you search for and book flights. Try: 'find me a flight to LAX'"}


# ── Real LLM planner (Module 3) ───────────────────────────────────────────────

def _llm_plan(user_input: str, history: list[dict], region: str) -> dict:
    """
    Invoke Claude Haiku 4.5 via Bedrock to decide the next action.
    Returns {"tool": ..., "args": {...}} or {"answer": "..."}.
    """
    import os
    from strands import Agent
    from strands.models import BedrockModel

    model = BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001:0"),
        region_name=region,
    )

    system = (
        "You are a flight booking assistant for ACME Booking Travel (ABT). "
        "You have one tool: search_flights(origin, destination, date). "
        "When the user asks to find or book a flight, call this tool. "
        'Respond ONLY with valid JSON: {"tool": "search_flights", "args": {...}} '
        'or {"answer": "<natural language answer>"}.'
    )

    history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
    prompt = f"{history_text}\nuser: {user_input}"

    agent = Agent(model=model, system_prompt=system)
    raw = str(agent(prompt)).strip()

    # Parse JSON from model output
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return {"answer": raw}


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_turn(
    conn: psycopg.Connection,
    conversation_id: str,
    user_id: str,
    user_input: str,
    region: str = "us-east-1",
    use_mock: bool = True,
) -> str:
    """
    Run one agent turn:
      1. Ensure conversation exists in DSQL
      2. Persist the user message
      3. Plan (mock or LLM)
      4. Persist the planner decision as an assistant message
      5. If plan is a tool call: execute via the Executor, persist result
      6. Produce and persist the final answer
      7. Return the answer string

    The whole turn is resumable: a crash at any step leaves DSQL in a state
    that allows the next process to continue from where this one stopped.
    """
    conversation_store.create_conversation(conn, conversation_id, user_id, region)
    history = conversation_store.get_messages(conn, conversation_id)

    # ── Persist user message ──────────────────────────────────────────────────
    user_seq = conversation_store.next_seq(conn, conversation_id)
    conversation_store.append_message(
        conn, str(uuid.uuid4()), conversation_id, user_seq, "user", user_input
    )

    # ── Plan ──────────────────────────────────────────────────────────────────
    plan = _mock_plan(user_input, history) if use_mock else _llm_plan(user_input, history, region)

    # ── Persist planner decision ──────────────────────────────────────────────
    plan_seq = conversation_store.next_seq(conn, conversation_id)
    plan_content = json.dumps(plan)
    conversation_store.append_message(
        conn, str(uuid.uuid4()), conversation_id, plan_seq, "assistant", plan_content
    )

    answer: str

    if "tool" in plan:
        # ── Execute tool (at-most-once) ───────────────────────────────────────
        tool_result = execute(
            conn,
            conversation_id=conversation_id,
            seq=plan_seq,
            tool_name=plan["tool"],
            args=plan["args"],
        )

        # ── Persist tool result ───────────────────────────────────────────────
        result_seq = conversation_store.next_seq(conn, conversation_id)
        conversation_store.append_message(
            conn, str(uuid.uuid4()), conversation_id, result_seq, "tool", json.dumps(tool_result)
        )

        # ── Synthesize final answer ───────────────────────────────────────────
        flights = tool_result.get("flights", [])
        if flights:
            top = flights[0]
            answer = (
                f"Top match: {top['flight_code']} ({top['origin']}→{top['destination']}) "
                f"departing {top['departs_at']}. {top['available_seats']} seat(s) available."
            )
        else:
            args = plan["args"]
            answer = f"No flights found from {args.get('origin','?')} to {args.get('destination','?')} on {args.get('date','?')}."

    else:
        answer = plan.get("answer", "Sorry, I could not understand that request.")

    # ── Persist final answer ──────────────────────────────────────────────────
    answer_seq = conversation_store.next_seq(conn, conversation_id)
    conversation_store.append_message(
        conn, str(uuid.uuid4()), conversation_id, answer_seq, "assistant", answer
    )

    return answer
