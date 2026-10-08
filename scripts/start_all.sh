#!/usr/bin/env bash
# Container entrypoint: serve Decider 2B, then the API + UI.
set -euo pipefail
cd "$(dirname "$0")/.."
strands-decider serve StrandsAgents/strands-decider-2B-hobson-v21 --device cpu --port 8099 &
bash scripts/seed_demo_data.sh
exec uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-8000}"
