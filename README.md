# HL Terminal (Hyperliquid read-only analysis dashboard)

分析用・投資助言ではない。Public data only, no trading, no keys required.

## Env vars (set as host secrets; never commit)
- `ACCESS_TOKEN` (required, >=16 chars). Open `https://<host>/?t=<ACCESS_TOKEN>` once; a 30-day HttpOnly cookie is set.
- `XAI_API_KEY` (optional). Grok rewrites the 考察 under a number guard; without it the rule-based text is used.
- `PORT` is provided by the host (default 8000).

## Run locally
    pip install -r requirements.txt
    ACCESS_TOKEN=... uvicorn app:app --port 8000

## Deploy on Render (free)
Push this folder to a GitHub repo, then open
`https://render.com/deploy?repo=https://github.com/<user>/<repo>` (uses render.yaml: Docker, free plan, Singapore).
Enter ACCESS_TOKEN (and optionally XAI_API_KEY) in the secret fields.

Unauthenticated endpoint: `/healthz` (returns only {"ok":true}).
