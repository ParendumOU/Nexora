#!/usr/bin/env bash
# Nexora installer — Linux / macOS
#
#   curl -fsSL https://raw.githubusercontent.com/ParendumOU/Nexora/main/install.sh | bash
#
# Interactive: asks a couple of questions, generates all secrets, writes .env,
# starts the Docker stack and runs the database migrations. Safe to re-run.
#
# Non-interactive (accept all defaults):
#   NEXORA_NONINTERACTIVE=1 bash install.sh
#
# Overrides: NEXORA_DIR, NEXORA_PORT, NEXORA_REPO_URL
set -euo pipefail

REPO_URL="${NEXORA_REPO_URL:-https://github.com/ParendumOU/Nexora.git}"
DEFAULT_DIR="${NEXORA_DIR:-$PWD/nexora}"
DEFAULT_PORT="${NEXORA_PORT:-80}"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[32m ✓ \033[0m%s\n' "$*"; }
fail()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Read from the terminal even when the script itself is piped into bash.
ask() { # ask <prompt> <default> -> REPLY
  local prompt="$1" default="$2"
  if [ "${NEXORA_NONINTERACTIVE:-0}" = "1" ] || [ ! -e /dev/tty ]; then
    REPLY="$default"
    return
  fi
  printf '%s [%s]: ' "$prompt" "$default" > /dev/tty
  IFS= read -r REPLY < /dev/tty || REPLY=""
  [ -n "$REPLY" ] || REPLY="$default"
}

ask_yn() { # ask_yn <prompt> <y|n> -> 0 if yes
  local prompt="$1" default="$2"
  ask "$prompt (y/n)" "$default"
  case "$REPLY" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

bold ""
bold "  Nexora — self-hosted AI-agent orchestration platform"
bold "  https://nexora.parendum.com"
bold ""

# ── 1. Requirements ───────────────────────────────────────────────────────────
info "Checking requirements"
command -v docker  >/dev/null 2>&1 || fail "Docker is required. Install it from https://docs.docker.com/engine/install/ and re-run."
command -v git     >/dev/null 2>&1 || fail "git is required. Install it with your package manager and re-run."
command -v curl    >/dev/null 2>&1 || fail "curl is required."
command -v openssl >/dev/null 2>&1 || fail "openssl is required."

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  fail "Docker Compose is required (the 'docker compose' plugin). See https://docs.docker.com/compose/install/"
fi
docker info >/dev/null 2>&1 || fail "The Docker daemon is not running (or you lack permission). Start Docker and re-run."
ok "Docker, Compose, git found"

# ── 2. Get the code ───────────────────────────────────────────────────────────
if [ -f docker-compose.yml ] && [ -d backend/src ] && [ -f .env.example ]; then
  INSTALL_DIR="$PWD"
  ok "Existing Nexora checkout detected — installing here ($INSTALL_DIR)"
else
  ask "Where should Nexora be installed?" "$DEFAULT_DIR"
  INSTALL_DIR="$REPLY"
  if [ -d "$INSTALL_DIR/.git" ]; then
    info "Directory exists — pulling latest"
    git -C "$INSTALL_DIR" pull --ff-only
  else
    info "Cloning $REPO_URL"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi
  cd "$INSTALL_DIR"
fi

# ── 3. Configuration ──────────────────────────────────────────────────────────
if [ -f .env ]; then
  ok ".env already exists — keeping your configuration"
else
  info "Configuring your instance"
  ask "HTTP port for the web UI" "$DEFAULT_PORT"
  HTTP_PORT="$REPLY"
  REQUIRE_INVITE=false
  if ask_yn "Require an invite link to register new users? (recommended for shared servers)" "n"; then
    REQUIRE_INVITE=true
  fi

  info "Generating secrets"
  PG_PASS="$(openssl rand -hex 24)"
  REDIS_PASS="$(openssl rand -hex 24)"
  SECRET_KEY="$(openssl rand -hex 48)"
  ENCRYPTION_KEY="$(openssl rand -base64 32 | tr '+/' '-_')"

  cp .env.example .env
  sed -i.bak \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$PG_PASS|" \
    -e "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$REDIS_PASS|" \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" \
    -e "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY|" \
    -e "s|^HTTP_PORT=.*|HTTP_PORT=$HTTP_PORT|" \
    -e "s|^REQUIRE_INVITE=.*|REQUIRE_INVITE=$REQUIRE_INVITE|" \
    -e "s|^CORS_ORIGINS=.*|CORS_ORIGINS=http://localhost,http://localhost:$HTTP_PORT,http://localhost:3000,http://localhost:8080|" \
    .env
  rm -f .env.bak
  ok ".env written (secrets generated automatically)"
fi

HTTP_PORT="$(grep -E '^HTTP_PORT=' .env | cut -d= -f2)"
HTTP_PORT="${HTTP_PORT:-80}"

# ── 4. Start ──────────────────────────────────────────────────────────────────
info "Building and starting the stack (first build can take a few minutes)"
$COMPOSE up -d --build

info "Waiting for the backend to become ready"
ATTEMPTS=0
until $COMPOSE exec -T backend python -c "import sys; sys.exit(0)" >/dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS + 1))
  if [ "$ATTEMPTS" -ge 30 ]; then
    fail "Backend did not become ready. Check logs with: $COMPOSE logs backend"
  fi
  sleep 3
done
ok "Backend is up"

info "Running database migrations"
ATTEMPTS=0
until $COMPOSE exec -T backend alembic upgrade head >/dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS + 1))
  if [ "$ATTEMPTS" -ge 10 ]; then
    fail "Migrations failed. Check logs with: $COMPOSE logs backend"
  fi
  sleep 3
done
ok "Database is ready"

# ── 5. Done ───────────────────────────────────────────────────────────────────
URL="http://localhost:${HTTP_PORT}"
[ "$HTTP_PORT" = "80" ] && URL="http://localhost"

bold ""
bold "  Nexora is running!"
bold ""
echo "  1. Open $URL in your browser"
echo "  2. You will be redirected to /setup — create your admin account there"
echo ""
echo "  Useful commands (run inside $INSTALL_DIR):"
echo "    $COMPOSE logs -f      # tail logs"
echo "    $COMPOSE down         # stop"
echo "    $COMPOSE up -d        # start again"
echo ""
echo "  Docs: https://docs.nexora.parendum.com"
echo ""
