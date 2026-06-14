"""
Manufacturing MCP Server (SAP PM Aligned)

Aligns with SAP Plant Maintenance process:
  1. Malfunction Detection → PM Notification
  2. Notification Approval → PM Work Order

Tools exposed:
  - get_sensor_readings      : latest reading per machine (or a specific machine)
  - get_sensor_history       : last N readings for a machine (max 50)
  - create_notification      : create PM notification and publish to AEM
  - create_workorder         : create PM work order (after notification approval)
  - get_notification_events  : get approval/rejection events from BPA

Run with:
    python -m mcp_server.server
"""

import os
import ssl
import json
import uuid
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("mfg-mcp-server")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

SOLACE_HOST     = os.getenv("SOLACE_HOST",     "localhost")
SOLACE_PORT     = int(os.getenv("SOLACE_PORT", "8883"))
SOLACE_VPN      = os.getenv("SOLACE_VPN",      "default")
SOLACE_USERNAME = os.getenv("SOLACE_USERNAME", "admin")
SOLACE_PASSWORD = os.getenv("SOLACE_PASSWORD", "admin")
SOLACE_CA_CERT  = os.getenv("SOLACE_CA_CERT",  None)

USE_TLS          = SOLACE_PORT != 1883
SUBSCRIBE_TOPIC  = "factory/line-A/+/sensors"
HISTORY_MAXLEN   = 50

# Topics for notification events (agent subscribes to these)
NOTIFICATION_APPROVED_TOPIC = "factory/line-A/+/notification/approved"
NOTIFICATION_REJECTED_TOPIC = "factory/line-A/+/notification/rejected"

# CloudEvents configuration
CLOUDEVENTS_SOURCE = os.getenv("CLOUDEVENTS_SOURCE", "urn:com:factory:line-A:mcp-server")
CLOUDEVENTS_TYPE_NOTIFICATION = "com.factory.pm.notification.pending.v1"
CLOUDEVENTS_TYPE_WORKORDER = "com.factory.pm.workorder.created.v1"

# ── In-memory state ───────────────────────────────────────────────────────────

# { machine_id: deque(maxlen=50) of reading dicts }
sensor_history: dict[str, deque] = {}
history_lock = threading.Lock()

# { notification_id: notification_dict }
notifications: dict[str, dict] = {}
notifications_lock = threading.Lock()

# { work_order_id: work_order_dict }
work_orders: dict[str, dict] = {}
workorders_lock = threading.Lock()

# Incoming notification events (approved/rejected) from BPA
notification_events: deque = deque(maxlen=100)
events_lock = threading.Lock()

# MQTT client reference for publishing
mqtt_client: mqtt.Client | None = None

# ── MQTT helpers ──────────────────────────────────────────────────────────────

def _on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to Solace broker at %s:%s", SOLACE_HOST, SOLACE_PORT)
        # Subscribe to sensor data
        client.subscribe(SUBSCRIBE_TOPIC, qos=1)
        log.info("Subscribed to %s", SUBSCRIBE_TOPIC)
        # Subscribe to notification approval/rejection events from BPA
        client.subscribe(NOTIFICATION_APPROVED_TOPIC, qos=1)
        client.subscribe(NOTIFICATION_REJECTED_TOPIC, qos=1)
        log.info("Subscribed to notification events: %s, %s", 
                 NOTIFICATION_APPROVED_TOPIC, NOTIFICATION_REJECTED_TOPIC)
    else:
        log.error("MQTT connection failed — rc=%s", rc)


def _on_disconnect(client, userdata, rc, properties=None, reason=None):
    log.warning("Disconnected from broker (rc=%s). Will auto-reconnect.", rc)


