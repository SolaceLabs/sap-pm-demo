# Deployment Guide

Step-by-step instructions to deploy the SAP PM Demo on an Ubuntu EC2 instance, alongside an existing nginx setup (like the AEM Field Guide).

This guide assumes:
- You have SSH access to an EC2 instance
- Python 3.11+ is installed (or installable via pyenv)
- nginx is already installed and running
- You have credentials for an AEM broker and an LLM API

---

## Overview

The deployment has four steps:

1. **Clone the repo and set up the Python environment**
2. **Configure environment variables (credentials)**
3. **Configure nginx to serve the web files**
4. **Run the agent stack**

After this guide, you'll have:
- The dashboard accessible at `http://your-ec2-host:9080/sap-pm-demo/dashboard`
- The agent, MCP server, and simulator running and connected to AEM

Optional CloudFront integration (for HTTPS) is covered at the end.

---

## Step 1: Clone the Repo

SSH into your EC2 instance, then:

```bash
# Navigate to the standard location for AI/demo projects
cd /home/ubuntu/sap/ai

# Clone the repo (replace with your fork if applicable)
git clone https://github.com/SolaceLabs/sap-pm-demo.git pm-demo

cd pm-demo
ls
```

You should see the repo structure: `agent/`, `web/`, `specs/`, `deploy/`, etc.

### Python Setup

If you don't already have Python 3.11+ active, use pyenv:

```bash
# Check current version
python3 --version

# If too old, set up pyenv (one-time setup)
curl https://pyenv.run | bash

# Add to .bashrc (one-time)
cat >> ~/.bashrc << 'EOF'

# pyenv setup
export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
EOF
source ~/.bashrc

# Install Python 3.11.9 (takes 5-10 min)
pyenv install 3.11.9
pyenv global 3.11.9

# Verify
python --version  # should show 3.11.9
```

### Create a Virtual Environment

```bash
cd /home/ubuntu/sap/ai/pm-demo/agent

# Create venv
python -m venv .venv

# Activate
source .venv/bin/activate

# Verify
which python  # should point to .venv/bin/python

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

If you hit a `tiktoken` build error (common on Ubuntu 18.04), install Rust:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
echo 'source "$HOME/.cargo/env"' >> ~/.bashrc

# Retry
pip install -r requirements.txt
```

---

## Step 2: Configure Environment Variables

```bash
cd /home/ubuntu/sap/ai/pm-demo/agent

# Create your .env from the template
cp .env.example .env

# Edit it with your credentials
nano .env
```

Fill in:

```bash
SOLACE_HOST=tcps://your-aem-host.messaging.solace.cloud
SOLACE_VPN=your-vpn-name
SOLACE_USERNAME=your-username
SOLACE_PASSWORD=your-password
SOLACE_PORT=8883

API_KEY=your-llm-api-key
API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4

MCP_SERVER_PATH=mcp_server/server.py
CHECK_INTERVAL=60
```

**Important:** `.env` is in `.gitignore` — never commit it.

### Verify EC2 → AEM Connectivity

Before going further, confirm the EC2 instance can reach your AEM broker:

```bash
# Extract host without scheme
SOLACE_HOST_PLAIN=$(grep SOLACE_HOST .env | cut -d= -f2 | sed 's|.*://||')
SOLACE_PORT_VALUE=$(grep SOLACE_PORT .env | cut -d= -f2)

# Test connection
nc -zv "$SOLACE_HOST_PLAIN" "$SOLACE_PORT_VALUE"
```

You should see `succeeded` or `Connected`. If it hangs or fails, there's a network/firewall issue.

---

## Step 3: Configure nginx

Your EC2 already has nginx serving the Field Guide on port 9080. We'll add the demo to the same nginx setup by inserting new `location` blocks into the existing `usecases` config file.

### Back Up the Existing Config

```bash
sudo cp /etc/nginx/sites-enabled/usecases /etc/nginx/sites-enabled/usecases.bak
```

If anything goes wrong, restore with:
```bash
sudo cp /etc/nginx/sites-enabled/usecases.bak /etc/nginx/sites-enabled/usecases
sudo systemctl reload nginx
```

### Add the Demo Location Blocks

Open the existing nginx config:

```bash
sudo nano /etc/nginx/sites-enabled/usecases
```

Find the closing `}` of the `server { ... }` block (the very last `}` in the file). **Before** that closing brace, paste the contents of `deploy/nginx/pm-demo.conf` from this repo.

