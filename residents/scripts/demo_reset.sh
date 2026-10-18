#!/bin/bash
# A fresh demo run per judge: in place in a few seconds when the backend is up (POST /dev/fresh), else (~60 s) stop it,
# forget every player, start again with calls on, and EMBER
# calls one team phone (DEMO_PHONES in residents/.env) right away, placed on a flood-zone corner; the judge can then call
# (346) 566-0512 to join. Then reload localhost:43123/?live.
#   residents/scripts/demo_reset.sh                 call our phone
#   residents/scripts/demo_reset.sh 6175551234      call the judge first (earliest flood deadline), then ours
#   residents/scripts/demo_reset.sh --none          call nobody
# At most 3 calls at once; the rest wait for a free line. Calls ride the Photon number either way; PHOTON_ENABLED=0 (default
# here) keeps players off Photon's 25 iMessage seats, which a wiped database can't release. Log: /tmp/ember-demo.log
cd "$(dirname "$0")/.." || exit 1
if [ $# -eq 0 ] && curl -sf -m 5 -X POST localhost:8000/dev/fresh > /dev/null; then  # running: reset in place, seconds
    echo "Fresh run: no players, clock 0:00, calling our phone. Reload localhost:43123/?live."
    exit 0
fi
DB=/tmp/ember-demo.db
CORNERS=("Flagg St and Memorial Dr" "Akron St and Banks St" "Ballord Pl and Putnam Ave" "Banks St and Elmer St"
         "Putnam Ave and Western Ave")
if [ "$1" = "--none" ]; then phones=(); else phones=("$@" $(sed -n 's/^DEMO_PHONES=//p' .env | tr ',' ' ')); fi
callers=()
for i in "${!phones[@]}"; do callers+=(--caller "${phones[$i]}=${CORNERS[$((i % ${#CORNERS[@]}))]}"); done
pkill -INT -f "bin/ember-drill" && while pgrep -f "bin/ember-drill" >/dev/null; do sleep 1; done
until python3 -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 8000)); s.close()" 2>/dev/null; do sleep 1; done
rm -f "$DB" "$DB-shm" "$DB-wal"
# detached, with stdin held open: closing this window must not stop the backend (an EOF would quit its console)
PHOTON_ENABLED="${PHOTON_ENABLED:-0}" EXTRACT_ENABLED=1 VOICE_MAX_CONCURRENT=3 MAX_PLAYERS=25 \
    nohup bash -c 'tail -f /dev/null | exec uv run ember-drill "$@"' _ --voice --crowded "${callers[@]}" --db "$DB" \
    > /tmp/ember-demo.log 2>&1 < /dev/null &
disown
until grep -qE "residents can call|isn't reachable|rror" /tmp/ember-demo.log 2>/dev/null; do sleep 1; done
grep -E "residents can call|isn't reachable|rror" /tmp/ember-demo.log | tail -1
echo "Fresh run: calling ${#phones[@]} phone(s). Reload localhost:43123/?live."
