#!/bin/sh
# A fresh demo between judge groups: stop the running backend, forget every player, start again with calls on (~60 s).
#   residents/scripts/demo_reset.sh            then reload localhost:43123/?live
# Calls ride the Photon number either way; PHOTON_ENABLED=0 (default here) keeps callers off Photon's 25 iMessage seats,
# which a wiped database can't release. Log: /tmp/ember-demo.log
cd "$(dirname "$0")/.." || exit 1
DB=/tmp/ember-demo.db
pkill -INT -f "ember-drill" && while pgrep -f "ember-drill" >/dev/null; do sleep 1; done
until python3 -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 8000)); s.close()" 2>/dev/null; do sleep 1; done
rm -f "$DB" "$DB-shm" "$DB-wal"
tail -f /dev/null | PHOTON_ENABLED="${PHOTON_ENABLED:-0}" EXTRACT_ENABLED=1 VOICE_MAX_CONCURRENT=3 MAX_PLAYERS=25 \
    nohup uv run ember-drill --voice --crowded --db "$DB" > /tmp/ember-demo.log 2>&1 &
until grep -qE "residents can call|isn't reachable|rror" /tmp/ember-demo.log 2>/dev/null; do sleep 1; done
grep -E "residents can call|isn't reachable|rror" /tmp/ember-demo.log | tail -1
curl -s -X POST localhost:8000/clock -H 'content-type: application/json' -d '{"t_s": 0}' > /dev/null
echo "Fresh demo at 0:00 with no players. Reload localhost:43123/?live."