Your file should end up looking like this:

```nginx
server {
    listen 9080;
    server_name _;

    root /var/www/usecases;
    index use-case-cards.html;

    location / {
        try_files $uri $uri/ =404;
    }

    location = /fieldguide {
        root /home/ubuntu/sap/usecases/aem-fieldguide/html;
        try_files /field-guide.html =404;
    }

    location = /admin {
        root /home/ubuntu/sap/usecases/aem-fieldguide/html;
        try_files /admin.html =404;
    }

    location /api/ {
        proxy_pass         http://127.0.0.1:4000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }

    # ===== SAP PM Demo location blocks (paste from deploy/nginx/pm-demo.conf) =====
    location = /sap-pm-demo { return 302 /sap-pm-demo/dashboard; }
    location = /sap-pm-demo/ { return 302 /sap-pm-demo/dashboard; }

    location = /sap-pm-demo/dashboard {
        alias /home/ubuntu/sap/ai/pm-demo/web/dashboard.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    location = /sap-pm-demo/architecture {
        alias /home/ubuntu/sap/ai/pm-demo/web/architecture.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    location = /sap-pm-demo/technician {
        alias /home/ubuntu/sap/ai/pm-demo/web/technician.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    location /sap-pm-demo/static/ {
        alias /home/ubuntu/sap/ai/pm-demo/web/static/;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }

    location /sap-pm-demo/specs/ {
        alias /home/ubuntu/sap/ai/pm-demo/specs/;
        add_header Content-Type "application/json" always;
    }
    # ===== End SAP PM Demo blocks =====
}
```

The Field Guide config (the `/fieldguide`, `/admin`, `/api/` blocks) stays exactly as it was. We only added new `/sap-pm-demo/*` location blocks.

### Test and Reload

```bash
# Validate nginx config
sudo nginx -t

# If OK, reload
sudo systemctl reload nginx
```

### Verify the Web Files Are Served

```bash
# From the EC2 instance itself
curl -I http://localhost:9080/sap-pm-demo/dashboard
# Should return: HTTP/1.1 200 OK

curl -I http://localhost:9080/sap-pm-demo/static/solclient.js
# Should return: HTTP/1.1 200 OK
```

From your laptop browser:
```
http://ec2-54-219-47-90.us-west-1.compute.amazonaws.com:9080/sap-pm-demo/dashboard
```

You should see the dashboard load. At this point it can't connect to AEM yet because we haven't started the agent stack. Click the **Settings** gear icon to open the connection panel — leave it open while you proceed.

---

## Step 4: Run the Agent Stack

The agent stack has three processes that must all be running. For initial testing, run them in three separate terminal sessions (SSH into EC2 from three terminals, or use `tmux` / `screen`).

### Using tmux (Recommended)

```bash
# Start a tmux session
tmux new -s pm-demo

# Inside tmux:
# Ctrl-B then % to split vertically
# Ctrl-B then " to split horizontally
# Ctrl-B then arrow keys to navigate panes
```

### Terminal 1: Sensor Simulator

```bash
cd /home/ubuntu/sap/ai/pm-demo/agent
source .venv/bin/activate
python simulator/sensor_sim.py
```

You should see:
```
[INFO] Connected to Solace broker at ...
[INFO] Publishing sensor data every 5 seconds
[INFO] Anomaly on machine-02 will start in 60 seconds
```

### Terminal 2: MCP Server

```bash
cd /home/ubuntu/sap/ai/pm-demo/agent
source .venv/bin/activate
python mcp_server/server.py
```

You should see:
```
[INFO] Starting Manufacturing MCP Server
[INFO] Connected to Solace broker at ...
[INFO] Subscribed to factory/line-A/+/sensors
```

### Terminal 3: Maintenance Agent

```bash
cd /home/ubuntu/sap/ai/pm-demo/agent
source .venv/bin/activate
python agent.py
```

You should see:
```
🏭 SAP PM AUTONOMOUS MAINTENANCE AGENT
🔌 Connecting to MCP Server...
✓ Connected! Discovered 5 tools
Starting SAP PM maintenance loop (checking every 60s)
```

### Watch It All Work

Switch back to your browser dashboard. Click **Connect** in the Settings panel (with your AEM credentials filled in). You should see:

1. Sensor events streaming in immediately (one per machine, every 5 seconds)
2. After ~60 seconds, the simulator triggers an anomaly on machine-02
3. The agent detects the anomaly (look at Terminal 3) and creates a PM Notification
4. The dashboard shows the PM Notification event with the "PM Notification Created" stage blinking

