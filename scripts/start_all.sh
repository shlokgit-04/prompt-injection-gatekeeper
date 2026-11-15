#!/usr/bin/env bash
# Container entrypoint: optionally serve Decider 2B, then the API + UI.
# The Decider 2B needs far more RAM than the 512 MB free tier offers, so it is
# opt-in: set STRANDS_DECIDER_URL (e.g. http://127.0.0.1:8099) on a host with
# enough memory and the serve process starts; otherwise the app runs on its
# built-in signature fallback.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "${STRANDS_DECIDER_URL:-}" ]; then
  strands-decider serve StrandsAgents/strands-decider-2B-hobson-v21 --device cpu --port 8099 &
fi
bash scripts/seed_demo_data.sh
exec uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-8000}"
