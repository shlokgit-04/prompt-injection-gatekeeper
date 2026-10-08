#!/usr/bin/env bash
# Serves the reference Strands Decider 2B checkpoint locally.
# First run downloads the model (~4.5 GB) to the Hugging Face cache.
set -euo pipefail
pip install strands-decider strands-agents
strands-decider serve StrandsAgents/strands-decider-2B-hobson-v21 --port 8099