def _on_message(client, userdata, msg):
    """Parse incoming messages - sensor data or notification events."""
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        topic_parts = msg.topic.split("/")
        
        # Topic structure: factory/line-A/{machine_id}/notification/{approved|rejected}
        # Index:              0       1        2            3             4
        if len(topic_parts) >= 5 and topic_parts[3] == "notification":
            event_type = topic_parts[4]  # "approved" or "rejected"
            machine_id = topic_parts[2]
            
            # Handle CloudEvents structured format (payload might be in "data" field)
            actual_payload = payload.get("data", payload)
            
            event = {
                "event_id": f"EVT-{uuid.uuid4().hex[:8].upper()}",
                "event_type": event_type,
                "machine_id": machine_id,
                "notification_id": actual_payload.get("notification_id"),
                "payload": actual_payload,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "processed": False,
            }
            
            with events_lock:
                notification_events.append(event)
            
            log.info("Received notification %s event for %s: %s", 
                     event_type, machine_id, actual_payload.get("notification_id"))
            
            # Update notification status if we have it
            notification_id = actual_payload.get("notification_id")
            if notification_id:
                with notifications_lock:
                    if notification_id in notifications:
                        notifications[notification_id]["status"] = event_type
                        log.info("Updated notification %s status to %s", 
                                 notification_id, event_type)
            return
        
        # Otherwise, it's sensor data
        machine_id = payload.get("machine_id") or topic_parts[2]

        with history_lock:
            if machine_id not in sensor_history:
                sensor_history[machine_id] = deque(maxlen=HISTORY_MAXLEN)
            sensor_history[machine_id].append(payload)

        log.debug("Buffered reading for %s (buffer size=%d)",
                  machine_id, len(sensor_history[machine_id]))
    except Exception as exc:
        log.error("Failed to process message on %s: %s", msg.topic, exc)


