#!/usr/bin/env bash
# Verify a deployed weather-mcp Databricks App.
#   export DATABRICKS_TOKEN=dapi...
#   ./verify_deployed.sh https://your-app.aws.databricksapps.com
set -uo pipefail

APP_URL="${1:-}"
if [[ -z "$APP_URL" || -z "${DATABRICKS_TOKEN:-}" ]]; then
  echo "usage: DATABRICKS_TOKEN=dapi... $0 https://<app-url>" >&2
  exit 2
fi
APP_URL="${APP_URL%/}"
MCP="$APP_URL/mcp"

call() {
  curl -sS -N --max-time 45 \
    -H "Authorization: Bearer $DATABRICKS_TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "$1" "$MCP"
}

echo "=== 1. tools/list ==="
LIST=$(call '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
echo "$LIST" | head -c 2000; echo
COUNT=$(echo "$LIST" | grep -o '"name"' | wc -l | tr -d ' ')
echo "--> tool-name occurrences: $COUNT (expect 7)"

echo
echo "=== 2. health_check ==="
call '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"health_check","arguments":{}}}' | head -c 1500
echo

echo
echo "=== 3. live tool call: current weather, Helsinki ==="
call '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_current_weather","arguments":{"location":"Helsinki"}}}' | head -c 1500
echo