If everything works to here: 🎉 **the demo is running end-to-end.**

---

## Step 5: SAP Build BPA Integration

(Assumes BPA workspace exists and is configured per the project's BPA-EVENT-PAYLOADS.md guidance.)

Your BPA workflow should:

1. **Subscribe** to `factory/line-A/+/notification/pending` (using the AsyncAPI spec at `specs/asyncapi-pm-notification-pending.json`)
2. **Display** the notification to a human approver
3. **Publish** approval/rejection events to `factory/line-A/+/notification/approved` or `/rejected` (using the OpenAPI spec at `specs/openapi-pm-notification-action.json`)

Once configured, the dashboard will show the approval event arriving and the agent creating a Work Order in response.

---

## CloudFront Integration (HTTPS)

If you have an existing CloudFront distribution for the Field Guide, add a new behavior for the demo:

1. Go to **AWS Console → CloudFront → your existing distribution**
2. Click **Behaviors → Create behavior**
3. Configure:
   - **Path pattern:** `/sap-pm-demo/*`
   - **Origin:** the same EC2 origin used for `/fieldguide`
   - **Viewer protocol policy:** `Redirect HTTP to HTTPS`
   - **Allowed HTTP methods:** `GET, HEAD, OPTIONS` (no POST needed since the demo is static HTML + WSS)
   - **Cache policy:** `CachingDisabled` (HTML is dynamic-ish, and we don't want stale states)
   - **Origin request policy:** `AllViewer`
4. Save. CloudFront propagates in ~5-10 minutes.

Result: `https://your-cloudfront-domain.cloudfront.net/sap-pm-demo/dashboard` will serve the demo over HTTPS.

---

## Running as systemd Services (Production)

For repeatable demos, run the agent stack as systemd services so they auto-start on boot and restart on failure. Unit files for this will be added in `deploy/systemd/` in a future update.

---

## Troubleshooting

### "Cannot connect to broker"
- Check `.env` credentials
- Run `nc -zv your-aem-host port` from EC2
- Verify the security group allows outbound 8883 (or whatever port you use)

### Dashboard shows "Disconnected"
- Open browser DevTools (F12) → Console tab
- Look for WebSocket errors
- Verify `solclient.js` loaded (no 404)
- Check that the AEM URL in the Settings panel starts with `wss://` not `ws://`

### Agent says "MCP connection failed"
- MCP server must be running and reachable
- If running on the same machine, the agent uses stdio (no port needed)
- Check `MCP_SERVER_PATH` in `.env` points to the correct file

### "Module not found" errors
- Activate the venv: `source .venv/bin/activate`
- Reinstall: `pip install -r requirements.txt`

### nginx says "404" for /sap-pm-demo/dashboard
- Verify file exists: `ls -la /home/ubuntu/sap/ai/pm-demo/web/dashboard.html`
- Verify nginx user can read it: `sudo -u www-data cat /home/ubuntu/sap/ai/pm-demo/web/dashboard.html`
- Check nginx error log: `sudo tail -f /var/log/nginx/error.log`

### LLM API errors
- Verify `API_KEY` is correct
- Check that `LLM_MODEL` exists for your provider
- Check your provider's rate limits

---

## Quick Reference

| Component | Where | How to Run |
|-----------|-------|------------|
| Sensor Simulator | `agent/simulator/sensor_sim.py` | `python simulator/sensor_sim.py` |
| MCP Server | `agent/mcp_server/server.py` | `python mcp_server/server.py` |
| Maintenance Agent | `agent/agent.py` | `python agent.py` |
| Dashboard | `web/dashboard.html` | Browse to URL |
| nginx config | `/etc/nginx/sites-available/...` | `sudo nginx -t && sudo systemctl reload nginx` |

| URL | What It Serves |
|-----|----------------|
| `/sap-pm-demo/dashboard` | Live event monitor |
| `/sap-pm-demo/architecture` | Architecture diagram |
| `/sap-pm-demo/static/*` | CSS, JS, images |
| `/sap-pm-demo/specs/*` | AsyncAPI/OpenAPI JSON specs |

---

## Next Steps

After deployment is working:

1. Read [`DEMO_GUIDE.md`](./DEMO_GUIDE.md) for talking points and the demo script
2. Read [`ARCHITECTURE.md`](./ARCHITECTURE.md) to be ready for technical questions
3. Practice the demo end-to-end before showing a customer
