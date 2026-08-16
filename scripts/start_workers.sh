#!/usr/bin/env bash
# Start both regional FastAPI workers for the local ABT demo.
#
# Worker A: us-west-2  → http://localhost:8080
# Worker B: us-east-1  → http://localhost:8081
#
# Open http://localhost:8080 after both workers are up.

set -e
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in your DSQL endpoints."
  exit 1
fi

# Load .env into current shell
set -a; source .env; set +a

PY="${PYTHON:-python}"
command -v "$PY" &>/dev/null || PY="python3"
command -v "$PY" &>/dev/null || { echo "ERROR: python not found"; exit 1; }

echo "=== ACME Booking Travel — Starting dual-region workers ==="
echo ""

cleanup() {
  echo ""
  echo "Stopping workers..."
  kill "$PID_A" "$PID_B" 2>/dev/null
  wait "$PID_A" "$PID_B" 2>/dev/null
  echo "Done."
}
trap cleanup EXIT INT TERM

# Worker A — us-west-2 on port 8080
echo "Starting Worker A (us-west-2) on http://localhost:8080 ..."
WORKER_REGION=us-west-2 \
DSQL_ENDPOINT="$DSQL_ENDPOINT_A" \
PEER_URL=http://localhost:8081 \
PEER_REGION=us-east-1 \
"$PY" -m uvicorn src.api.server:app \
  --host 0.0.0.0 --port 8080 \
  --log-level warning \
  --no-access-log \
  > /tmp/worker_a.log 2>&1 &
PID_A=$!

# Worker B — us-east-1 on port 8081
echo "Starting Worker B (us-east-1) on http://localhost:8081 ..."
WORKER_REGION=us-east-1 \
DSQL_ENDPOINT="$DSQL_ENDPOINT_B" \
PEER_URL=http://localhost:8080 \
PEER_REGION=us-west-2 \
"$PY" -m uvicorn src.api.server:app \
  --host 0.0.0.0 --port 8081 \
  --log-level warning \
  --no-access-log \
  > /tmp/worker_b.log 2>&1 &
PID_B=$!

# Wait for both to be ready
echo ""
echo "Waiting for workers to start..."
for i in $(seq 1 15); do
  sleep 1
  A_OK=0; B_OK=0
  curl -sf http://localhost:8080/health > /dev/null 2>&1 && A_OK=1
  curl -sf http://localhost:8081/health > /dev/null 2>&1 && B_OK=1
  if [ $A_OK -eq 1 ] && [ $B_OK -eq 1 ]; then
    echo ""
    echo "Both workers are healthy!"
    break
  fi
  printf "."
done

echo ""
echo "============================================"
echo "  Worker A (us-west-2):  http://localhost:8080"
echo "  Worker B (us-east-1):  http://localhost:8081"
echo ""
echo "  Open either URL in your browser."
echo "  Press Ctrl+C to stop both workers."
echo "============================================"
echo ""

# Tail both logs to terminal
tail -f /tmp/worker_a.log /tmp/worker_b.log &
TAIL_PID=$!

wait "$PID_A" "$PID_B"
kill "$TAIL_PID" 2>/dev/null
