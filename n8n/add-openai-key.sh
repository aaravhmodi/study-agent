#!/usr/bin/env bash
# Run on the server, once: save the OpenAI API key the home server assistant uses in n8n.
#   bash ~/projects/study-agent/n8n/add-openai-key.sh              # asks for the key
#   bash ~/projects/study-agent/n8n/add-openai-key.sh FILE NAME    # reads NAME=... from an env file
# n8n encrypts it with N8N_ENCRYPTION_KEY. The key is never printed and never put in a
# workflow file. Run it again to replace the key.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)

if [ $# -eq 2 ]; then
  key=$(grep -E "^$2=" "$1" | head -1 | cut -d= -f2- | tr -d "\"'\r ")
else
  read -rsp "OpenAI API key: " key
  echo
fi
[ -n "$key" ] || { echo "No key found, so nothing was saved."; exit 1; }

file=$(mktemp)
trap 'rm -f "$file"' EXIT
# The credential's id and name come from the workflow, so the two always match.
KEY="$key" python3 - "$here/workflows/assistant.json" > "$file" <<'PY'
import json
import os
import sys

flow = json.load(open(sys.argv[1], encoding="utf-8"))
(saved,) = [n["credentials"]["openAiApi"] for n in flow["nodes"] if "credentials" in n]
print(json.dumps([{**saved, "type": "openAiApi", "data": {"apiKey": os.environ["KEY"]}}]))
PY

cd ~/homelab/n8n
docker compose exec -T n8n sh -c 'umask 077; cat > /tmp/openai-key.json' < "$file"
docker compose exec -T n8n sh -c \
  'n8n import:credentials --input=/tmp/openai-key.json; status=$?; rm -f /tmp/openai-key.json; exit $status'
echo "Saved. The assistant can answer now."
