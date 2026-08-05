# Hostinger VPS deployment

This deployment runs two fully isolated Aranye stacks on one VPS. Each stack has its own API,
PostgreSQL database, Redis data, worker, environment file, and Docker volumes.

## Public endpoints

Before a domain is connected:

- Staging API base: `http://200.141.6.228/api/staging`
- Staging health: `http://200.141.6.228/api/staging/health`
- Staging readiness: `http://200.141.6.228/api/staging/ready`
- Password-protected Swagger UI: `http://200.141.6.228/api/staging/docs`
- Password-protected ReDoc: `http://200.141.6.228/api/staging/redoc`
- Production API base after the domain and HTTPS are configured:
  `https://api.YOUR_DOMAIN/api/production`

Staging uses demo data and console OTP. Production never receives demo data. A real production
container must not be started over plain HTTP: application validation requires HTTPS, explicit
CORS origins, a strong JWT secret, and valid Twilio configuration.

## Important security rules

- Never commit `.env.staging` or `.env.production`.
- Never expose PostgreSQL (`5432`), Redis (`6379`), or the API container ports (`8100` and `8200`).
- Only Nginx exposes ports `80` and, after a domain is connected, `443`.
- `.dockerignore` prevents environment files and Git metadata from being copied into images.
- Do not seed demo data into production.

## 1. Verify access

Find the VPS IPv4 address and SSH port in Hostinger hPanel under **VPS -> Manage -> SSH access**.
Confirm that the hPanel firewall permits the SSH port from the administrator's current IP.

```bash
ssh root@VPS_IP
```

## 2. Install system packages

Hostinger's Ubuntu 24.04 Docker template already includes Docker and the Compose plugin. On the
server, install the remaining packages and enable basic protection:

```bash
apt update
apt upgrade -y
apt install -y git nginx fail2ban
systemctl enable --now nginx
systemctl enable --now fail2ban
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

## 3. Clone the private repository

Use a GitHub deploy key on the VPS, then clone:

```bash
mkdir -p /opt/aranye
git clone git@github.com:Shubhamrwt029/aranye-backend.git /opt/aranye/backend
cd /opt/aranye/backend
```

Do not copy a developer's personal private key to the VPS. Create a dedicated read-only GitHub
deploy key for this repository.

## 4. Create staging secrets

```bash
cd /opt/aranye/backend
cp deploy/staging.env.example .env.staging
openssl rand -hex 32
openssl rand -hex 32
nano .env.staging
chmod 600 .env.staging
```

Replace `VPS_IP` and every `CHANGE_ME` value. Use hexadecimal output for the database password so
the password is safe inside the database URL.

The documentation variables must remain separate from customer, shopkeeper, and administrator API
accounts:

```env
API_DOCS_ENABLED=true
API_DOCS_USERNAME=aranye-docs
API_DOCS_PASSWORD=GENERATE_A_SEPARATE_STRONG_PASSWORD
```

Swagger UI, ReDoc, and the raw OpenAPI schema all use HTTP Basic authentication. The API endpoints
shown inside Swagger continue to use their normal Bearer-token authorization through the
**Authorize** button. Until a domain and HTTPS are installed, documentation credentials travel over
plain HTTP; treat the IP-based documentation as staging-only and do not reuse this password.

## 5. Start, migrate, and seed staging

Every command must use the same Compose project name. This keeps its volumes isolated from
production.

```bash
cd /opt/aranye/backend
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml up -d postgres redis
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml run --rm api /app/.venv/bin/alembic upgrade head
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml run --rm api /app/.venv/bin/python -m scripts.seed_demo_data
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml up -d
```

## 6. Install IP-based Nginx routing

```bash
cp deploy/nginx-ip.conf /etc/nginx/sites-available/aranye-api
ln -s /etc/nginx/sites-available/aranye-api /etc/nginx/sites-enabled/aranye-api
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

Verify staging:

```bash
curl http://VPS_IP/api/staging/health
curl http://VPS_IP/api/staging/ready
curl -I http://VPS_IP/api/staging/docs
curl -u 'DOCS_USERNAME:DOCS_PASSWORD' http://VPS_IP/api/staging/openapi.json
```

## 7. Production prerequisites

Before production can start, obtain and configure:

1. A domain pointing to the VPS, such as `api.example.com`.
2. A Let's Encrypt certificate and Nginx HTTPS configuration.
3. Twilio Verify production credentials.
4. S3-compatible object storage for uploaded product and reel media.
5. Razorpay production credentials when online payments are enabled.
6. An off-server PostgreSQL backup destination.

Then create `.env.production` from `deploy/production.env.example`, migrate the separate database,
and start the production stack. Never run the demo seed command against this stack.

```bash
cp deploy/production.env.example .env.production
nano .env.production
chmod 600 .env.production
docker compose --env-file .env.production -p aranye-production \
  -f deploy/compose.vps.yml up -d postgres redis
docker compose --env-file .env.production -p aranye-production \
  -f deploy/compose.vps.yml run --rm api /app/.venv/bin/alembic upgrade head
docker compose --env-file .env.production -p aranye-production \
  -f deploy/compose.vps.yml up -d
```

## 8. Mobile application URLs

Development/staging build:

```env
API_BASE_URL=http://200.141.6.228/api/staging
API_TIMEOUT_MS=15000
ALLOW_INSECURE_LOCAL_API=false
```

Production build after HTTPS is active:

```env
API_BASE_URL=https://api.YOUR_DOMAIN/api/production
API_TIMEOUT_MS=15000
ALLOW_INSECURE_LOCAL_API=false
```

React Native configuration is embedded at build time, so rebuild the Android/iOS application after
changing the selected environment file. Until HTTPS is configured, use this staging URL only in a
debug/development mobile build; release builds intentionally reject insecure public HTTP APIs.

## 9. Updating a deployed stack

Take a database backup before applying migrations:

```bash
mkdir -p /opt/backups
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml exec -T postgres \
  pg_dump -U aranye_staging aranye_staging | \
  gzip > /opt/backups/aranye-staging-$(date +%Y%m%d-%H%M%S).sql.gz
```

Deploy an update:

```bash
git pull --ff-only
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml build api scratch-worker
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml run --rm api /app/.venv/bin/alembic upgrade head
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml up -d
curl http://VPS_IP/api/staging/ready
```

## 10. Diagnostics

```bash
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml ps
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml logs --tail=200 api
docker compose --env-file .env.staging -p aranye-staging \
  -f deploy/compose.vps.yml logs --tail=200 scratch-worker
nginx -t
journalctl -u nginx --since "30 minutes ago"
```
