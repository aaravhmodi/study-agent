#!/usr/bin/env bash
# Run on the server after the workflow files change: load them into n8n and switch them on.
#   bash ~/projects/study-agent/n8n/install.sh
# Only these workflows are touched; anything you made in the n8n editor is left alone.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd ~/homelab/n8n
docker compose exec -T n8n n8n import:workflow --separate --input=/workflows
for file in "$here"/workflows/*.json; do
  id=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["id"])' "$file")
  docker compose exec -T n8n n8n publish:workflow --id="$id"
done
# n8n schedules published workflows when it starts.
docker compose restart n8n
