# Nexora — Setup Guide

Nexora is the open-source core. Run it standalone for development or self-hosting.

---

## Requirements

- Docker + Docker Compose
- Git

---

## Quick start

```bash
git clone https://github.com/ParendumOU/Nexora.git
cd nexora
cp .env.example .env
```

Edit `.env` — minimum required:

```env
POSTGRES_PASSWORD=strong-password-here
REDIS_PASSWORD=strong-password-here
SECRET_KEY=generate-with-python-secrets-token-urlsafe-64
ENCRYPTION_KEY=generate-with-fernet-generate-key
ENVIRONMENT=production
```

Generate values:
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"   # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
```

Start:
```bash
make up
```

Run migrations (first time only):
```bash
docker compose exec backend alembic upgrade head
```

Access: `http://localhost:80`

---

## Development (hot-reload)

```bash
make dev
```

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/api/docs`

---

## First login

On first visit the app detects no users exist and redirects to `/setup`.  
Create your admin account there.

---

## Optional integrations

Add to `.env` as needed:

```env
TELEGRAM_BOT_TOKEN=
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY=
GITLAB_APP_ID=
GITLAB_APP_SECRET=
SMTP_HOST=smtp.sendgrid.net
SMTP_USER=apikey
SMTP_PASSWORD=SG.xxxxx
APP_URL=https://your-domain.com
```

---

## Invite-only registration

To prevent open registration:

```env
REQUIRE_INVITE=true
```

First account can still be created via `/setup`. After that, all registrations need an invite link (generated from Settings → Team).

---

## Useful make targets

```bash
make up          # start production
make dev         # start with hot-reload
make down        # stop
make logs        # tail logs
make clean       # stop + remove volumes (DESTRUCTIVE)
docker compose exec backend alembic revision --autogenerate -m "description"  # new migration
```
