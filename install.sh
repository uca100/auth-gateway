#!/usr/bin/env bash
# install.sh — auth-gateway (Unified Authentication Service)
# Run ON pi5 (192.168.40.99) as the 'uri' user.
# Idempotent: safe to re-run after app changes.
#
# IMPORTANT: auth-gateway is the auth layer for ALL apps behind nginx.
# It must be running before any other app is accessible.
#
# Usage: bash install.sh
# Prerequisites: python3, pip installed on pi5

set -e

APP="auth-gateway"
APP_DIR="/usr/local/bin/auth-gateway"
ENV_FILE="/usr/local/bin/auth-gateway.env"
DB_FILE="/home/uri/auth_gateway.db"
PORT=4001
USER="uri"

echo "==> [auth-gateway] Starting install/update..."

# ── 1. System dependencies ─────────────────────────────────────────────────
echo "==> Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-pip

# ── 2. App directory & source ───────────────────────────────────────────────
echo "==> Setting up app directory at ${APP_DIR}..."
sudo mkdir -p "${APP_DIR}"
sudo chown "${USER}:${USER}" "${APP_DIR}"

if [[ ! -f "${APP_DIR}/app.py" ]]; then
  echo "WARNING: No source files found in ${APP_DIR}."
  echo "Run ./deploy.sh from mac first, then re-run install.sh."
  exit 1
fi

# ── 3. Python virtual environment ───────────────────────────────────────────
echo "==> Setting up Python venv..."
cd "${APP_DIR}"
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

# ── 4. Environment file ─────────────────────────────────────────────────────
if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${APP_DIR}/auth-gateway.env.example" ]]; then
    cp "${APP_DIR}/auth-gateway.env.example" "${ENV_FILE}"
  else
    cat > "${ENV_FILE}" <<EOF
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=502550514
SECRET_KEY=generate_a_random_secret_here
OTP_TTL=300
SESSION_TTL=14400
DB_FILE=/home/uri/auth_gateway.db
ADMIN_USER=uri
EOF
  fi
  chmod 600 "${ENV_FILE}"
  echo "==> IMPORTANT: Edit ${ENV_FILE} — fill in TELEGRAM_TOKEN and SECRET_KEY."
else
  echo "==> Env file already exists at ${ENV_FILE} — skipping."
fi

# ── 5. Database migration (first-time only) ─────────────────────────────────
if [[ ! -f "${DB_FILE}" ]]; then
  echo "==> Running one-time DB migration from legacy JSON files..."
  USERS_JSON="/home/uri/alwayson_allowed.json"
  TOTP_JSON="/home/uri/alwayson_totp.json"
  "${APP_DIR}/venv/bin/python" "${APP_DIR}/migrate.py" \
    --users "${USERS_JSON}" \
    --totp  "${TOTP_JSON}" \
    --db    "${DB_FILE}" 2>/dev/null || {
    echo "==> Migration skipped (no legacy files). DB will be created fresh on first run."
  }
else
  echo "==> Database already exists — skipping migration."
fi

# ── 6. Systemd service ──────────────────────────────────────────────────────
echo "==> Installing systemd service..."
sudo cp "${APP_DIR}/auth-gateway.service" "/etc/systemd/system/auth-gateway.service"
sudo systemctl daemon-reload
sudo systemctl enable auth-gateway
sudo systemctl restart auth-gateway

sleep 2
if sudo systemctl is-active --quiet auth-gateway; then
  echo "==> auth-gateway service is running."
else
  echo "ERROR: auth-gateway service failed to start. Check: journalctl -u auth-gateway -n 50"
  exit 1
fi

# ── 7. Firewall ─────────────────────────────────────────────────────────────
echo "==> Checking firewall rule for port ${PORT}..."
if ! sudo ufw status | grep -q "${PORT}"; then
  sudo ufw allow from 192.168.40.100 to any port ${PORT} proto tcp comment "auth-gateway — nginx proxy only"
  echo "==> ufw rule added for port ${PORT}."
else
  echo "==> ufw rule already exists."
fi

echo ""
echo "==> MANUAL STEP (if first install): Nginx must route /auth to this service."
echo "    location /auth { proxy_pass http://192.168.40.99:4001; ... }"
echo "    Then: cd ~/projects/nginx-proxy && ./deploy.sh"
echo ""
echo "==> Admin panel: https://myweb.tail075174.ts.net/auth/admin"
echo "==> [auth-gateway] Install complete."
