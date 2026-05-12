# PATRON v14 Secure Actions (FastAPI)

## What this provides
- `/validateSubscription` validates access, issues a short-lived session token and returns only coded operational fields for Split-Knowledge mode.
- Stripe-backed registration and subscription validation.
- SQLite logging, abuse detection and blocklist support.

## Security model
- The server must never return algorithm parts, prompt fragments, MCTS trees, organized weights or proprietary formulas.
- The Custom GPT receives only `status`, `session_token`, `cfg`, `sk` and access-control metadata.
- The protected Python file stays attached to the GPT and is executed via Code Interpreter.
- Keep the repository private if `server/main.py` is considered proprietary in your environment.

## Run locally
```bash
pip install -r server/requirements.txt
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment variables
- `TOKEN_TTL_MINUTES` (default: 10)
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
2. Attach `mcts_engine_v2.py` as a GPT file.
3. Replace the GPT instructions with `server/gpt_instructions_v14_partA.txt`.
4. Replace the Action schema with `server/openapi.yaml`.
5. Test with a fresh chat, sending e-mail + OAB before the legal query.

## Registration-only mode
1. Set `BILLING_MODE=registration_only`.
2. Set `REGISTRATION_BACKEND=stripe` if you want registration persisted in Stripe customers.
3. Ensure `PUBLIC_BASE_URL` points to your Render URL.
4. Users who are not registered will receive the `/register` link.
