# Source from bash or zsh: source residents/scripts/requests.sh
# Override EMBER_API before sourcing to use another server.
export EMBER_API="${EMBER_API:-http://127.0.0.1:8000}"

ember_get() {
  curl -sS "$EMBER_API$1" | python3 -m json.tool
}

ember_post() {
  local endpoint="$1"
  local body="${2-}"
  if [[ -z "$body" ]]; then
    body='{}'
  fi
  curl -sS -X POST "$EMBER_API$endpoint" \
    -H 'Content-Type: application/json' \
    --data-raw "$body" | python3 -m json.tool
}
