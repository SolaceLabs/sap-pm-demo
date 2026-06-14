# Architecture

This document explains how the SAP PM Demo works, why it's architected this way, and what value the architecture demonstrates to SAP customers.

---

## The Story This Architecture Tells

When you walk into a customer meeting and show this demo, the architecture itself is part of the message. Every component placement, every event flow, every integration choice is making a point about how SAP customers should think about event-driven architecture for AI.

The headline architecture point: **agents and SAP modules don't talk to each other directly. They talk to AEM.** This decoupling is the whole reason the demo works the way it does, and it's the whole reason AEM is valuable to SAP customers building AI strategies.

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       FACTORY FLOOR                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │machine-01  │  │machine-02  │  │machine-03  │                │
│  │ 📊 sensors │  │ 📊 sensors │  │ 📊 sensors │                │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘                │
│        │               │               │                        │
│        └───────────────┼───────────────┘                        │
│                        │                                         │
│                        ▼                                         │
│              ┌──────────────────┐                                │
│              │ Sensor Simulator │ (or real PLC/SCADA)            │
│              │  factory/line-A/ │                                │
│              │   +/sensors      │                                │
│              └────────┬─────────┘                                │
└───────────────────────┼──────────────────────────────────────────┘
                        │
                        │ publishes via MQTT
                        ▼
        ┌───────────────────────────────────┐
        │   SAP Advanced Event Mesh (AEM)   │
        │                                   │
        │   ┌─────────────────────────┐    │
        │   │  Topics                 │    │
        │   │  factory/line-A/        │    │
        │   │    +/sensors            │    │
        │   │    +/notification/      │    │
        │   │       pending           │    │
        │   │       approved          │    │
        │   │       rejected          │    │
        │   │    +/workorder/created  │    │
        │   └─────────────────────────┘    │
        └─────┬─────────────┬───────────┬──┘
              │             │           │
              │ subscribes  │           │ subscribes
              ▼             │           ▼
    ┌─────────────────┐    │   ┌──────────────────┐
    │  MCP Server     │    │   │  SAP Build BPA   │
    │  • caches data  │    │   │  • human approval│
    │  • publishes    │    │   │  • publishes     │
    │    PM events    │    │   │    decisions     │
    └────────┬────────┘    │   └────────┬─────────┘
             │             │            │
             │ stdio (MCP) │            │ publishes
             ▼             │            ▼
    ┌─────────────────┐    │   (back to AEM topics
    │  AI Agent       │    │    notification/approved
    │  • calls LLM    │    │    or .../rejected)
    │  • decides      │    │
    │  • orchestrates │    │
    └────────┬────────┘    │
             │             │
             │ stdio       │
             ▼             │
    ┌─────────────────┐    │
    │  Web Dashboard  │◄───┘ subscribes (visualization)
    │  (this repo)    │
    └─────────────────┘
