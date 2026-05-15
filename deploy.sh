#!/usr/bin/env bash
# deploy.sh — Deploy auth-gateway to Pi5 (.99)
set -euo pipefail

PI5="pi5"
APP_DIR="/usr/local/bin/auth-gateway"

echo "==> Deploying auth-gateway to Pi5 ($PI5)"

# 1. Create app directory and copy files
ssh "$PI5" "sudo mkdir -p $APP_DIR && sudo chown uri:uri $APP_DIR"
scp app.py "$PI5:$APP_DIR/"
scp requirements.txt "$PI5:$APP_DIR/"
scp -r templates "$PI5:$APP_DIR/"

# 2. Set up Python venv and install dependencies
ssh "$PI5" "
  cd $APP_DIR
  python3 -m venv venv
  venv/bin/pip install -q --upgrade pip
  venv/bin/pip install -q -r requirements.txt
"

# 3. Copy env file if not already present
if ! ssh "$PI5" "test -f /usr/local/bin/auth-gateway.env"; then
  echo ""
  echo "⚠️  /usr/local/bin/auth-gateway.env not found on Pi5."
  echo "    Create it before starting the service:"
  echo "    scp auth-gateway.env.example $PI5:/usr/local/bin/auth-gateway.env"
  echo "    Then edit it: ssh $PI5 nano /usr/local/bin/auth-gateway.env"
  echo ""
fi

# 4. Install and enable systemd service
scp auth-gateway.service "$PI5:/tmp/auth-gateway.service"
ssh "$PI5" "sudo mv /tmp/auth-gateway.service /etc/systemd/system/auth-gateway.service"
ssh "$PI5" "
  sudo systemctl daemon-reload
  sudo systemctl enable auth-gateway
  sudo systemctl restart auth-gateway
"

# 5. Run migration if DB does not exist yet
ssh "$PI5" "
  if [ ! -f /home/uri/auth_gateway.db ]; then
    echo 'Running one-time migration from alwayson JSON files...'
    $APP_DIR/venv/bin/python $APP_DIR/migrate.py \
      --users /home/uri/alwayson_allowed.json \
      --totp  /home/uri/alwayson_totp.json \
      --db    /home/uri/auth_gateway.db
  else
    echo 'Database already exists — skipping migration'
  fi
"

# 6. Open firewall port (LAN only)
ssh "$PI5" "sudo ufw allow from 192.168.40.100 to any port 4001 proto tcp 2>/dev/null || true"

echo ""
echo "✅ auth-gateway deploy complete!"
echo "Service: https://myweb.tail075174.ts.net/auth/login"
echo "Admin:   https://myweb.tail075174.ts.net/auth/admin"
echo "Version: https://myweb.tail075174.ts.net/auth/version"
