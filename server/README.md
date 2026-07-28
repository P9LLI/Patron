# PATRON v14.1 Secure Actions (FastAPI)

## What this provides
- `/validateSubscription` validates access and returns only coded operational fields for Split-Knowledge mode.
- Stripe-backed registration and subscription validation.
- SQLite logging, abuse detection and blocklist support.
- A public-safe Python runtime for GPT usage without exposing the original engine.

## Security model
- The server must never return algorithm parts, prompt fragments, MCTS trees, organized weights or proprietary formulas.
- The Custom GPT receives only `status`, `cfg`, `sk` and access-control metadata.
- The GPT must use `mcts_engine_public_safe.py` as its attached runtime surface.
- Keep the original engine private and out of the public GPT file set.
- Keep the repository private if `server/main.py` is considered proprietary in your environment.

## Run locally
```bash
pip install -r server/requirements.txt
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment variables
- `RATE_LIMIT_WINDOW_SECONDS` (default: 3600)
- `RATE_LIMIT_MAX_CALLS` (default: 10)
- `DB_PATH` (default: `server/server_data.db`)
- `LOG_FULL_MESSAGE` (default: false)
- `STRIPE_SECRET_KEY`
- `STRIPE_API_VERSION`
- `ALLOWED_SUBSCRIPTION_STATUSES`
- `STRIPE_WEBHOOK_SECRET`
- `PUBLIC_BASE_URL`
- `BILLING_MODE`
- `REGISTRATION_BACKEND`

## Custom GPT setup
1. Activate Code Interpreter in the GPT.
2. Attach `patron/runtime_public/mcts_engine_public_safe.py` as a GPT file.
3. Replace the GPT instructions with `server/gpt_instructions_v14_partA.txt`.
4. Replace the Action schema with `server/openapi.yaml`.
5. Test with a fresh chat, sending e-mail + OAB/estado before the legal query.

## Anonymous v14.2 Split-Knowledge setup
1. Activate Code Interpreter and attach `patron/runtime_public/patron_runtime.py`.
2. Paste `server/gpt_instructions_v14_2_anonymous_split_knowledge.txt` into the GPT instructions.
3. Replace the GPT Action schema with `server/openapi_runtime_mode.yaml`.
4. Keep Action authentication as `None`; the action neither requires nor accepts OAB, e-mail, CPF or registration data.
5. Do not expose the legacy `openapi.yaml` in this GPT: it includes subscription and administrative operations.
6. Test a new legal chat without any personal data.

## Registration-only mode
1. Set `BILLING_MODE=registration_only`.
2. Set `REGISTRATION_BACKEND=stripe` if you want registration persisted in Stripe customers.
3. Ensure `PUBLIC_BASE_URL` points to your Render URL.
4. Users who are not registered will receive the `/register` link.
