# SAP Predictive Maintenance Demo

A working demonstration of how SAP customers can use **SAP Advanced Event Mesh (AEM)** to build event-driven predictive maintenance with AI agents, integrated with SAP Plant Maintenance (PM) and SAP Build Process Automation (BPA).

This repo contains everything needed to run the demo: agent code, web dashboard, AsyncAPI specs, deployment guides, and field-team talking points.

---

## What This Demo Shows

A factory floor with three machines generating sensor data. When an anomaly is detected, an **autonomous AI agent** analyzes the data, creates a SAP PM Notification, and publishes it through AEM to SAP Build BPA for human approval. Once approved, the agent creates a Work Order, which gets routed to a technician's mobile device — all event-driven through AEM.

**Demo timeline (~3-5 minutes):**

1. Sensors publish readings to AEM
2. Agent detects anomaly via LLM analysis
3. Agent creates PM Notification → published to AEM
4. SAP Build BPA picks up the notification → human approves
5. BPA publishes approval event → agent receives it
6. Agent creates PM Work Order → published to AEM
7. Technician's mobile device receives the work order

Every step is a real event flowing through Solace AEM. There are no point-to-point integrations.

---

## Architecture at a Glance

```
┌──────────────┐  sensors  ┌────────────────┐  notification  ┌──────────┐
│  Sensor Sim  ├──────────►│                │◄──────────────►│  SAP     │
└──────────────┘           │  SAP Advanced  │                │  Build   │
                           │  Event Mesh    │                │  BPA     │
┌──────────────┐  events   │   (Solace)     │   workorder    └──────────┘
│  AI Agent    │◄─────────►│                │
│  (MCP +      │           │                │
│   LLM)       │           └────────────────┘
└──────────────┘                   │
                                   │ events
                                   ▼
                           ┌────────────────┐
                           │  Web Dashboard │
                           │  (this repo)   │
                           └────────────────┘
```

For the full architecture explanation, see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Repository Structure

```
sap-pm-demo/
├── README.md                  ← you are here
├── ARCHITECTURE.md            ← architecture deep-dive
├── DEPLOYMENT.md              ← step-by-step EC2 deployment
├── DEMO_GUIDE.md              ← talking points + demo script for field team
├── LICENSE                    ← Apache 2.0
├── .gitignore
│
├── agent/                     ← Maintenance agent stack (Python)
│   ├── agent.py               ← LLM-driven autonomous agent
│   ├── mcp_server/server.py   ← MCP server (sensor data + AEM publishing)
│   ├── simulator/             ← Sensor data simulator
│   ├── requirements.txt
│   ├── .env.example           ← Copy to .env, fill in your credentials
│   └── README.md
│
├── web/                       ← Web dashboard + future tech screens
│   ├── dashboard.html         ← Live event monitor
│   ├── static/
│   │   ├── solclient.js       ← Solace JavaScript API
│   │   └── ...
│   └── README.md
│
├── specs/                     ← AsyncAPI / OpenAPI specs for SAP Build
│   ├── asyncapi-pm-notification-pending.json
│   ├── asyncapi-pm-notification-enriched.json
│   ├── asyncapi-workorder-pending.json
│   └── openapi-pm-notification-action.json
│
└── deploy/                    ← Deployment artifacts
    ├── nginx/                 ← nginx config snippets
    ├── systemd/               ← systemd unit files (future)
    └── scripts/
```

---

## Quick Start

### Run on EC2 (recommended for live demos)

See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for the full step-by-step guide.

```bash
# On your EC2 instance:
cd /home/ubuntu/sap/ai
git clone https://github.com/SolaceLabs/sap-pm-demo.git pm-demo
cd pm-demo/agent
cp .env.example .env
# Edit .env with your AEM and LLM credentials
pip install -r requirements.txt
./run_simulator.sh   # in one terminal
python mcp_server/server.py   # in another terminal
python agent.py   # in another terminal
```

Open the dashboard:
```
http://ec2-54-219-47-90.us-west-1.compute.amazonaws.com:9080/sap-pm-demo/dashboard
```

### Run locally (for development)

Same as above, but on your laptop. The dashboard needs to be served from a web server (it won't work as `file://` due to WebSocket security). Quick option:

```bash
cd web/
python -m http.server 8000
# Open http://localhost:8000/dashboard.html
```

---

## Prerequisites

- **SAP Advanced Event Mesh (AEM)** broker accessible from your environment (Solace Cloud or on-prem)
- **SAP Build BPA** workspace (for the approval workflow)
- **LLM API access** — OpenAI, Anthropic, or compatible
- **Python 3.11+** for the agent stack
- **Modern browser** for the dashboard (Chrome, Safari, Firefox)

---

## Demo URLs

When deployed to EC2 + CloudFront, the demo lives under these paths:

| What | URL Path |
|------|----------|
| Live event dashboard | `/sap-pm-demo/dashboard` |
| Architecture diagram (interactive) | `/sap-pm-demo/architecture` |
| Demo guide for field team | `/sap-pm-demo/docs/demo-guide` |
| Technician QR claim page (future) | `/sap-pm-demo/technician` |

These work both directly via EC2 (HTTP on port 9080) and via the CloudFront HTTPS distribution.

---

## For SAP Field Teams

If you're an AE or SE running this demo for a customer:

1. **Read [`DEMO_GUIDE.md`](./DEMO_GUIDE.md)** for talking points and the demo script
2. **Review [`ARCHITECTURE.md`](./ARCHITECTURE.md)** to be ready for technical questions
3. **Pre-flight check** the demo URLs in your browser before walking into the meeting

---

## Contributing

This is a SolaceLabs demo project. To contribute:

1. Fork the repo
2. Make changes on a feature branch
3. Submit a pull request with a clear description

For substantial changes, open an issue first to discuss.

---

## License

Apache 2.0 — see [`LICENSE`](./LICENSE).

---

## Acknowledgments

Built by the Solace SAP Tech Team. Uses:
- [Solace PubSub+](https://solace.com/products/event-broker/)
- [SAP Advanced Event Mesh](https://www.sap.com/products/technology-platform/advanced-event-mesh.html)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [CloudEvents specification](https://cloudevents.io/)
- [AsyncAPI specification](https://www.asyncapi.com/)
