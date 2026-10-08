#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8000
