# Aranye API

Production-oriented FastAPI backend for the Aranye customer, shopkeeper, and administrator applications.

For the complete architecture, API workflows, current implementation status, paid-service costs, alternatives, and production checklist, read the [Backend Handbook](docs/BACKEND_HANDBOOK.md).

## Local development

1. Copy `.env.development.example` to `.env` and replace development secrets.
2. Start PostgreSQL, Redis, and MinIO with `docker compose up -d`.
3. Install dependencies with `uv sync --dev`.
4. Apply migrations with `uv run alembic upgrade head`.
5. Seed the idempotent, full-volume demo marketplace with `uv run python scripts/seed_demo_data.py`.
6. Seed an administrator with `uv run python scripts/seed_admin.py admin@example.com 'a-strong-password'`.
7. Start the API with `uv run fastapi dev app/main.py`.

Interactive API documentation is available at `/docs` in development. Health and dependency readiness are exposed at `/health` and `/ready`.

## Architecture

- `app/api`: versioned HTTP contracts and authorization dependencies.
- `app/models`: PostgreSQL persistence models.
- `app/schemas`: validated request/response contracts.
- `app/services`: transactional business rules and provider orchestration.
- `alembic`: additive database migrations.

All monetary values are integer paise, all database timestamps are UTC, and payment state is finalized only from signature-verified Razorpay webhooks.

## Environment and demo-data policy

Use `ARANYE_ENV_FILE` to select a configuration file without renaming it, for example:

```bash
ARANYE_ENV_FILE=.env.staging uv run alembic upgrade head
ARANYE_ENV_FILE=.env.staging uv run python scripts/seed_demo_data.py
```

- Development, preview, and staging may set `DEMO_DATA_ENABLED=true` and run the idempotent demo seed command after migrations.
- Production must set `DEMO_DATA_ENABLED=false`; configuration validation refuses to start or seed when it is enabled.
- Every environment must use a separate PostgreSQL database, Redis namespace/service, JWT secret, and public base URL.
- Demo images are served from `/static/demo`; set `PUBLIC_BASE_URL` to the externally reachable API origin before seeding.
- The dense seed creates 20 categories, 20 shops, 20 products per shop, 20 campaigns/promotions, and enriches every customer with 15–20 private records.
- Validate collection coverage at any time with `uv run python scripts/audit_demo_data.py`.
- Never commit real `.env` files. Commit only the provided `.example` templates and store deployed secrets in the hosting platform's secret manager.
## Scratch-card worker

Apply migrations before publishing scratch cards:

```bash
uv run alembic upgrade head
```

Audience distribution and lifecycle maintenance run outside API requests:

```bash
uv run aranye-scratch-worker
```

Run exactly one or more worker replicas alongside the API. Jobs are claimed with
PostgreSQL `FOR UPDATE SKIP LOCKED`, so replicas can process different jobs safely.

Scratch-card publication requires all four local services:

```bash
# Terminal 1
docker compose up postgres redis minio

# Terminal 2
uv run alembic upgrade head
uv run fastapi dev app/main.py

# Terminal 3
uv run aranye-scratch-worker

# Terminal 4 (from ../admin)
npm run dev
```

`GET /ready` returns `503 database_schema_outdated` until PostgreSQL is at the
expected Alembic revision. A card can be saved as a draft without the worker, but
publication remains pending until a scratch-card worker is running.
