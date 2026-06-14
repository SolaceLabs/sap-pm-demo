# Web Dashboard

Static HTML/JS files for the live event monitoring dashboard.

## Files

| File | Purpose |
|------|---------|
| `dashboard.html` | Main live event monitor — shows AEM events as they happen |
| `static/solclient.js` | Solace PubSub+ JavaScript API (for WSS connection to AEM) |
| `static/` | CSS, JS, images |
| `docs/` | Architecture diagram, demo guide (when rendered as HTML) |

## How It's Served

The dashboard is **a static page** that connects directly to AEM via WebSocket (WSS). No backend required.

In production (on EC2), nginx serves these files from `/home/ubuntu/sap/ai/pm-demo/web/` at the path `/sap-pm-demo/*`.

See [`../deploy/nginx/`](../deploy/nginx/) for the nginx config snippet.

## Local Development

To run the dashboard on your laptop:

```bash
cd web/
python3 -m http.server 8000
```

Then open `http://localhost:8000/dashboard.html`.

When the dashboard opens, click the **Settings** gear icon (top right) and enter your AEM connection details:
- WebSocket Host (e.g., `wss://your-host.messaging.solace.cloud:443`)
- VPN Name
- Username / Password

Click **Connect**. You should see "Connected to AEM" status and events start streaming as they arrive.

## URL Paths When Deployed

When deployed to EC2 + CloudFront:

| Path | Serves |
|------|--------|
| `/sap-pm-demo/dashboard` | `dashboard.html` |
| `/sap-pm-demo/static/solclient.js` | Solace JS API |
| `/sap-pm-demo/static/*` | All static assets |

URLs in HTML use relative paths (e.g., `static/solclient.js`) so they work correctly under both the EC2-direct URL and the CloudFront-fronted HTTPS URL.

## What the Dashboard Shows

- **Stats row** — counters for sensor events, notifications, approvals, rejections, work orders
- **Live event feed** — every AEM message with timestamp, topic, and key details
- **Process stages** — visual timeline of the SAP PM workflow with animations for important transitions
- **Current event payload** — JSON of the most recent event
- **Tablet popup** — appears when a work order is created (mimics technician's mobile screen)
- **Connection log** — connection status and subscription activity

## Connection Topics

The dashboard subscribes to these AEM topics:

- `factory/line-A/*/sensors` — Sensor data from simulator
- `factory/line-A/*/notification/pending` — PM Notifications created by agent
- `factory/line-A/*/notification/approved` — Approvals from BPA
- `factory/line-A/*/notification/rejected` — Rejections from BPA
- `factory/line-A/*/workorder/created` — Work orders created by agent
