# Run Decider 2B on your laptop (one-time setup, ~30 min active)

Decider 2B is a ~4.5 GB checkpoint, so the gate needs a machine with real
RAM. Your workspace (~3 GiB) cannot load it; your laptop can.

## What you need

- 8+ GB RAM (5+ GB free while the server runs) and ~15 GB free disk
- Python 3.10+ and git; internet (the first run downloads the checkpoint)
- macOS or Linux native. On Windows, use WSL2 (`wsl --install`) and run
  everything inside it; the scripts are bash.

## Steps

1. Get the code:
   ```
   git clone https://github.com/shlokgit-04/prompt-injection-gatekeeper.git
   cd prompt-injection-gatekeeper
   ```
2. Start the decision model (installs `strands-decider`, downloads the
   checkpoint to the Hugging Face cache on first run, then serves it):
   ```
   ./scripts/run_decider.sh
   ```
   Wait for the server line; it listens on port 8099.
3. Check it is up (leave this window open):
   ```
   curl -s http://127.0.0.1:8099/health
   ```
4. Then one of:
   - **Run the live red-team suite yourself** (writes real measured numbers
     to docs/evaluation_results.json):
     ```
     pip install -r requirements-dev.txt
     STRANDS_DECIDER_URL=http://127.0.0.1:8099 pytest tests/redteam -v -s
     ```
   - **Or tunnel it so Fo can run the suite and commit the metrics:**
     ```
     npx cloudflared tunnel --url http://127.0.0.1:8099
     ```
     (or any quick tunnel you prefer) and send the printed URL to Fo with
     the text `decider is up`. The suite takes a few minutes.
5. Optional, the full demo UI (needs AWS credentials with Bedrock access):
   `cp .env.example .env`, fill in your region/model, then
   `./scripts/seed_demo_data.sh && ./scripts/run_backend.sh` and open
   http://localhost:8000.

## Troubleshooting

- Slow start: the first run downloads ~4.5 GB once; later starts load from
  the cache in seconds.
- "Address already in use": another process has 8099. Change the port in
  run_decider.sh and export `STRANDS_DECIDER_URL` with the new port.
- Machine swaps or the server is killed: close other apps; the model needs
  ~5 GB while loaded.