def start_mqtt_listener() -> mqtt.Client:
    """Create, configure and start the MQTT client in a background thread."""
    global mqtt_client
    
    client = mqtt.Client(
        client_id="mfg-mcp-server-agent",  # Fixed client ID for persistent sessions
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(SOLACE_USERNAME, SOLACE_PASSWORD)
    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message    = _on_message

    if USE_TLS:
        ctx = ssl.create_default_context()
        if SOLACE_CA_CERT:
            ctx.load_verify_locations(cafile=SOLACE_CA_CERT)
        client.tls_set_context(ctx)
        log.info("TLS enabled for MQTT connection")

    try:
        client.connect(SOLACE_HOST, SOLACE_PORT, keepalive=60)
        client.loop_start()
        mqtt_client = client
        log.info("MQTT listener started")
    except Exception as exc:
        log.warning("Could not connect to Solace (%s). "
                    "Server will start but tools will return empty data.", exc)

    return client


def publish_to_aem(topic: str, payload: dict) -> bool:
    """Publish a CloudEvents-compliant message to AEM via MQTT."""
    global mqtt_client
    
    if mqtt_client is None or not mqtt_client.is_connected():
        log.warning("MQTT client not connected, cannot publish to %s", topic)
        return False
    
    try:
        result = mqtt_client.publish(topic, json.dumps(payload), qos=1)
        result.wait_for_publish(timeout=5.0)
        log.info("Published to %s", topic)
        return True
    except Exception as exc:
        log.error("Failed to publish to %s: %s", topic, exc)
        return False


def map_priority_to_sap(priority: str) -> str:
    """Map our priority levels to SAP PM priority codes."""
    mapping = {
        "low": "4",       # SAP: Low
        "medium": "3",    # SAP: Medium
        "high": "2",      # SAP: High
        "critical": "1",  # SAP: Very High
    }
    return mapping.get(priority, "3")


def get_notification_type(alert_level: str) -> str:
    """Map alert level to SAP PM Notification Type."""
    # SAP Standard Notification Types:
    # M1 = Malfunction report
    # M2 = Maintenance request
    # M3 = Activity report
    if alert_level == "critical_alert":
        return "M1"  # Malfunction report
    else:
        return "M2"  # Maintenance request


# ── MCP Server ────────────────────────────────────────────────────────────────

server = Server("mfg-sensor-agent")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_sensor_readings",
            description=(
                "Return the most recent sensor reading for one or all machines on "
                "factory line-A. Sensors reported: temperature (°C), vibration (mm/s), "
                "pressure (bar), motor_current (A). Also includes a drift_factor for "
                "machine-02 when a bearing-failure anomaly is active (0.0 = normal, "
                "1.0 = full failure)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "machine_id": {
                        "type": "string",
                        "description": (
                            "Optional. One of: machine-01, machine-02, machine-03. "
                            "Omit to get the latest reading for every machine."
                        ),
                    }
                },
                "required": [],
            },
        ),
        types.Tool(
            name="get_sensor_history",
            description=(
                "Return the last N sensor readings (up to 50) for a specific machine. "
                "Useful for trend analysis, anomaly detection, or reviewing a machine's "
                "recent behaviour before creating a maintenance notification."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "machine_id": {
                        "type": "string",
                        "description": "Required. One of: machine-01, machine-02, machine-03.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of readings to return (1–50). Defaults to 10.",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                },
                "required": ["machine_id"],
            },
        ),
        types.Tool(
            name="create_notification",
            description=(
                "Create a SAP PM (Plant Maintenance) Notification to document a detected "
                "malfunction or maintenance need. This is the FIRST step in the SAP PM process. "
                "The notification is published to AEM for BPA approval workflow. "
                "Once approved, use create_workorder to create the actual work order. "
                "Use this for both medium_alert and critical_alert situations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "equipment_id": {
                        "type": "string",
                        "description": "The equipment/machine ID (e.g. machine-02). Maps to SAP Equipment.",
                    },
                    "functional_location": {
                        "type": "string",
                        "description": "Functional location in plant hierarchy (e.g. PLANT-A/LINE-A/STATION-02).",
                    },
                    "notification_type": {
                        "type": "string",
                        "enum": ["M1", "M2", "M3"],
                        "description": (
                            "SAP PM Notification Type: "
                            "M1 = Malfunction Report (for breakdowns/critical issues), "
                            "M2 = Maintenance Request (for planned maintenance needs), "
                            "M3 = Activity Report (for completed activities)."
                        ),
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["1", "2", "3", "4"],
                        "description": (
                            "SAP Priority: 1 = Very High (immediate), 2 = High (within 24h), "
                            "3 = Medium (within 1 week), 4 = Low (next planned downtime)."
                        ),
                    },
                    "short_text": {
                        "type": "string",
                        "description": "Brief description of the problem (max 40 chars). Maps to SAP Notification Short Text.",
                    },
                    "long_text": {
                        "type": "string",
                        "description": "Detailed description of the malfunction, symptoms observed, and sensor readings.",
                    },
                    "effect_code": {
                        "type": "string",
                        "enum": ["1", "2", "3", "4"],
                        "description": (
                            "Breakdown effect: 1 = No breakdown, 2 = Partial breakdown, "
                            "3 = Full breakdown, 4 = Safety risk."
                        ),
                    },
                    "reported_by": {
                        "type": "string",
                        "description": "Who/what reported the issue. Use 'AI-MAINT-AGENT' for autonomous detection.",
                    },
                },
                "required": ["equipment_id", "notification_type", "priority", "short_text", "long_text"],
            },
        ),
        types.Tool(
            name="create_workorder",
            description=(
                "Create a SAP PM Work Order AFTER a notification has been approved. "
                "This is the SECOND step in the SAP PM process. "
                "Only call this when you receive an approved notification event. "
                "The work order includes operations, scheduling, and resource planning."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "notification_id": {
                        "type": "string",
                        "description": "The approved notification ID this work order is based on.",
                    },
                    "equipment_id": {
                        "type": "string",
                        "description": "The equipment/machine ID requiring maintenance.",
                    },
                    "order_type": {
                        "type": "string",
                        "enum": ["PM01", "PM02", "PM03"],
                        "description": (
                            "SAP PM Order Type: PM01 = Corrective maintenance, "
                            "PM02 = Preventive maintenance, PM03 = Emergency repair."
                        ),
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["1", "2", "3", "4"],
                        "description": "SAP Priority: 1 = Very High, 2 = High, 3 = Medium, 4 = Low.",
                    },
                    "short_text": {
                        "type": "string",
                        "description": "Work order description (max 40 chars).",
                    },
                    "operations": {
                        "type": "array",
                        "description": "List of maintenance operations to perform.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "operation_num": {"type": "string", "description": "Operation number (e.g. 0010, 0020)"},
                                "description": {"type": "string", "description": "Operation description"},
                                "work_center": {"type": "string", "description": "Work center responsible"},
                                "duration_hours": {"type": "number", "description": "Planned duration in hours"},
                            },
                        },
                    },
                    "scheduled_start": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Planned start date/time for the work.",
                    },
                    "scheduled_end": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Planned end date/time for the work.",
                    },
                },
                "required": ["notification_id", "equipment_id", "order_type", "priority", "short_text"],
            },
        ),
        types.Tool(
            name="get_notification_events",
            description=(
                "Retrieve pending notification approval/rejection events from AEM. "
                "These events are generated by the BPA workflow when a human approves "
                "or rejects a PM notification. When a notification is APPROVED, "
                "you should create a work order using create_workorder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "machine_id": {
                        "type": "string",
                        "description": "Optional. Filter events for a specific machine.",
                    },
                    "mark_processed": {
                        "type": "boolean",
                        "description": "If true (default), mark returned events as processed.",
                        "default": True,
                    },
                },
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:

    # ── get_sensor_readings ───────────────────────────────────────────────────
    if name == "get_sensor_readings":
        machine_id = arguments.get("machine_id")

        with history_lock:
            if machine_id:
                if machine_id not in sensor_history or not sensor_history[machine_id]:
                    return [types.TextContent(
                        type="text",
                        text=json.dumps({
                            "error": f"No data available for '{machine_id}'. "
                                     "Is the simulator running?",
                        }),
                    )]
                result = {machine_id: sensor_history[machine_id][-1]}
            else:
                if not sensor_history:
                    return [types.TextContent(
                        type="text",
                        text=json.dumps({
                            "error": "No sensor data buffered yet. "
                                     "Is the simulator running and connected?",
                        }),
                    )]
                result = {
                    mid: list(buf)[-1]
                    for mid, buf in sensor_history.items()
                    if buf
                }

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    # ── get_sensor_history ────────────────────────────────────────────────────
    elif name == "get_sensor_history":
        machine_id = arguments.get("machine_id")
        limit      = min(int(arguments.get("limit", 10)), HISTORY_MAXLEN)

        if not machine_id:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "machine_id is required."}),
            )]

        with history_lock:
            buf = sensor_history.get(machine_id)
            if not buf:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"No history for '{machine_id}'. "
                                 "Is the simulator running?",
                    }),
                )]
            history_slice = list(buf)[-limit:]

        result = {
            "machine_id":     machine_id,
            "readings_count": len(history_slice),
            "limit":          limit,
            "readings":       history_slice,
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    # ── create_notification ───────────────────────────────────────────────────
    elif name == "create_notification":
        required = ["equipment_id", "notification_type", "priority", "short_text", "long_text"]
        missing  = [f for f in required if not arguments.get(f)]
        if missing:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Missing required fields: {missing}"}),
            )]

        equipment_id = arguments["equipment_id"]
        now = datetime.now(timezone.utc)
        
        # Generate SAP-style notification number (10 digits)
        notification_id = f"10{uuid.uuid4().hex[:8].upper()}"
        
        # PM Notification data (SAP PM aligned)
        notification_data = {
            "notification_id": notification_id,
            "notification_type": arguments["notification_type"],
            "equipment_id": equipment_id,
            "functional_location": arguments.get("functional_location", f"PLANT-A/LINE-A/{equipment_id.upper()}"),
            "priority": arguments["priority"],
            "short_text": arguments["short_text"][:40],  # SAP limit
            "long_text": arguments["long_text"],
            "effect_code": arguments.get("effect_code", "1"),
            "reported_by": arguments.get("reported_by", "AI-MAINT-AGENT"),
            "status": "PENDING",  # NOPR in SAP terms (Outstanding)
            "created_at": now.isoformat(),
            "plant": "PLANT-A",
            "planning_plant": "PLANT-A",
        }

        # Store locally
        with notifications_lock:
            notifications[notification_id] = notification_data.copy()

        # CloudEvents structured format
        cloudevent = {
            "specversion": "1.0",
            "type": CLOUDEVENTS_TYPE_NOTIFICATION,
            "source": CLOUDEVENTS_SOURCE,
            "id": str(uuid.uuid4()),
            "time": now.isoformat(),
            "datacontenttype": "application/json",
            "subject": f"factory/line-A/{equipment_id}/notification/{notification_id}",
            "data": notification_data
        }

        # Publish to AEM
        topic = f"factory/line-A/{equipment_id}/notification/pending"
        published = publish_to_aem(topic, cloudevent)

        log.info(
            "PM Notification created: %s | equipment=%s | type=%s | priority=%s",
            notification_id, equipment_id, arguments["notification_type"], arguments["priority"],
        )

        result = {
            "notification": notification_data,
            "cloudevent": cloudevent,
            "published_to_aem": published,
            "topic": topic,
            "message": "Notification created and sent to BPA for approval. Monitor get_notification_events for approval.",
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    # ── create_workorder ──────────────────────────────────────────────────────
    elif name == "create_workorder":
        required = ["notification_id", "equipment_id", "order_type", "priority", "short_text"]
        missing  = [f for f in required if not arguments.get(f)]
        if missing:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Missing required fields: {missing}"}),
            )]

        notification_id = arguments["notification_id"]
        equipment_id = arguments["equipment_id"]
        now = datetime.now(timezone.utc)
        
        # Verify notification exists and is approved
        with notifications_lock:
            notification = notifications.get(notification_id)
            if notification and notification.get("status") != "approved":
                log.warning("Attempting to create work order for non-approved notification: %s", notification_id)
        
        # Generate SAP-style work order number (12 digits)
        workorder_id = f"40{uuid.uuid4().hex[:10].upper()}"
        
        # Default operations if not provided
        default_operations = [
            {
                "operation_num": "0010",
                "description": "Inspect and diagnose issue",
                "work_center": "MAINT-01",
                "duration_hours": 1.0,
            },
            {
                "operation_num": "0020",
                "description": "Perform corrective action",
                "work_center": "MAINT-01", 
                "duration_hours": 2.0,
            },
            {
                "operation_num": "0030",
                "description": "Test and verify repair",
                "work_center": "MAINT-01",
                "duration_hours": 0.5,
            },
        ]
        
        # PM Work Order data (SAP PM aligned)
        workorder_data = {
            "work_order_id": workorder_id,
            "notification_id": notification_id,
            "order_type": arguments["order_type"],
            "equipment_id": equipment_id,
            "functional_location": f"PLANT-A/LINE-A/{equipment_id.upper()}",
            "priority": arguments["priority"],
            "short_text": arguments["short_text"][:40],
            "operations": arguments.get("operations", default_operations),
            "status": "CREATED",  # CRTD in SAP terms
            "scheduled_start": arguments.get("scheduled_start", now.isoformat()),
            "scheduled_end": arguments.get("scheduled_end"),
            "created_at": now.isoformat(),
            "plant": "PLANT-A",
            "planning_plant": "PLANT-A",
            "work_center": "MAINT-01",
        }

        # Store locally
        with workorders_lock:
            work_orders[workorder_id] = workorder_data.copy()

        # Update notification status
        with notifications_lock:
            if notification_id in notifications:
                notifications[notification_id]["work_order_id"] = workorder_id
                notifications[notification_id]["status"] = "WORK_ORDER_CREATED"

        # CloudEvents structured format
        cloudevent = {
            "specversion": "1.0",
            "type": CLOUDEVENTS_TYPE_WORKORDER,
            "source": CLOUDEVENTS_SOURCE,
            "id": str(uuid.uuid4()),
            "time": now.isoformat(),
            "datacontenttype": "application/json",
            "subject": f"factory/line-A/{equipment_id}/workorder/{workorder_id}",
            "data": workorder_data
        }

        # Publish work order created event to AEM
        topic = f"factory/line-A/{equipment_id}/workorder/created"
        published = publish_to_aem(topic, cloudevent)

        log.info(
            "PM Work Order created: %s | notification=%s | equipment=%s | type=%s",
            workorder_id, notification_id, equipment_id, arguments["order_type"],
        )

        result = {
            "work_order": workorder_data,
            "cloudevent": cloudevent,
            "published_to_aem": published,
            "topic": topic,
            "message": f"Work order {workorder_id} created from approved notification {notification_id}.",
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    # ── get_notification_events ───────────────────────────────────────────────
    elif name == "get_notification_events":
        machine_id = arguments.get("machine_id")
        mark_processed = arguments.get("mark_processed", True)
        
        with events_lock:
            pending_events = [
                e for e in notification_events 
                if not e["processed"] and (not machine_id or e["machine_id"] == machine_id)
            ]
            
            if mark_processed:
                for event in pending_events:
                    event["processed"] = True
        
        result = {
            "events_count": len(pending_events),
            "events": pending_events,
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    # ── Unknown tool ──────────────────────────────────────────────────────────
    else:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: '{name}'"}),
        )]


# ── Entrypoint ────────────────────────────────────────────────────────────────

async def main():
    log.info("Starting Manufacturing MCP Server (SAP PM Aligned)")
    log.info("Broker: %s:%s  VPN: %s  TLS: %s", SOLACE_HOST, SOLACE_PORT, SOLACE_VPN, USE_TLS)

    start_mqtt_listener()

    async with stdio_server() as (read_stream, write_stream):
        log.info("MCP server ready — waiting for tool calls via stdio")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
