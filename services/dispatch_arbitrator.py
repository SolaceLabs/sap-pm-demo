"""
Dispatch Arbitrator for SAP PM Demo

Manages the availability pool when the demo presenter shows the QR code to the
audience. When the work order is created, picks the first technician from the
pool and broadcasts the assignment.

Topics subscribed:
  factory/line-A/dispatch/qr-shown          - presenter clicked Show QR (new round)
  factory/line-A/dispatch/availability      - phone tapped "I'm Available"
  factory/line-A/+/workorder/created        - agent created a work order (trigger assignment)
  factory/line-A/control/demo/reset         - hard reset, clear pool

Topics published:
  factory/line-A/dispatch/assignment        - winner selected (round_id + winner_tech_id + WO data)
  factory/line-A/dispatch/pool-update       - someone joined the pool (live counter update)

Pool logic:
  - First-in-pool wins
  - Each phone has a tech_id (random, browser-generated)
  - Duplicates are deduplicated by tech_id
  - Round is bounded by round_id (incremented each time QR is shown)
  - Stale availability events (wrong round_id) are ignored
"""

import os
import ssl
import json
import logging
import signal
import uuid
import threading
from collections import OrderedDict
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("dispatch-arbitrator")

load_dotenv()

SOLACE_HOST     = os.getenv("SOLACE_HOST",     "localhost")
SOLACE_PORT     = int(os.getenv("SOLACE_PORT", "8883"))
SOLACE_VPN      = os.getenv("SOLACE_VPN",      "default")
SOLACE_USERNAME = os.getenv("SOLACE_USERNAME", "admin")
SOLACE_PASSWORD = os.getenv("SOLACE_PASSWORD", "admin")
SOLACE_CA_CERT  = os.getenv("SOLACE_CA_CERT",  None)
USE_TLS         = SOLACE_PORT != 1883

# Subscribe topics
SUBSCRIBE_TOPICS = [
    "factory/line-A/dispatch/qr-shown",
    "factory/line-A/dispatch/availability",
    "factory/line-A/+/workorder/created",
    "factory/line-A/control/demo/reset",
]

# Publish topics
TOPIC_ASSIGNMENT  = "factory/line-A/dispatch/assignment"
TOPIC_POOL_UPDATE = "factory/line-A/dispatch/pool-update"

