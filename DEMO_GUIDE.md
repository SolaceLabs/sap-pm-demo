# Demo Guide

A field-team playbook for running the SAP PM Demo with customers. This document covers:

1. Pre-demo checklist
2. Demo script (3-minute, 5-minute, 10-minute versions)
3. Talking points by audience type
4. Common questions and how to answer them
5. Recovery moves if things go wrong

---

## Pre-Demo Checklist

Do this **at least 30 minutes before** the customer meeting.

### Infrastructure
- [ ] EC2 instance is running
- [ ] All three agent processes started (simulator, MCP server, agent) — verify with `ps aux | grep python`
- [ ] AEM connection working from dashboard — open the dashboard URL and click Connect
- [ ] You can see sensor events streaming in the dashboard
- [ ] SAP Build BPA workspace is open in a separate browser tab and connected to the same AEM

### Browser Setup
- [ ] Dashboard open and connected: `http://ec2-54-219-47-90.us-west-1.compute.amazonaws.com:9080/sap-pm-demo/dashboard` (or your CloudFront URL)
- [ ] Architecture diagram open in another tab: `/sap-pm-demo/architecture`
- [ ] SAP Build BPA workspace in another tab
- [ ] Browser zoomed appropriately for the screen you'll project on (usually 110-125%)
- [ ] No distracting browser bookmarks or open tabs

### Demo State Reset
- [ ] Click "Clear" on the dashboard event feed (clean slate)
- [ ] Verify no pending notifications in BPA from previous demos

### Backup Plan
- [ ] Screen-recorded demo video on local laptop (in case live demo fails)
- [ ] Architecture diagram PDF or screenshots
- [ ] Have the talking points and key URLs written down somewhere accessible

---

## The 3-Minute Demo (Elevator Pitch)

Use when time is tight, attention is short, or you're testing interest before committing to longer demos.

### Setup the Scene (15 seconds)
> "What you're about to see is a working demo of how SAP customers can build event-driven AI on top of their existing SAP investments. We have a factory floor with three machines. They're publishing sensor data into SAP Advanced Event Mesh. An AI agent is watching."

### Wait for Anomaly + PM Notification (60 seconds)
- Dashboard shows sensor events streaming
- About 60 seconds in, machine-02 anomaly triggers
- The dashboard's "Anomaly Detection" stage blinks
- Soon after, the "PM Notification Created" stage blinks

> "There — the AI agent just analyzed the sensor trend, classified this as a critical malfunction, and created a SAP PM Notification. It's now flowing through AEM to SAP Build BPA for approval."

### Switch to BPA (45 seconds)
- Show the notification appearing in BPA
- Approver clicks Approve

> "Notice — the agent didn't call BPA's API. It published an event. BPA subscribed to that event independently. This is event-driven architecture in action."

### Back to Dashboard for Work Order (30 seconds)
- Show the approval event arriving
- Show the Work Order being created
- Show the tablet popup

> "BPA published the approval back to AEM. The agent received it, created a Work Order, and the work order is now flowing to the technician's mobile device. End-to-end: about 3 seconds of automated processing, plus however long the human takes to click approve."

### The Punchline (30 seconds)
> "This entire flow uses zero point-to-point integrations. Every component just publishes and subscribes to events on AEM. If we wanted to add a Slack notification, a CFO dashboard, a partner system, we'd just add a new subscriber. No changes to anything else.
> 
> This is the architectural pattern SAP customers need for their AI strategy. AEM is the foundation."

---

## The 5-Minute Demo (Standard)

The 3-minute version plus:

- Show the **architecture diagram** (1 minute) before triggering the anomaly. Walk through the components left-to-right, emphasizing the event mesh in the middle.
- Spend more time on the **BPA notification details** — show the SAP-native field names (notification_id, equipment_id, priority, etc.) so customers see this is real SAP, not a toy.
- Show **multiple events flowing through AEM** in the live feed to reinforce volume and parallelism.

---

## The 10-Minute Demo (Deep Dive)

The 5-minute version plus:

- Open the **AsyncAPI spec** in SAP Build, show how BPA subscribed using a standards-based contract (~2 minutes)
- Walk through the **CloudEvent envelope structure** in the dashboard's "Current Event Payload" panel (~2 minutes)
- Show **wildcards in action** — explain how the dashboard subscribes to `factory/line-A/+/notification/+` to catch every notification event with one subscription (~1 minute)

---

## Audience-Specific Talking Points

The same demo, different framing depending on who's in the room.

### For SAP Integration Architects / iFlow Developers

**Hook:** *"How many point-to-point integrations are you maintaining between SAP and surrounding systems?"*

**Key points:**
- This entire flow has **zero iFlows, zero CPI, zero point-to-point**
- AEM is the integration layer
- New integrations are just new subscribers — no code changes elsewhere
- AsyncAPI specs are the contract — discoverable, versionable, importable by SAP Build

**What they need to hear:** AEM doesn't replace iFlows. It's the foundation that makes integration simpler, faster, and more resilient. It works alongside what they already have.

### For SAP Functional Consultants (PM / MM / FI)

**Hook:** *"What if AI could trigger PM Notifications using real SAP fields and processes?"*

**Key points:**
- The notification uses real SAP PM fields: notification_type, priority, damage_code, cause_code
- The work order uses real SAP PM order types: PM01, PM02, PM03
- This isn't a "wrapper" around SAP — it speaks SAP's language natively
- The agent could (in production) be triggered by ANY SAP event, not just sensor data

