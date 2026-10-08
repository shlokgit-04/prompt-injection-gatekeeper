# AWS deployment

The decision model runs locally on the machine serving the backend (it
answers a question in ~115 ms on a consumer GPU, seconds on CPU), so the
smallest reliable AWS architecture is one compute target running the backend
plus a sidecar strands-decider server; no GPU infrastructure is required
unless latency demands it.

Draft target (to be finalized against the official rules, which publish
October 16, 2026):

- **Compute:** one AWS App Runner service (or ECS Fargate task) running
  backend/app.py (uvicorn) and a second process with
  `strands-decider serve ...`. The model (~4.5 GB) is baked into the image;
  CPU inference is acceptable for the demo's ~9 gate evaluations.
- **Agent LLM:** Amazon Bedrock (model id in .env), IAM role, no long-lived
  keys on the machine.
- **Cost:** one Fargate/App Runner CPU task is well inside AWS Promotional
  Credits / free-tier budgets. Budget alerts should be set before deployment.
- **Finalized once the official rules publish; nothing here is submitted
  until they are verified.**
