# Maintenance Agent Stack

This directory contains the Python agent stack that runs the live predictive maintenance demo.

## Components

| File | Purpose |
|------|---------|
| `agent.py` | Autonomous agent that calls the LLM and decides when to create PM Notifications |
| `mcp_server/server.py` | MCP server exposing sensor data and AEM publishing as tools |
| `simulator/sensor_sim.py` | Generates simulated sensor data published to AEM |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for environment variables |
| `run_agent.sh` | Helper to start the agent |
| `run_simulator.sh` | Helper to start the simulator |

## How It Fits Together

```
  ┌────────────────────────────────┐
  │  sensor_sim.py (simulator)     │
  │  publishes sensor readings     │
  └──────────────┬─────────────────┘
                 │ MQTT/Solace
                 ▼
       ┌──────────────────┐
       │   AEM Broker     │
       └────┬──────────┬──┘
            │          │
       sub  │          │  pub: PM Notification
            │          │
            ▼          │
  ┌────────────────────┴───────┐
  │  mcp_server/server.py      │
  │  • caches sensor readings  │
  │  • exposes MCP tools       │
  │  • publishes notifications │
  └────────────┬───────────────┘
               │ stdio (MCP protocol)
               ▼
       ┌──────────────────┐
       │   agent.py       │
       │  • calls LLM     │
       │  • orchestrates  │
       └──────────────────┘
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your AEM and LLM credentials

# 3. Verify credentials work
# (optional sanity check — uses curl to ping your LLM API)
```

## Running

You need **three terminals**, one for each component:

```bash
# Terminal 1: Sensor simulator
./run_simulator.sh

# Terminal 2: MCP server
python3 mcp_server/server.py

# Terminal 3: Agent
./run_agent.sh
```

The simulator publishes sensor readings every 5 seconds. By default, an anomaly on `machine-02` starts 60 seconds after the simulator launches (configurable via `ANOMALY_DELAY_SEC` env var). The agent runs a maintenance cycle every 60 seconds (configurable via `CHECK_INTERVAL`).

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Description |
|----------|-------------|
| `SOLACE_HOST` | Your AEM broker hostname |
| `SOLACE_VPN` | Message VPN name |
| `SOLACE_USERNAME` / `SOLACE_PASSWORD` | AEM credentials |
| `API_KEY` | LLM provider API key |
| `API_BASE` | LLM endpoint URL |
| `LLM_MODEL` | Model identifier (e.g., `gpt-4`, `claude-3-5-sonnet-20241022`) |

## Troubleshooting

**MCP server can't connect to AEM:**
- Verify `SOLACE_HOST`, port, and credentials in `.env`
- Check that EC2 (or your local machine) can reach the broker
- Try the connection test: `nc -zv $SOLACE_HOST $SOLACE_PORT`

**Agent says "no sensor data":**
- The simulator must be running and connected before the agent can query data
- Check the MCP server logs for "Buffered reading for..." messages

**LLM API errors:**
- Verify `API_KEY` is valid
- Verify `LLM_MODEL` matches your provider's available models
- Check rate limits

## Related Documentation

- [`../README.md`](../README.md) - top-level overview
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) - architecture details
- [`../DEPLOYMENT.md`](../DEPLOYMENT.md) - EC2 deployment guide
- [`../specs/`](../specs/) - AsyncAPI specs for SAP Build integration