# State (with lock for thread-safety because paho callbacks run in a separate thread)
state_lock = threading.Lock()
state = {
    "round_id": None,
    "round_active": False,
    "pool": OrderedDict(),  # tech_id -> joined_at iso string, preserves insertion order
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def cloudevent(event_type, data):
    """Wrap a payload in a CloudEvents envelope."""
    return {
        "specversion": "1.0",
        "type": event_type,
        "source": "urn:com:factory:line-A:dispatch-arbitrator",
        "id": str(uuid.uuid4()),
        "time": now_iso(),
        "datacontenttype": "application/json",
        "data": data,
    }


def publish(client, topic, payload):
    """Publish a CloudEvent-wrapped payload."""
    if client is None or not client.is_connected():
        log.warning("Client not connected; cannot publish to %s", topic)
        return
    try:
        client.publish(topic, json.dumps(payload), qos=1)
    except Exception as exc:
        log.error("Failed to publish to %s: %s", topic, exc)


def broadcast_pool_update(client):
    """Broadcast current pool size so dashboards and phones can show live count."""
    with state_lock:
        snapshot = {
            "round_id": state["round_id"],
            "round_active": state["round_active"],
            "pool_size": len(state["pool"]),
            "pool_tech_ids": list(state["pool"].keys()),
        }
    publish(client, TOPIC_POOL_UPDATE, cloudevent("com.factory.dispatch.pool.update.v1", snapshot))
    log.info("Pool update broadcast: round=%s, size=%d", snapshot["round_id"], snapshot["pool_size"])


def handle_qr_shown(client, payload):
    """Presenter showed QR code - start a new round, clear pool."""
    new_round = payload.get("round_id") or str(uuid.uuid4())[:8]
    with state_lock:
        old_round = state["round_id"]
        state["round_id"] = new_round
        state["round_active"] = True
        state["pool"] = OrderedDict()
    log.info("New dispatch round started: %s (previous: %s)", new_round, old_round)
    broadcast_pool_update(client)


def handle_availability(client, payload):
    """A phone tapped 'I'm Available'."""
    tech_id = payload.get("tech_id")
    round_id = payload.get("round_id")
    if not tech_id:
        log.warning("Availability event missing tech_id, ignoring")
        return

    with state_lock:
        current_round = state["round_id"]
        round_active = state["round_active"]

    if not round_active:
        log.info("Availability from %s rejected: no active round", tech_id)
        return
    if round_id and round_id != current_round:
        log.info("Availability from %s rejected: stale round (%s != %s)", tech_id, round_id, current_round)
        return

    with state_lock:
        if tech_id in state["pool"]:
            log.info("Availability from %s: already in pool (dedupe)", tech_id)
            return
        state["pool"][tech_id] = now_iso()

    log.info("Tech %s joined pool", tech_id)
    broadcast_pool_update(client)


def handle_workorder_created(client, topic, payload):
    """Work order was just created - pick a winner from the pool and broadcast assignment."""
    # Topic: factory/line-A/{machine_id}/workorder/created
    parts = topic.split("/")
    machine_id = parts[2] if len(parts) >= 4 else "unknown"

    # The work order payload might be in a CloudEvents data field
    wo_data = payload.get("data", payload) if "type" in payload else payload

    with state_lock:
        current_round = state["round_id"]
        pool_copy = list(state["pool"].items())
        # Close the round
        state["round_active"] = False

    if not pool_copy:
        log.warning("Work order created (machine=%s) but pool is EMPTY - no assignment possible",
                    machine_id)
        # Broadcast an "unassigned" event so dashboards/phones know
        assignment = {
            "round_id": current_round,
            "winner_tech_id": None,
            "pool_size": 0,
            "machine_id": machine_id,
            "work_order": wo_data,
            "status": "unassigned",
            "reason": "no_available_technicians",
        }
        publish(client, TOPIC_ASSIGNMENT, cloudevent("com.factory.dispatch.assignment.v1", assignment))
        return

    # First-in-pool wins
    winner_tech_id, joined_at = pool_copy[0]
    loser_tech_ids = [tid for tid, _ in pool_copy[1:]]

    assignment = {
        "round_id": current_round,
        "winner_tech_id": winner_tech_id,
        "loser_tech_ids": loser_tech_ids,
        "pool_size": len(pool_copy),
        "machine_id": machine_id,
        "work_order": wo_data,
        "status": "assigned",
    }
    publish(client, TOPIC_ASSIGNMENT, cloudevent("com.factory.dispatch.assignment.v1", assignment))
    log.info("ASSIGNMENT: round=%s winner=%s (pool had %d)", current_round, winner_tech_id, len(pool_copy))


def handle_demo_reset(client, payload):
    """Demo was reset - clear pool and stop any active round."""
    with state_lock:
        state["round_id"] = None
        state["round_active"] = False
        state["pool"] = OrderedDict()
    log.info("Demo reset: pool cleared, round ended")
    broadcast_pool_update(client)


# MQTT callbacks

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to Solace broker at %s:%s", SOLACE_HOST, SOLACE_PORT)
        for topic in SUBSCRIBE_TOPICS:
            client.subscribe(topic, qos=1)
            log.info("Subscribed: %s", topic)
    else:
        log.error("MQTT connection failed - rc=%s", rc)


def on_disconnect(client, userdata, rc, properties=None, reason=None):
    log.warning("Disconnected from broker (rc=%s). Will auto-reconnect.", rc)


def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode("utf-8")
        payload = json.loads(payload_str) if payload_str else {}

        # If payload looks like a CloudEvent, unwrap the data field for handlers that want raw data
        # but some handlers want the topic and whole payload too
        unwrapped = payload.get("data", payload) if isinstance(payload, dict) and payload.get("type") else payload

        topic = msg.topic
        log.debug("Received message on %s", topic)

        if topic == "factory/line-A/dispatch/qr-shown":
            handle_qr_shown(client, unwrapped if isinstance(unwrapped, dict) else {})
        elif topic == "factory/line-A/dispatch/availability":
            handle_availability(client, unwrapped if isinstance(unwrapped, dict) else {})
        elif "/workorder/created" in topic:
            handle_workorder_created(client, topic, payload)
        elif topic == "factory/line-A/control/demo/reset":
            handle_demo_reset(client, unwrapped if isinstance(unwrapped, dict) else {})
        else:
            log.debug("Unhandled topic: %s", topic)
    except Exception as exc:
        log.error("Failed to process message on %s: %s", msg.topic, exc, exc_info=True)


def make_client():
    client = mqtt.Client(client_id="dispatch-arbitrator", protocol=mqtt.MQTTv5)
    client.username_pw_set(SOLACE_USERNAME, SOLACE_PASSWORD)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    if USE_TLS:
        ctx = ssl.create_default_context()
        if SOLACE_CA_CERT:
            ctx.load_verify_locations(cafile=SOLACE_CA_CERT)
        client.tls_set_context(ctx)

    client.connect(SOLACE_HOST, SOLACE_PORT, keepalive=60)
    client.loop_start()
    return client


def main():
    log.info("Starting dispatch arbitrator")
    log.info("Broker: %s:%s  VPN: %s", SOLACE_HOST, SOLACE_PORT, SOLACE_VPN)

    client = make_client()

    running = [True]
    def shutdown(sig, frame):
        log.info("Shutting down...")
        running[0] = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("Dispatch arbitrator running. Press Ctrl+C to stop.")
    import time
    while running[0]:
        time.sleep(1)

    client.loop_stop()
    client.disconnect()
    log.info("Dispatch arbitrator stopped")


if __name__ == "__main__":
    main()
