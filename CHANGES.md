# Phase 1 (Complete) — Demo Controls + QR Dispatch

This bundle delivers the complete Phase 1 demo experience: SE-controlled demo flow, polished UX, and audience-participation QR-code technician dispatch.

## What's New

### Demo Controls (already shipped, refined in this bundle)
- **Start Demo / Stop Demo / Trigger Anomaly / Reset** buttons in dashboard
- Status badge: NOT CONNECTED / STOPPED / ACTIVE / ANOMALY ACTIVE
- 30-minute auto-reset timer with 28-minute warning + "Extend 30 min" button
- All controls gated on AEM connection state

### NEW: QR-Code Technician Dispatch (Phase 1.2)
The signature WOW moment: during the demo, the presenter shows a QR code. Audience scans, taps "I'm Available" on their phones, and the first to tap wins the assignment when the work order is approved.

**Flow:**
1. SE clicks **▶ Start Demo** → demo active
2. SE clicks **⚡ Trigger Anomaly** → machine-02 starts drifting
3. Agent detects anomaly within ~10s → publishes PM Notification
4. SE clicks **📱 Show QR for Technicians** → big QR modal appears on dashboard
5. Audience scans QR → each phone opens the technician page
6. Phones tap "✓ I'm Available" → live counter in modal increments
7. SE approves notification in BPA
8. Agent creates work order → arbitrator picks first-in-pool winner
9. Winning phone shows full work order details with confetti + vibration
10. Losing phones show "Tech-XXXX was assigned this dispatch"
11. Dashboard shows winner banner: "🎯 Tech-A1B2 received the work order (2 others standing by)"

### NEW: Toast Notifications (Phase 1.1)
Replaced the modal-after-Stop/Reset with subtle toast notifications that slide in from the top-right and auto-dismiss in 3 seconds. Modals now only appear when the SE needs to take action:
- AEM connection success (welcome message)
- 30-minute auto-reset (needs SE to re-Start)

### Recommended: CHECK_INTERVAL=10 (Phase 1.1)
Updated `.env.example` to recommend `CHECK_INTERVAL=10` instead of `60`. Snappier anomaly detection (10-15s after Trigger Anomaly instead of up to 60s).

## What Changed in the Code

### NEW: `services/dispatch_arbitrator.py`
Python service that manages the QR-code dispatch flow.

**Subscribes to:**
- `factory/line-A/dispatch/qr-shown` — presenter clicked Show QR (new round)
- `factory/line-A/dispatch/availability` — phone tapped "I'm Available"
- `factory/line-A/+/workorder/created` — agent created a work order (trigger assignment)
- `factory/line-A/control/demo/reset` — hard reset, clear pool

**Publishes to:**
- `factory/line-A/dispatch/assignment` — winner selected
- `factory/line-A/dispatch/pool-update` — pool size updated (live counter)

**Pool logic:**
- First-in-pool wins
- Each phone has a unique tech_id (browser-generated, persisted in sessionStorage)
- Duplicates deduplicated by tech_id
- Round bounded by round_id (each Show QR click = new round)
- Stale events from previous rounds are ignored

### NEW: `services/requirements.txt`, `services/run_arbitrator.sh`, `services/README.md`

### NEW: `web/technician.html`
Mobile-optimized page that audience phones land on after scanning the QR code.

**Five states:**
- **AVAILABLE** — round is open, big "I'm Available" button
- **STANDING BY** — joined the pool, watching pool counter
- **WON** — assigned the work order, full details, confetti, vibration, Accept button
- **LOST** — another tech got it, friendly "stay ready" message
- **IDLE** — no active round, wait for presenter

### `web/dashboard.html`
- New "📱 Show QR for Technicians" button (purple gradient, enabled when ACTIVE or ANOMALY_ACTIVE)
- QR code modal with live pool counter inside
- Winner reveal banner above stats row
- Toast notification system (top-right, 3s auto-dismiss)
- Removed modals after Stop/Reset (now toasts)
- Saves AEM credentials to localStorage on connect (for QR URL embedding)
- Subscribed to dispatch/pool-update and dispatch/assignment

### `agent/.env.example`
- Updated `CHECK_INTERVAL` default to `10` with explanation

## Topic Reference (Complete)

