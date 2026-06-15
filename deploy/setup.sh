#!/bin/bash
set -e

REPO_DIR="/home/ubuntu/sap/ai/pm-demo"
SYSTEMD_DIR="/etc/systemd/system"
NGINX_CONF="/etc/nginx/sites-enabled/usecases"

echo "═══════════════════════════════════════════════════════════"
echo "  SAP PM Demo — One-Time Setup"
echo "═══════════════════════════════════════════════════════════"

# 1. Install systemd units
echo ""
echo "Installing systemd services..."
sudo cp "$REPO_DIR/deploy/systemd/pm-simulator.service"  "$SYSTEMD_DIR/"
sudo cp "$REPO_DIR/deploy/systemd/pm-agent.service"      "$SYSTEMD_DIR/"
sudo cp "$REPO_DIR/deploy/systemd/pm-arbitrator.service"  "$SYSTEMD_DIR/"
sudo systemctl daemon-reload
echo "  ✓ Systemd services installed"

# 2. Enable and start
echo ""
echo "Enabling and starting services..."
sudo systemctl enable pm-simulator pm-agent pm-arbitrator
sudo systemctl start pm-simulator
sudo systemctl start pm-arbitrator
sudo systemctl start pm-agent
echo "  ✓ All 3 services running (auto-start on reboot)"

# 3. Nginx
echo ""
echo "Checking nginx configuration..."
if grep -q "sap-pm-demo/dashboard" "$NGINX_CONF" 2>/dev/null; then
  echo "  ✓ Nginx locations already configured"
else
  echo "  Adding nginx locations..."
  sudo bash -c "cat >> $NGINX_CONF" << 'NGINX'

# SAP PM Demo
location /sap-pm-demo/dashboard {
    default_type text/html;
    alias /home/ubuntu/sap/ai/pm-demo/web/dashboard.html;
}
location /sap-pm-demo/technician {
    default_type text/html;
    alias /home/ubuntu/sap/ai/pm-demo/web/technician.html;
}
location /sap-pm-demo/architecture {
    default_type text/html;
    alias /home/ubuntu/sap/ai/pm-demo/web/architecture.html;
}
location /sap-pm-demo/static/ {
    alias /home/ubuntu/sap/ai/pm-demo/web/static/;
}
NGINX
  sudo nginx -t && sudo nginx -s reload
  echo "  ✓ Nginx configured and reloaded"
fi

# 4. Summary
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Setup Complete!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Dashboard: http://$(hostname -f):9080/sap-pm-demo/dashboard"
echo ""
echo "  Each SE enters their name on the dashboard."
echo "  Topics automatically namespace to factory/{name}/..."
echo "  Multiple SEs can demo simultaneously without interference."
echo ""
echo "  Manage services:"
echo "    ./deploy/pm-ctl.sh status"
echo "    ./deploy/pm-ctl.sh restart"
echo "    ./deploy/pm-ctl.sh logs"
echo ""
