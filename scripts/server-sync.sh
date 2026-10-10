#!/usr/bin/env bash
# Refresh from LEARN on this computer and hand the result to the home server.
#
# LEARN is read through the Chrome you are signed in to, so syncing stays here. The
# server holds the live data: chats, notes and the assessments you marked done. This
# stops its dashboard, brings its database and index record back, syncs and indexes, sends the
# database, the changed course files and the index over, and starts it again.
#
# Run it from Git Bash:   bash scripts/server-sync.sh
# It needs STUDY_SERVER (user@host) in the environment or in .env.
set -euo pipefail
cd "$(dirname "$0")/.."

setting() { grep -m1 "^$1=" .env 2>/dev/null | cut -d= -f2- | tr -d '\r' || true; }
server="${STUDY_SERVER:-$(setting STUDY_SERVER)}"
remote="${STUDY_SERVER_DIR:-$(setting STUDY_SERVER_DIR)}"
remote="${remote:-projects/study-agent}"
[ -n "$server" ] || { echo "Set STUDY_SERVER=user@host in .env first." >&2; exit 1; }

on_server() { ssh -o BatchMode=yes "$server" "cd '$remote' && $1"; }

on_server "docker compose stop dashboard"
trap 'on_server "docker compose start dashboard"' EXIT

# The server's copies know what was marked done, and what it indexed itself, since
# the last sync here.
scp -q -o BatchMode=yes "$server:$remote/data/study_agent.db" data/study_agent.db
scp -q -o BatchMode=yes "$server:$remote/data/rag_manifest.json" data/rag_manifest.json

uv run study-agent sync
uv run study-agent rag-index

# Course files are large, so only the ones changed since the last run are sent.
cd data
newer=()
[ -f .sent-to-server ] && newer=(-newer .sent-to-server)
touch .sending
find downloads -type f "${newer[@]}" -print0 |
  tar --null -cf - study_agent.db rag_manifest.json -T - |
  ssh -o BatchMode=yes "$server" "tar -xf - -C '$remote/data'"
mv .sending .sent-to-server
echo "Sent to $server. The dashboard is starting again."