**What they need to hear:** AI agents don't replace SAP processes. They add intelligence on top of existing SAP workflows.

### For Business Stakeholders (Plant Manager, COO)

**Hook:** *"What if your approvers could make decisions in seconds instead of hours?"*

**Key points:**
- The PM Notification arrives with full context — not just "machine broken"
- The approver makes informed decisions, not blind ones
- The work order routes automatically to the right technician's device
- Total time from anomaly to technician notification: under a minute (vs. hours/days in traditional flows)

**What they need to hear:** This isn't about cool AI. It's about reducing MTTR, increasing OEE, and avoiding bad decisions made with incomplete data.

### For CIO / Enterprise Architect

**Hook:** *"You're going to need an event-driven foundation for your agentic AI strategy. Where will it come from?"*

**Key points:**
- AI agents need to be triggered by real-world events, not just chat
- Multiple agents will collaborate; you need a substrate for A2A communication
- Audit trails will become regulatory requirements for AI decisions
- AEM provides all of this as managed infrastructure

**What they need to hear:** AEM is the equivalent of the integration platform for the AI era. Not having one is a structural problem.

---

## Common Questions & How to Answer

### "Is this just MQTT? We already have MQTT."
> "AEM speaks MQTT, but it's much more than that. It's a mesh — meaning brokers in different regions form a single logical broker. Events published in one region flow to subscribers in another automatically. It also handles topic-level ACLs, replay, schema validation, and CloudEvents natively. MQTT alone gives you the protocol. AEM gives you the operational platform."

### "What's special about CloudEvents?"
> "CloudEvents is the industry standard event envelope. It's supported by AWS EventBridge, Azure Event Grid, Kafka Connect, Knative — basically every modern eventing platform. Using CloudEvents means our events are portable. If you ever wanted to bridge to AWS or Azure, you wouldn't have to translate event formats."

### "Why MCP and not just function calling?"
> "MCP is becoming the standard for agent-tool integration. Anthropic created it, OpenAI is adopting it, the ecosystem is converging. Using MCP means the agent isn't locked to one LLM. We could swap GPT-4 for Claude or for a local Llama model without changing the MCP server at all."

### "How does this work with SAP Joule?"
> "Joule is SAP's AI copilot inside SAP — helping users navigate, ask questions, do work in the SAP UI. What you're seeing here is complementary: autonomous AI that's triggered by events, not by humans typing. Joule talks to humans. This kind of agent talks to other systems. Together, they're the complete AI fabric for an SAP environment."

### "What's the realistic effort to deploy this in our environment?"
> "The agent stack and dashboard you're seeing is open-source on GitHub — you can clone it today. The main work is connecting it to your real sensor data and real SAP. That's typically a few weeks of integration work for a pilot, depending on the complexity of your existing landscape. Solace can help with that."

### "How does this scale?"
> "AEM is built for scale. A single broker handles 100s of thousands of messages per second. The mesh capability means you can geographically distribute load. The pattern you see here — agents subscribing to topics — scales linearly with the number of agents. Add a new agent, it subscribes to relevant topics, it participates. No central orchestrator to become a bottleneck."

### "What if the LLM gives bad advice?"
> "The agent's actions go through human approval via SAP Build BPA. The LLM doesn't directly modify SAP. It proposes — humans approve. That keeps you in control. Over time, as confidence grows, you can move some decisions to fully autonomous (e.g., reordering parts under $X), but that's a deliberate choice."

### "Doesn't event-driven make debugging harder?"
> "Two answers. One: AEM has built-in observability — every event is captured, you can replay sequences, you can trace events across topics. Two: every event is a CloudEvent with a unique ID. You can correlate events across the entire mesh by that ID. In practice, it's often *easier* to debug than point-to-point because the audit trail is automatic."

---

## Recovery Moves (If Things Go Wrong)

### The agent isn't detecting the anomaly
- Wait an extra 30 seconds — the LLM call takes time
- Check the agent terminal for errors (rate limit, API key)
- If broken: switch to architecture diagram, narrate the flow conceptually

### Dashboard shows "Disconnected"
- Click Settings → Reconnect
- If WSS connection failed, the AEM cloud broker might be unreachable from the customer's network — check with them
- Fall back to: video of the demo (have it ready)

### BPA isn't picking up the notification
- Verify BPA workspace is in the same AEM
- Verify subscription is to the right topic
- If broken: explain the flow verbally, show payload in the dashboard, move on

### Customer is bored / not engaging
- Pause the demo
- Ask: "Does this resemble anything you're trying to do today?"
- Pivot to whatever they're actually struggling with — the demo is the canvas, not the message

### Customer is too engaged / asking too many technical questions
- Don't go deeper than you can confidently answer
- Take notes, promise to follow up with SE
- This is a great problem to have — they're hooked

---

## After the Demo

Recommended close:

> "If this resonates with what you're trying to build, the natural next step is a 60-90 minute architecture workshop where we map this pattern to your specific environment. I can set that up. What would be a good week?"

The architecture workshop is the conversion. The demo plants the seed. Don't try to close the sale in the demo.

---

## Materials to Share After

- Link to this repo: `https://github.com/SolaceLabs/sap-pm-demo`
- Architecture diagram (HTML or PDF)
- Specific section of the AEM Field Guide that matches their industry
- (Don't share `.env` files, credentials, or anything internal)

---

## Demo Improvement Loop

After each demo, jot down in the repo's issue tracker:
- What worked
- What didn't
- Questions you couldn't answer
- Improvements customers requested

This is how the demo gets better over time. Don't keep these insights in your head.
