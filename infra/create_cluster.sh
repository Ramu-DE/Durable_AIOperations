#!/usr/bin/env bash
# Module 1 — Provision a multi-region Aurora DSQL cluster
#
# Usage:
#   bash infra/create_cluster.sh
#
# Optional overrides:
#   PRIMARY_REGION=us-east-1 PEER_REGION=us-west-2 bash infra/create_cluster.sh
#
# What this does:
#   1. Creates a linked two-region DSQL cluster (active-active writers)
#   2. Polls until the cluster is ACTIVE
#   3. Generates an IAM auth token
#   4. Applies schema.sql and seed_flights.sql
#   5. Writes .env with both region endpoints

set -euo pipefail

PRIMARY_REGION="${PRIMARY_REGION:-us-east-1}"
PEER_REGION="${PEER_REGION:-us-west-2}"
WITNESS_REGION="${WITNESS_REGION:-us-east-2}"
ENV_FILE="${ENV_FILE:-.env}"

BOLD='\033[1m'; RESET='\033[0m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'

hr() { echo "────────────────────────────────────────────────────────────"; }

hr
echo -e "${BOLD}Module 1 — Aurora DSQL Multi-Region Setup${RESET}"
hr
echo ""
echo "  Primary region : $PRIMARY_REGION"
echo "  Peer region    : $PEER_REGION"
echo "  Witness region : $WITNESS_REGION  (quorum only — no reads/writes)"
echo ""

# ── Step 1: Create cluster ───────────────────────────────────────────────────
echo -e "${BOLD}Step 1/5  Creating linked cluster...${RESET}"

CLUSTER_JSON=$(aws dsql create-multi-region-cluster \
  --linked-region-list "$PRIMARY_REGION" "$PEER_REGION" \
  --witness-region "$WITNESS_REGION" \
  --region "$PRIMARY_REGION" \
  --output json)

CLUSTER_ARN=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('arn',''))")
echo "  ARN: $CLUSTER_ARN"

# Extract per-region cluster identifiers from the linked cluster list
PRIMARY_ID=$(echo "$CLUSTER_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for lc in data.get('linkedClusters', []):
    if lc.get('region') == '$PRIMARY_REGION':
        print(lc['identifier']); break
")

PEER_ID=$(echo "$CLUSTER_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for lc in data.get('linkedClusters', []):
    if lc.get('region') == '$PEER_REGION':
        print(lc['identifier']); break
")

if [[ -z "$PRIMARY_ID" || -z "$PEER_ID" ]]; then
  echo "ERROR: Could not parse cluster identifiers from response. Check AWS console."
  echo "$CLUSTER_JSON"
  exit 1
fi

PRIMARY_ENDPOINT="${PRIMARY_ID}.dsql.${PRIMARY_REGION}.on.aws"
PEER_ENDPOINT="${PEER_ID}.dsql.${PEER_REGION}.on.aws"

echo ""
echo "  Primary endpoint : $PRIMARY_ENDPOINT"
echo "  Peer endpoint    : $PEER_ENDPOINT"

# ── Step 2: Poll until ACTIVE ────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Step 2/5  Waiting for cluster to reach ACTIVE status...${RESET}"
echo "  (DSQL provisions in ~60-90s on first create)"

MAX_WAIT=180
ELAPSED=0
INTERVAL=10
while true; do
  STATUS=$(aws dsql get-cluster \
    --identifier "$PRIMARY_ID" \
    --region "$PRIMARY_REGION" \
    --query "status" --output text 2>/dev/null || echo "UNKNOWN")

  if [[ "$STATUS" == "ACTIVE" ]]; then
    echo -e "  ${GREEN}ACTIVE${RESET} after ${ELAPSED}s"
    break
  fi

  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    echo -e "  ${YELLOW}Timed out after ${MAX_WAIT}s (status: $STATUS). Proceeding anyway.${RESET}"
    break
  fi

  printf "  [%3ds] status=%s — retrying in %ds...\r" "$ELAPSED" "$STATUS" "$INTERVAL"
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

# ── Step 3: Write .env ───────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Step 3/5  Writing $ENV_FILE...${RESET}"

cat > "$ENV_FILE" <<EOF
# Aurora DSQL — Module 1
DSQL_ENDPOINT=$PRIMARY_ENDPOINT
DSQL_ENDPOINT_PEER=$PEER_ENDPOINT

# AWS / Bedrock
AWS_DEFAULT_REGION=$PRIMARY_REGION
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6-20251001-v2:0

# Chaos injection (leave blank for normal run)
CRASH_AFTER_STEP=
EOF

echo "  Written to $ENV_FILE"

# ── Step 4: Apply schema ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Step 4/5  Generating IAM auth token and applying schema...${RESET}"

TOKEN=$(python3 - "$PRIMARY_ENDPOINT" "$PRIMARY_REGION" <<'PYEOF'
import sys, boto3
endpoint, region = sys.argv[1], sys.argv[2]
client = boto3.client("dsql", region_name=region)
print(client.generate_db_connect_admin_auth_token(hostname=endpoint, region=region, expires_in=900))
PYEOF
)

PGPASSWORD="$TOKEN" psql \
  "host=$PRIMARY_ENDPOINT port=5432 dbname=postgres user=admin sslmode=require" \
  -v ON_ERROR_STOP=1 \
  -f infra/schema.sql \
  && echo "  schema.sql applied"

# ── Step 5: Seed data ────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Step 5/5  Seeding flight and seat data...${RESET}"

PGPASSWORD="$TOKEN" psql \
  "host=$PRIMARY_ENDPOINT port=5432 dbname=postgres user=admin sslmode=require" \
  -v ON_ERROR_STOP=1 \
  -f infra/seed_flights.sql \
  && echo "  seed_flights.sql applied"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
hr
echo -e "${GREEN}${BOLD}Module 1 complete.${RESET}"
hr
echo ""
echo "  Next: verify cross-region write visibility"
echo ""
echo "    source .env"
echo "    python infra/verify_cross_region.py"
echo ""
