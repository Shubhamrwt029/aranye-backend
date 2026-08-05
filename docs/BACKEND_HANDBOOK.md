# Aranye Backend Handbook

Last reviewed: 15 July 2026

## Architecture

Aranye is a FastAPI application serving customer and shopkeeper mobile apps plus a Next.js administrator panel. The API prefix is `/api/v1`; development documentation is available at `/docs` and `/redoc`.

```text
Mobile apps / Admin panel
          │ HTTPS + JSON
          ▼
       FastAPI
       ├── PostgreSQL: durable application data
       ├── Redis: OTP cooldown and development OTP state
       ├── Twilio Verify: production OTP delivery and verification
       ├── Razorpay: online payments
       ├── FCM: push notifications (integration pending)
       └── S3/MinIO: media storage (integration pending)
```

## Authentication

Customer and shopkeeper identities share the `users` table and are separated by role. Admins use email/password authentication.

### OTP modes

- `SMS_PROVIDER=console`: local development mode. Aranye generates a six-digit OTP, stores it temporarily in Redis, and returns it as `debug_otp`.
- `SMS_PROVIDER=twilio`: Twilio Verify generates, sends, and validates the six-digit code. `debug_otp` is always `null`.

Send and resend return `202 Accepted` because delivery is asynchronous. With Twilio, `provider_request_id` is the verification SID beginning with `VE`. Verification returns tokens only when Twilio reports `status=approved`; Twilio documents `valid` as a legacy property.

Twilio errors are translated into API errors:

| Situation | HTTP status |
|---|---:|
| Invalid/expired code or invalid destination | 400 |
| Invalid Twilio credentials (backend/provider configuration) | 502 |
| Cooldown/provider limit | 429 |
| Invalid provider response | 502 |
| Provider timeout/unavailable | 503 |

Access tokens expire after 30 minutes by default. Refresh tokens use hashed, rotating database sessions and expire after seven days by default.

## API groups

### Customer Authentication

- `POST /api/v1/auth/customer/send-otp`
- `POST /api/v1/auth/customer/verify-otp`
- `POST /api/v1/auth/customer/resend-otp`

### Shopkeeper Authentication

- `POST /api/v1/auth/shopkeeper/send-otp`
- `POST /api/v1/auth/shopkeeper/verify-otp`
- `POST /api/v1/auth/shopkeeper/resend-otp`

### Shared Authentication

- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/profile/complete`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/logout-all`

### Customer APIs

- Shop and product discovery
- Saved delivery addresses
- Favorites
- Single-shop cart and idempotent checkout
- Delivery or customer pickup orders
- Order history
- Local reward campaigns and claims
- In-app notifications

### Shopkeeper APIs

- Shop onboarding, hours, bank details and availability
- Product and inventory management
- Order acceptance and fulfillment state changes
- Earnings summary
- Local reward campaigns

### Payment APIs

- Razorpay order/activation payment creation
- Signature-verified Razorpay webhook processing
- Cash on delivery support

### Admin APIs

- Dashboard metrics
- Shop approval/rejection
- User status management
- Catalog, orders, payments and rewards
- Notification composition
- Runtime settings and audit logs
- `GET /api/v1/admin/otp/status` for provider configuration status

## Twilio Verify setup

Create one Verify Service and configure:

- Friendly name: `Aranye Verify`
- Code length: `6`
- SMS channel: enabled
- Fraud Guard: enabled
- Default message templates during trial/development

Use the **Twilio Verify V2 API**, not the Programmable Messaging `messages.create` quickstart. Verify owns OTP generation, expiry, delivery, fraud checks, and code validation. A Twilio sender phone number is therefore not required for this integration.

Trial accounts can send only to recipient phone numbers verified in the Twilio Console.

Use exactly one complete credential pair:

- Local setup: `TWILIO_ACCOUNT_SID` (`AC...`) and `TWILIO_AUTH_TOKEN`.
- Production: `TWILIO_API_KEY` (`SK...`) and `TWILIO_API_KEY_SECRET`.

Both options also require `TWILIO_VERIFY_SERVICE_SID` (`VA...`). Prefer a restricted API key in production.

```dotenv
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_VERIFY_SERVICE_SID=
TWILIO_API_KEY=
TWILIO_API_KEY_SECRET=
TWILIO_TIMEOUT_SECONDS=10

OTP_LENGTH=6
OTP_EXPIRE_MINUTES=10
OTP_RESEND_COOLDOWN_SECONDS=60
OTP_MAX_ATTEMPTS=5
```

Never put Twilio secrets in mobile apps, browser code, `NEXT_PUBLIC_*` variables, Git, screenshots, logs, or documentation. Rotate any credential that has been exposed.

## Paid services

| Component | Cost model | Development alternative |
|---|---|---|
| Twilio Verify | Usage-based verification/SMS charges | `SMS_PROVIDER=console` |
| Razorpay | Transaction fee on successful online payments | COD and development provider IDs |
| PostgreSQL | Free software; managed hosting costs money | Local Docker PostgreSQL |
| Redis | Free software; managed hosting costs money | Local Docker Redis |
| S3-compatible storage | Storage/request/egress charges | Local MinIO |
| FCM | Cloud Messaging itself is no-cost | In-app database notifications |
| Hosting/domain/monitoring | Provider-dependent | Local Docker/development server |

Check current provider pricing before launch because rates and taxes change.

## Local development

```bash
cd backend
docker compose up -d
uv sync --dev
uv run alembic upgrade head
uv run python scripts/seed_admin.py admin@example.com 'replace-with-a-strong-password'
uv run fastapi dev app/main.py
```

For no-cost local OTP testing, set:

```dotenv
SMS_PROVIDER=console
```

Use the returned `debug_otp` with the verify endpoint.

## Quality checks

```bash
uv run ruff format --check app tests
uv run ruff check app tests
uv run pytest -q
```

## Production checklist

- Rotate exposed credentials and use a managed secret store.
- Use restricted Twilio API keys and enable Fraud Guard.
- Add API and edge rate limits for OTP endpoints.
- Upgrade Twilio from trial and test real supported destinations.
- Use HTTPS, explicit CORS origins, PostgreSQL TLS and managed Redis.
- Complete Razorpay webhook replay protection, refunds and reconciliation.
- Implement FCM delivery, presigned media uploads and background jobs.
- Add database integration, concurrency, authorization and end-to-end tests.
- Configure automated backups, restore drills, monitoring and alerting.
- Complete privacy, retention, account deletion, marketplace and tax policies.