**Control plane:**
- `factory/line-A/control/demo/start` — dashboard → simulator
- `factory/line-A/control/demo/stop` — dashboard → simulator
- `factory/line-A/control/demo/reset` — dashboard → simulator + arbitrator
- `factory/line-A/control/anomaly/trigger` — dashboard → simulator
- `factory/line-A/control/demo/state` — simulator → all (state sync)

**Dispatch plane (NEW):**
- `factory/line-A/dispatch/qr-shown` — dashboard → arbitrator
- `factory/line-A/dispatch/availability` — phone → arbitrator
- `factory/line-A/dispatch/pool-update` — arbitrator → all (live counter)
- `factory/line-A/dispatch/assignment` — arbitrator → all (winner)

**Data plane (unchanged):**
- `factory/line-A/{machine_id}/sensors` — simulator → all
- `factory/line-A/{machine_id}/notification/pending` — agent → BPA
- `factory/line-A/{machine_id}/notification/approved` — BPA → MCP
- `factory/line-A/{machine_id}/notification/rejected` — BPA → MCP
- `factory/line-A/{machine_id}/workorder/created` — agent → all (including arbitrator)

## Deployment

### 1. On your Mac (push to GitHub)

```bash
cd /Users/sumeetkoshal/ai/sap-pm-demo

# Unzip the bundle
unzip -o ~/Downloads/sap-pm-demo-phase1-complete.zip -d /tmp/p1c/

# Copy changed files
cp /tmp/p1c/agent/simulator/sensor_sim.py agent/simulator/sensor_sim.py
cp /tmp/p1c/agent/.env.example agent/.env.example
cp /tmp/p1c/web/dashboard.html web/dashboard.html
cp /tmp/p1c/web/technician.html web/technician.html

# New files
mkdir -p services
cp /tmp/p1c/services/dispatch_arbitrator.py services/dispatch_arbitrator.py
cp /tmp/p1c/services/requirements.txt services/requirements.txt
cp /tmp/p1c/services/run_arbitrator.sh services/run_arbitrator.sh
cp /tmp/p1c/services/README.md services/README.md
chmod +x services/run_arbitrator.sh

cp /tmp/p1c/CHANGES.md .

# Commit
git add -A
git status
git commit -m "Phase 1 complete: demo controls, toasts, QR-code technician dispatch"
git push
```

### 2. On EC2

```bash
ssh ubuntu@ec2-54-219-47-90.us-west-1.compute.amazonaws.com
cd /home/ubuntu/sap/ai/pm-demo
git pull

# Update CHECK_INTERVAL in .env
nano agent/.env
# Change CHECK_INTERVAL=60 to CHECK_INTERVAL=10

# Terminal 1 — Simulator:
cd /home/ubuntu/sap/ai/pm-demo/agent
source .venv/bin/activate
python simulator/sensor_sim.py

# Terminal 2 — Agent:
cd /home/ubuntu/sap/ai/pm-demo/agent
source .venv/bin/activate
python agent.py

# Terminal 3 — Arbitrator:
cd /home/ubuntu/sap/ai/pm-demo/services
chmod +x run_arbitrator.sh
./run_arbitrator.sh
```

### 3. Nginx — Add technician page location

Add this block to `/etc/nginx/sites-enabled/usecases` alongside the existing dashboard block:

```nginx
location /sap-pm-demo/technician {
    default_type text/html;
    alias /home/ubuntu/sap/ai/pm-demo/web/technician.html;
}
```

Then reload: `sudo nginx -t && sudo nginx -s reload`

### 4. Verification

Hard-refresh dashboard (`Cmd+Shift+R`):

1. Connect to AEM → welcome modal
2. Start Demo → timer starts
3. Trigger Anomaly → agent detects within 10-15s
4. Click "📱 Show QR for Technicians" → QR modal with pool counter
5. Scan QR with phone → phone shows "I'm Available" button
6. Tap "I'm Available" → pool counter increments in modal
7. Approve notification in BPA
8. Agent creates work order → winning phone gets confetti + WO details
9. Dashboard shows winner banner, QR modal auto-closes
10. Stop Demo → toast "Demo stopped" (no modal)
11. Reset → toast "Demo reset to clean state"

## Phase 2 Preview

- Agent goes event-driven (no polling, zero idle LLM cost)
- 30-min timer moves server-side (browser-independent)
- Work order creation within 1-2s of BPA approval
