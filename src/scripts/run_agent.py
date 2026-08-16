"""
CLI runner for a single-turn agent interaction.

Usage (from workspace root):
    python -m src.scripts.run_agent --region us-east-1 --input "find me a flight to JFK"

    # Use real Bedrock LLM instead of the mock planner:
    python -m src.scripts.run_agent --region us-east-1 --input "..." --llm

    # Resume an existing conversation:
    python -m src.scripts.run_agent --conversation-id <uuid> --input "..." --region us-east-1

Output (JSON):
    {"conversation_id": "<uuid>", "answer": "Top match: ..."}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from src.db.dsql_client import get_connection
from src.db.chaos_store import is_region_disabled
from src.agent.loop import run_turn


def main():
    parser = argparse.ArgumentParser(description="Run one agent turn against Aurora DSQL")
    parser.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    parser.add_argument("--input", required=True, help="User message")
    parser.add_argument("--conversation-id", default=None, help="Resume existing conversation")
    parser.add_argument("--user-id", default="Workshop User")
    parser.add_argument("--llm", action="store_true", help="Use real Bedrock LLM instead of mock")
    args = parser.parse_args()

    # Select DSQL endpoint for this region
    region = args.region
    if region == os.environ.get("REGION_A", "us-east-1"):
        endpoint = os.environ.get("DSQL_ENDPOINT_A") or os.environ.get("DSQL_ENDPOINT")
    else:
        endpoint = os.environ.get("DSQL_ENDPOINT_B") or os.environ.get("DSQL_ENDPOINT_PEER")

    if not endpoint:
        print('{"error": "DSQL_ENDPOINT_A (or DSQL_ENDPOINT) not set"}', file=sys.stderr)
        sys.exit(1)

    conn = get_connection(endpoint)

    # Respect chaos flag — if this region is disabled, refuse
    if is_region_disabled(conn, region):
        conn.close()
        print(json.dumps({"error": f"Region {region} is disabled (chaos flag set)"}))
        sys.exit(1)

    conversation_id = args.conversation_id or str(uuid.uuid4())

    answer = run_turn(
        conn=conn,
        conversation_id=conversation_id,
        user_id=args.user_id,
        user_input=args.input,
        region=region,
        use_mock=not args.llm,
    )

    conn.close()
    print(json.dumps({"conversation_id": conversation_id, "answer": answer}, indent=2))


if __name__ == "__main__":
    main()
