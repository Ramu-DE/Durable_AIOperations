#!/usr/bin/env bash
# Delete the DSQL cluster and clean up .env
# Usage: bash infra/teardown.sh
#
# Reads DSQL_ENDPOINT from .env to determine the cluster identifier.

set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Nothing to tear down."
  exit 1
fi

source "$ENV_FILE"

if [[ -z "${DSQL_ENDPOINT:-}" ]]; then
  echo "ERROR: DSQL_ENDPOINT not set in $ENV_FILE."
  exit 1
fi

# Extract identifier from endpoint hostname  <id>.dsql.<region>.on.aws
PRIMARY_ID=$(echo "$DSQL_ENDPOINT" | cut -d. -f1)
PRIMARY_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "==> Deleting DSQL cluster: $PRIMARY_ID (region: $PRIMARY_REGION)"
echo "    This will DELETE all data. Ctrl-C within 5s to abort."
sleep 5

aws dsql delete-multi-region-cluster \
  --identifier "$PRIMARY_ID" \
  --region "$PRIMARY_REGION" \
  --output json \
  && echo "==> Delete request submitted."

echo "==> Removing .env..."
rm -f "$ENV_FILE"

echo "==> Done."
