# AWS deployment

The decision model runs locally on the machine serving the backend (it
answers a question in ~115 ms on a consumer GPU, seconds on CPU), so the
smallest reliable AWS architecture is one compute target running the backend
plus a sidecar strands-decider server; no GPU infrastructure is required
unless latency demands it.

Draft target (to be finalized against the official rules, which publish
October 16, 2026):

- **Compute:** one ECS Fargate task running backend/app.py (uvicorn) and a
  sidecar `strands-decider serve ... --port 8099`. The model (~4.5 GB) is
  baked into the image (see Dockerfile), so the task needs 8 GB RAM /
  2 vCPU. App Runner caps at 4 GB, which will not hold the loaded model;
  Fargate is the smallest fit. CPU inference is acceptable for the demo's
  ~9 gate evaluations.
- **Agent LLM:** Amazon Bedrock (model id in .env), IAM task role, no
  long-lived keys on the machine.
- **Cost guardrail:** set an AWS Budgets alert before creating anything.
  Target is Rs 0 (promotional credits). A 2 vCPU / 8 GB Fargate task costs
  roughly Rs 8-9 per hour while running; stop the task when the demo is
  over and the bill stays inside credits. Fo creates no resource until
  Shlok has credentials connected and has said go.

## Exact steps (run after October 16 once the rules confirm the target)

1. **One-time setup**
   - AWS account, IAM user (or SSO) with permissions: ECR push, ECS, EC2
     networking, CloudWatch, Bedrock invoke.
   - Enable Bedrock model access for `Nova Pro` in us-east-1 (Bedrock
     console > Model access).
   - Install AWS CLI v2 and `aws configure`.
2. **Budget alarm first** (AWS Budgets > Create budget > cost budget,
   e.g. $5/month, alert at 50%).
3. **Build and push the image**
   ```
   aws ecr create-repository --repository-name gatekeeper
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
   docker build -t <account>.dkr.ecr.us-east-1.amazonaws.com/gatekeeper:latest .
   docker push <account>.dkr.ecr.us-east-1.amazonaws.com/gatekeeper:latest
   ```
4. **Run it** (Fargate, public IP so the app is reachable without a load
   balancer): cluster + task definition with 2 vCPU / 8192 MB, container
   port 8000, env from .env.example (never keys in env; attach an IAM task
   role with Bedrock invoke), security group allowing inbound 8000.
5. **Verify:** `curl http://<task-public-ip>:8000/health` returns
   `{"decider": true}`, then open http://<task-public-ip>:8000 for the UI.
6. **Tear down when done:** stop the task ( ECS console > update service >
   desired count 0) so nothing runs between demo sessions.

Nothing here is submitted until the official rules publish on October 16
and the submission requirements are verified against them.
