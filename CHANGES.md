# Phase 1 Changes — Demo Controls

This document describes the changes made for Phase 1 of the demo refactor. After applying these changes, the SE has full control over when anomalies happen, when the demo starts/stops, and what state the system is in.

## What's New

### Dashboard

A new **Demo Controls** panel appears at the top of the main content area. It contains:

- **▶ Start Demo** — begins a new demo session (publishes `demo/start` event)
- **⚡ Trigger Anomaly** — initiates the machine-02 anomaly drift sequence (publishes `anomaly/trigger` event)
- **⏹ Stop Demo** — ends the current demo session, clears anomaly state
- **🔄 Reset** — hard reset: clears state, dashboard counters, event feed
- **Demo Status Badge** — visual indicator showing STOPPED / ACTIVE / ANOMALY ACTIVE
- **Demo Timer** — countdown showing time until auto-reset

### Idle Modal

The idle modal **only appears after a successful AEM connection** — the SE needs to connect first before the demo can begin. After successful AEM connection, a friendly welcome modal blocks the dashboard. The SE must click "Start Demo" to begin. Modal triggers:

- **After successful AEM connection** — "Welcome to the Demo"
- **After Stop Demo** — "You stopped the demo"
- **After auto-reset (30 minutes)** — "The demo has automatically reset"
- **After manual Reset** — "The demo has been reset to a clean state"

If AEM disconnects mid-demo, the modal hides and all demo controls become disabled (the SE needs to reconnect first).

### AEM Connection Gating

All demo control buttons are **disabled until AEM is connected**. The status badge shows "NOT CONNECTED" until a successful AEM connection. This prevents the SE from clicking Start Demo before the dashboard can actually publish control events.

### Auto-Reset (30 minutes)

- Timer starts when SE clicks "Start Demo"
- At 28-minute mark: warning banner appears with "Extend 30 min" button
- At 30-minute mark: hard reset, idle modal explains what happened
- Timer is browser-side for Phase 1 (Phase 2 will move it server-side)

### Visual Polish

- **Stage highlight blink** now blinks for 2 seconds, then lingers for ~5 more seconds with a fading background. Audiences can register what's happening instead of missing the flash.

## What Changed in the Code

### `agent/simulator/sensor_sim.py`

**Major changes:**
- Removed the auto-anomaly timer (`AUTO_ANOMALY`, `ANOMALY_DELAY_SEC` env vars no longer used)
- Added MQTT subscription to `factory/line-A/control/+/+`
- Added `handle_control_event()` that reacts to `demo/start`, `demo/stop`, `demo/reset`, `anomaly/trigger`
- Added `broadcast_state()` that publishes simulator state changes to `factory/line-A/control/demo/state`
- Anomaly drift now triggered ONLY by control events from the dashboard
- Drift growth rate increased (`0.01` → `0.03` per cycle) so the demo gets to "concerning readings" faster after trigger

**Behavior change:** The simulator now starts in a "normal readings only" state. It continues publishing sensor data, but no anomaly until the dashboard sends a trigger event.

### `agent/agent.py`

**Not changed in Phase 1.** Agent still polls every 60 seconds via `CHECK_INTERVAL`. Phase 2 will make this event-driven.

### `web/dashboard.html`

**Added:**
- CSS for Demo Controls panel, status badge, timer, warning banner, idle modal
- HTML for Demo Controls panel (placed between Connection Panel and Stats Row)
- HTML for Idle Modal overlay (placed before closing `</body>`)
- JavaScript:
  - `publishControlEvent(category, action, extraData)` — publishes CloudEvent to AEM
  - `startDemo()`, `stopDemo()`, `triggerAnomaly()`, `resetDemo()`, `extendDemo()` — button handlers
  - `startDemoTimer()`, `stopDemoTimer()`, `updateTimerDisplay()`, `handleAutoReset()` — 30-min timer
  - `updateDemoUI()` — sync button enabled state and badge with demo state
  - `showIdleModal(title, message, reason)`, `hideIdleModal()` — modal management
  - `clearDashboardState()` — clear stats, event feed, and stage highlights on reset
  - `handleDemoStateEvent(payload)` — log simulator state syncs
- Subscribed to new topic: `factory/line-A/control/demo/state`
- DOMContentLoaded handler updated to show idle modal on page load
- Extended `blink-highlight` animation with `lingerHighlight` keyframe (5s linger after blink)

## Topic Reference

**Control plane (new):**
- `factory/line-A/control/demo/start` — dashboard publishes when SE clicks Start Demo
- `factory/line-A/control/demo/stop` — dashboard publishes when SE clicks Stop Demo
- `factory/line-A/control/demo/reset` — dashboard publishes when SE clicks Reset, or on auto-reset
- `factory/line-A/control/anomaly/trigger` — dashboard publishes when SE clicks Trigger Anomaly
- `factory/line-A/control/demo/state` — simulator publishes state changes (informational)