```

---

## Component Responsibilities

### 1. Sensor Simulator
**What:** Python process that mimics factory sensors.  
**Where:** `agent/simulator/sensor_sim.py`  
**Talks to:** AEM (publishes sensor topics).  
**Why it exists for the demo:** Provides predictable, repeatable sensor data so the demo behaves the same way every time. In real deployments, this is replaced by actual PLC/SCADA integration via OPC-UA or MQTT gateways.

### 2. SAP Advanced Event Mesh (AEM)
**What:** The Solace event broker. The hub through which all events flow.  
**Where:** Solace Cloud or on-prem.  
**Why it's central:** AEM decouples publishers from subscribers. No component knows about any other component. Components only know about topics.

### 3. MCP Server
**What:** Python process implementing the [Model Context Protocol](https://modelcontextprotocol.io/). It exposes tools (functions) that the LLM-driven agent can call.  
**Where:** `agent/mcp_server/server.py`  
**Talks to:** AEM (subscribes to sensor topics, publishes PM events). Agent (via stdio MCP protocol).  
**Tools exposed:**
- `get_sensor_readings` — latest reading per machine
- `get_sensor_history` — last N readings for analysis
- `create_notification` — creates PM Notification, publishes to AEM
- `create_workorder` — creates PM Work Order after approval
- `get_notification_events` — checks for approval/rejection events

### 4. Maintenance Agent
**What:** Python process running an LLM (GPT-4, Claude, etc.) in a loop. The LLM is the "brain" — it analyzes sensor data and decides when to create PM Notifications.  
**Where:** `agent/agent.py`  
**Talks to:** MCP Server (via stdio). LLM API (via HTTPS).  
**How it works:**
1. Every 60 seconds, the agent calls the MCP server to check for pending approval events
2. Then it gets current sensor readings
3. It sends everything to the LLM with a SAP PM expert system prompt
4. The LLM decides whether to create notifications or work orders
5. The LLM calls MCP tools to act on its decisions

### 5. SAP Build BPA
**What:** SAP's Business Process Automation. The human-in-the-loop component.  
**Where:** SAP BTP / Build workspace.  
**Talks to:** AEM (subscribes to notification/pending, publishes approval/rejection).  
**Why it matters for SAP customers:** This is the SAP-native integration point. It's where the demo connects to existing SAP infrastructure. Customers see this and recognize "yes, this is how we already do approvals."

### 6. Web Dashboard
**What:** A static HTML/JS page that subscribes directly to AEM via WebSocket Secure (WSS).  
**Where:** `web/dashboard.html`  
**Talks to:** AEM (subscribes to all relevant topics for visualization).  
**Why it's a standalone client:** Demonstrates that AEM clients don't need a backend. Anyone with WSS credentials can subscribe. This is a powerful customer message: your AI dashboard, your mobile app, your kiosk, your reporting tool — all can subscribe directly.

---

## The Five Key Architectural Decisions

These are the choices that make the architecture worth showing to SAP customers. When customers ask "why did you build it this way?", these are your answers.

### Decision 1: Event-Driven via AEM, Not API-Driven

**The choice:** All inter-component communication goes through AEM as published events. There are no direct API calls between the agent, BPA, the dashboard, etc.

**Why:**
- **Decoupling.** The agent doesn't know BPA exists. BPA doesn't know about the agent. They just publish/subscribe to topics.
- **Scalability.** Adding a new subscriber (a mobile app, a Slack notifier, a metrics service) doesn't require changes anywhere else.
- **Resilience.** If a subscriber is down, events queue and replay. No data loss.
- **Audit trail.** Every interaction is a published event — automatically auditable.

**Customer takeaway:** *"We don't need point-to-point integrations between AI and SAP. We need an event mesh."*

### Decision 2: MCP for Agent-Tool Integration

**The choice:** The LLM-driven agent calls a Python MCP server via the Model Context Protocol, not custom function calls or REST APIs.

**Why:**
- **Standardization.** MCP is an emerging industry standard. Anthropic's Claude, OpenAI, and others are converging on it.
- **Portability.** The same MCP server works with any MCP-compatible LLM.
- **Tooling.** MCP Inspector and other dev tools make agent debugging easier.

**Customer takeaway:** *"Your AI investments aren't locked to one LLM vendor. MCP gives you optionality."*

### Decision 3: CloudEvents Payload Format

**The choice:** All events published to AEM follow the [CloudEvents](https://cloudevents.io/) specification.

**Why:**
- **Cross-platform compatibility.** CloudEvents is supported by AWS EventBridge, Azure Event Grid, Google Eventarc, Kafka, NATS, and more.
- **Self-describing events.** The `type`, `source`, `id`, `time`, `subject` fields make events independently meaningful.
- **Tooling ecosystem.** OTEL tracing, schema validation, replay tools all understand CloudEvents.

**Customer takeaway:** *"Your event payloads aren't proprietary. They're standards-based and portable."*

### Decision 4: AsyncAPI for Event Documentation

**The choice:** Every event topic is documented in an AsyncAPI 2.0 spec.

**Why:**
- **Discoverability.** Developers can browse the spec to learn what events exist and how to consume them.
- **SAP Build integration.** SAP Build BPA imports AsyncAPI specs to configure its event subscriptions and form fields.
- **Schema evolution.** AsyncAPI versions help teams manage backward compatibility.

**Customer takeaway:** *"Your events are contract-defined, not tribal knowledge. New teams can self-onboard."*

### Decision 5: SAP-Native Terminology Throughout

**The choice:** PM Notification numbers use SAP's 10-digit format. Equipment uses SAP terminology. The CloudEvent payloads use SAP-native field names (`material_number`, `personnel_number`, `cost_center`, etc.).

**Why:**
- **Customer recognition.** SAP customers see `release_strategy` in the payload and immediately understand what it means.
- **Easier integration.** When customers wire this to their real SAP systems, the field names already match.
- **Trust signal.** Using their language shows you understand their world.

**Customer takeaway:** *"This isn't a generic AI demo bolted onto SAP. It's SAP-aware from the ground up."*

---

## Topic Hierarchy

The event mesh uses a hierarchical topic structure that's easy to subscribe to with wildcards:

```
factory/line-A/{machine_id}/sensors
factory/line-A/{machine_id}/notification/pending
factory/line-A/{machine_id}/notification/approved
factory/line-A/{machine_id}/notification/rejected
factory/line-A/{machine_id}/workorder/created
```

**Subscribers can wildcard:**
- `factory/line-A/+/sensors` — all sensor data, any machine
- `factory/line-A/machine-02/+` — everything about machine-02
- `factory/>` — every event in the factory namespace

This is one of AEM's superpowers — high-cardinality routing without breaking a sweat. Customers used to message queues (where every queue is point-to-point) don't realize this is even possible until they see it.

---

## Event Payload Patterns

### Standard CloudEvent Envelope

Every event follows this structure:

```json
{
  "specversion": "1.0",
  "type": "com.factory.pm.notification.pending.v1",
  "source": "urn:com:factory:line-A:mcp-server",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "time": "2026-03-26T10:30:00.000Z",
  "datacontenttype": "application/json",
  "subject": "factory/line-A/machine-02/notification/10ABCD1234",
  "data": {
    /* event-specific payload */
  }
}
```

The `data` field varies by event type. See the JSON schemas in `specs/` for the full structure of each event.

### Version Convention

The `type` field includes a version suffix (`.v1`) so we can evolve schemas without breaking existing subscribers. To deprecate v1 in favor of v2:
- Publish events to both `.v1` and `.v2` types during transition
- New subscribers go to `.v2`
- Eventually deprecate `.v1`

This is a standard event-driven design pattern. Customers should adopt it.

---

## Security Notes

### Authentication
- AEM uses TLS for all connections
- Username/password authentication for the demo (Solace also supports certificate-based, OAuth, etc.)
- WSS (WebSocket Secure) for browser connections

### Authorization
- AEM supports topic-level ACLs (who can publish/subscribe to what topics)
- For production, you'd restrict each component to only the topics it needs

### Secrets Management
- Credentials in `.env` files, never committed to Git
- For production, use AWS Secrets Manager, HashiCorp Vault, or similar

---

## What This Architecture Demonstrates to SAP Customers

If you can leave a customer meeting with them having internalized these five points, the demo did its job:

1. **Event mesh is foundational infrastructure for AI in SAP environments.** Not nice-to-have — required.
2. **Decoupling matters.** Their AI agents shouldn't know about SAP. SAP shouldn't know about their AI agents. Both publish to topics.
3. **Standards (CloudEvents, AsyncAPI, MCP) reduce vendor lock-in.** Their AI investments stay portable.
4. **Mobile/dashboard/notification clients are trivial to add** when everything's on an event mesh.
5. **Audit trails come for free** when every action is a published event.

These five points map directly to AEM's value proposition. The demo is the proof.

---

## Where This Architecture Could Go Next

Future enhancements that could be added without restructuring:

- **Multi-agent orchestration via Solace Agent Mesh (SAM)** — multiple specialist agents (supply chain, workforce, finance) collaborating to enrich notifications before they reach BPA
- **Real SAP integration** — connect to actual S/4HANA PM module via the Event Mesh Gateway pattern
- **Mobile technician app** — phone-based work order acceptance via QR code scanning
- **External system integration** — partners, suppliers, customers subscribing to relevant events
- **Cross-plant coordination** — events from multiple factories on the same mesh

All of these are additive. The current architecture supports them without breaking changes.
