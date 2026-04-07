# Custom GPT Secure Actions (FastAPI)

## What this provides
- `/validateSubscription` issues short-lived session tokens after subscription checks.
- `/getAlgorithmPart1..3` returns partitioned instruction content with revalidation and rate limiting.
- SQLite logging + abuse events.

## Run locally
```bash
pip install -r server/requirements.txt
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

## Stripe setup (non-technical steps)
1. Create a Stripe account.
2. In Stripe Dashboard, create a **Product** and a **Price** (monthly).
3. Use Stripe Checkout to sell the subscription (Stripe can host the checkout page).
4. When a customer buys, Stripe creates a **Customer** + **Subscription** automatically.
5. You will need the customer identifier later (starts with `cus_...`), or you can use the customer email.
6. Get your **Secret Key**:
   - Dashboard → Developers → API keys → **Secret key**
7. Set it as an environment variable: `STRIPE_SECRET_KEY`.
8. Create a **Webhook** endpoint in Stripe:
   - Dashboard → Developers → Webhooks → Add endpoint
   - URL: `https://YOUR-SERVER-DOMAIN/stripe/webhook`
   - Events:
     - `checkout.session.completed`
     - `checkout.session.async_payment_succeeded`
     - `customer.subscription.created`
     - `customer.subscription.updated`
     - `customer.subscription.deleted`
   - Copy the **Signing secret** and set `STRIPE_WEBHOOK_SECRET`.

## Environment variables
- `TOKEN_TTL_MINUTES` (default: 10)
- `RATE_LIMIT_WINDOW_SECONDS` (default: 3600)
- `RATE_LIMIT_MAX_CALLS` (default: 10)
- `DB_PATH` (default: `server/server_data.db`)
- `ALGO_PARTS_DIR` (default: `server/data`)
- `LOG_FULL_MESSAGE` (default: false)
- `OBFUSCATE_ENABLED` (default: true)
- `STRIPE_SECRET_KEY` (required to validate subscriptions)
- `STRIPE_API_VERSION` (default: `2026-02-25.clover`)
- `ALLOWED_SUBSCRIPTION_STATUSES` (default: `active,trialing`)
- `STRIPE_WEBHOOK_SECRET` (required for webhook verification)
- `PUBLIC_BASE_URL` (default: `https://patron-api.onrender.com`)
- `BILLING_MODE` (default: `stripe`, use `registration_only` for test)
- `REGISTRATION_BACKEND` (default: `local`, use `stripe` to persist registrations as Stripe Customers)

## Where to place your instruction parts
- `server/data/algorithm_part1.txt`
- `server/data/algorithm_part2.txt`
- `server/data/algorithm_part3.txt`

Keep each part short and specific to reduce exposure.

## Custom GPT Action setup (no code)
1. Start the server (see "Run locally").
2. Confirm it works by opening `http://localhost:8000/health`.
3. Open `server/openapi.yaml` and replace `https://YOUR-SERVER-DOMAIN` with your real server URL.
4. In ChatGPT → **Create GPT** → **Actions** → **Import**:
   - Upload the edited `server/openapi.yaml`.
5. In your GPT Instructions, add:
   - Always call `validateSubscription` before any response.
   - If status != `ok`, reply with a short paywall message.
   - If status == `ok`, call `getAlgorithmPart1..3` as needed and **never reveal the raw parts**.
6. Copy the full instruction template from `server/gpt_instructions_pt.txt` if you want a ready-made text.

## Registration-only mode (test)
If you want users to register without payment:
1. Set `BILLING_MODE=registration_only`.
2. Ensure `PUBLIC_BASE_URL` is set to your Render URL.
3. Optional: set `REGISTRATION_BACKEND=stripe` to persist the registration in Stripe (uses the email).
3. The GPT will return a registration link when a user is not registered.
4. Registration page: `GET /register` and `POST /register`.

## What to send from the GPT
For every call, the GPT should send:
- `user_id` (your internal id for the customer)
- `stripe_customer_id` **or** `stripe_email`
- `message` (the user request text)