**Data plane (unchanged):**
- `factory/line-A/{machine_id}/sensors` — simulator publishes sensor readings
- `factory/line-A/{machine_id}/notification/pending` — agent publishes PM notifications
- `factory/line-A/{machine_id}/notification/approved` — BPA publishes approvals
- `factory/line-A/{machine_id}/notification/rejected` — BPA publishes rejections
- `factory/line-A/{machine_id}/workorder/created` — agent publishes work orders

## Deployment Steps

### 1. On your Mac (push to GitHub)

```bash
cd /Users/sumeetkoshal/ai/sap-pm-demo

# Replace the two changed files with the new versions
# (Drop in the files from this bundle)

# Verify what changed
git status
git diff agent/simulator/sensor_sim.py | head -30
git diff web/dashboard.html | head -30

# Commit and push
git add agent/simulator/sensor_sim.py web/dashboard.html CHANGES.md
git commit -m "Phase 1: Demo controls (Start/Stop/Trigger Anomaly/Reset) with 30-min auto-reset"
git push
```

### 2. On EC2 (pull and restart)

```bash
ssh ubuntu@ec2-54-219-47-90.us-west-1.compute.amazonaws.com
cd /home/ubuntu/sap/ai/pm-demo
git pull

# Restart the simulator (it now subscribes to control topics)
# Find the simulator terminal and Ctrl+C, then:
cd /home/ubuntu/sap/ai/pm-demo/agent
source .venv/bin/activate
python simulator/sensor_sim.py

# The dashboard updates automatically when nginx reloads the file
# Just hard-refresh in your browser (Cmd+Shift+R) to bypass cache
```

### 3. Verification

In your browser, hard-refresh `http://ec2-54-219-47-90.us-west-1.compute.amazonaws.com:9080/sap-pm-demo/dashboard`. You should see:

1. **No modal on initial load** — page is fully visible with the AEM Connection Settings panel
2. **All Demo Control buttons are disabled** (greyed out) and the status badge shows "NOT CONNECTED"
3. **Enter AEM credentials, click Connect**
4. **After successful connection:**
   - Status indicator at top shows "Connected"
   - Subscribe success messages appear in connection log (look for the new state topic)
   - **Idle modal appears** with "Welcome to the Demo" message
   - Demo control buttons become enabled (Start Demo and Reset)
5. **Click Start Demo** (either from the modal or the main button after closing) — modal closes, demo timer starts counting down from 30:00
6. **Status badge** shows "ACTIVE" (green pulse)
7. Sensor events should be flowing in the event feed (normal readings, no anomaly)
8. Click **Trigger Anomaly** — status changes to "ANOMALY ACTIVE" (amber pulse)
9. **Within 15 seconds**, sensor readings for machine-02 should show elevated temp/vibration
10. **Within 60 seconds**, the agent's next poll should detect the anomaly and create a PM Notification
11. **Approve in BPA** — within the agent's next poll cycle, a work order is created
12. Click **Reset** — back to clean state, idle modal appears
13. **Disconnect from AEM** (click Disconnect in Settings) → all demo control buttons disable immediately

## What Still Polls (Phase 1 limitation)

The **agent** still polls every 60 seconds (`CHECK_INTERVAL=60` in `.env`). This means:
- Even when no demo is running, agent makes one LLM call per minute
- Cost: minimal (only "all normal, no action" responses) but not zero

**Phase 2 will eliminate this.** Agent will subscribe to events and only call LLM when there's actually something to act on. The 30-minute auto-reset will also move from browser-side to server-side.

## Phase 2 Preview

When you're ready, Phase 2 will:
- Refactor `agent/agent.py` from a polling loop to an event-driven service
- Subscribe to: `notification/approved`, `notification/rejected`, `anomaly/trigger`, sensor changes
- Server-side 30-minute timer (independent of browser state)
- Zero LLM calls when idle
- Faster reaction time (work order creation within seconds of BPA approval, not 60s)

## Testing Locally Without EC2

If you want to validate the simulator changes work on your Mac before pushing to EC2:

```bash
cd /Users/sumeetkoshal/ai/sap-pm-demo/agent
source .venv/bin/activate
python simulator/sensor_sim.py

# In another terminal, use Solace Try-Me (or any MQTT client)
# Publish a test message to: factory/line-A/control/anomaly/trigger
# Payload: {"specversion":"1.0","type":"com.factory.control.anomaly.trigger.v1","data":{}}

# Watch the simulator logs — it should print:
#   "ANOMALY TRIGGERED on machine-02 - bearing degradation starts now"
# And subsequent sensor readings should show elevated values
```
