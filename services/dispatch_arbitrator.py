"""
Multi-Tenant Dispatch Arbitrator for SAP PM Demo

Uses wildcard subscriptions to handle any SE namespace dynamically.
Pools and rounds are tracked per namespace.

Topics subscribed (wildcards):
  factory/+/dispatch/qr-shown          - presenter clicked Show QR
  factory/+/dispatch/availability      - phone tapped "I'm Available"
  factory/+/+/workorder/created        - agent created a work order
  factory/+/control/demo/reset         - hard reset

Topics published (per namespace):
  factory/{name}/dispatch/assignment   - winner selected
  factory/{name}/dispatch/pool-update  - pool size updated
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

# Wildcard subscriptions for all namespaces
SUBSCRIBE_TOPICS = [
    "factory/+/dispatch/qr-shown",
    "factory/+/dispatch/availability",
    "factory/+/+/workorder/created",
    "factory/+/control/demo/reset",
]

# Per-namespace state: { namespace: { round_id, round_active, pool } }
state_lock = threading.Lock()
ns_state = {}


def get_ns(namespace):
    """Get or create state for a namespace."""
    with state_lock:
        if namespace not in ns_state:
            ns_state[namespace] = {
                "round_id": None,
                "round_active": False,
                "pool": OrderedDict(),
            }
        return ns_state[namespace]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def cloudevent(event_type, data, namespace):
    return {
        "specversion": "1.0",
        "type": event_type,
        "source": f"urn:com:factory:{namespace}:dispatch-arbitrator",
        "id": str(uuid.uuid4()),
        "time": now_iso(),
        "datacontenttype": "application/json",
        "data": data,
    }


def publish(client, topic, payload):
    if client is None or not client.is_connected():
        return
    try:
        client.publish(topic, json.dumps(payload), qos=1)
    except Exception as exc:
        log.error("Publish failed %s: %s", topic, exc)


def broadcast_pool_update(client, namespace):
    st = get_ns(namespace)
    with state_lock:
        snapshot = {
            "round_id": st["round_id"],
            "round_active": st["round_active"],
            "pool_size": len(st["pool"]),
            "pool_tech_ids": list(st["pool"].keys()),
        }
    topic = f"factory/{namespace}/dispatch/pool-update"
    publish(client, topic, cloudevent("com.factory.dispatch.pool.update.v1", snapshot, namespace))
    log.info("[%s] Pool update: size=%d", namespace, snapshot["pool_size"])


def handle_qr_shown(client, namespace, payload):
    new_round = payload.get("round_id") or str(uuid.uuid4())[:8]
    st = get_ns(namespace)
    with state_lock:
        st["round_id"] = new_round
        st["round_active"] = True
        st["pool"] = OrderedDict()
    log.info("[%s] New dispatch round: %s", namespace, new_round)
    broadcast_pool_update(client, namespace)


def handle_availability(client, namespace, payload):
    tech_id = payload.get("tech_id")
    round_id = payload.get("round_id")
    if not tech_id:
        return

    st = get_ns(namespace)
    with state_lock:
        if not st["round_active"]:
            return
        if round_id and round_id != st["round_id"]:
            return
        if tech_id in st["pool"]:
            return
        st["pool"][tech_id] = now_iso()

    log.info("[%s] Tech %s joined pool", namespace, tech_id)
    broadcast_pool_update(client, namespace)


def handle_workorder_created(client, namespace, topic, payload):
    parts = topic.split("/")
    machine_id = parts[2] if len(parts) >= 4 else "unknown"
    wo_data = payload.get("data", payload) if "type" in payload else payload

    st = get_ns(namespace)
    with state_lock:
        pool_copy = list(st["pool"].items())
        st["round_active"] = False

    if not pool_copy:
        log.warning("[%s] WO created but pool EMPTY", namespace)
        assignment = {
            "round_id": st["round_id"],
            "winner_tech_id": None,
            "pool_size": 0,
            "machine_id": machine_id,
            "work_order": wo_data,
            "status": "unassigned",
            "reason": "no_available_technicians",
        }
        topic_out = f"factory/{namespace}/dispatch/assignment"
        publish(client, topic_out, cloudevent("com.factory.dispatch.assignment.v1", assignment, namespace))
        return

    winner_tech_id, _ = pool_copy[0]
    loser_tech_ids = [tid for tid, _ in pool_copy[1:]]

    assignment = {
        "round_id": st["round_id"],
        "winner_tech_id": winner_tech_id,
        "loser_tech_ids": loser_tech_ids,
        "pool_size": len(pool_copy),
        "machine_id": machine_id,
        "work_order": wo_data,
        "status": "assigned",
    }
    topic_out = f"factory/{namespace}/dispatch/assignment"
    publish(client, topic_out, cloudevent("com.factory.dispatch.assignment.v1", assignment, namespace))
    log.info("[%s] ASSIGNED: winner=%s (pool=%d)", namespace, winner_tech_id, len(pool_copy))


def handle_demo_reset(client, namespace):
    with state_lock:
        if namespace in ns_state:
            ns_state[namespace] = {
                "round_id": None,
                "round_active": False,
                "pool": OrderedDict(),
            }
    log.info("[%s] Demo reset: pool cleared", namespace)
    broadcast_pool_update(client, namespace)


# ── MQTT callbacks ───────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to Solace broker at %s:%s", SOLACE_HOST, SOLACE_PORT)
        for topic in SUBSCRIBE_TOPICS:
            client.subscribe(topic, qos=1)
            log.info("Subscribed: %s", topic)
    else:
        log.error("Connection failed: rc=%s", rc)


def on_disconnect(client, userdata, rc, properties=None, reason=None):
    log.warning("Disconnected (rc=%s). Auto-reconnecting.", rc)


def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode("utf-8")
        payload = json.loads(payload_str) if payload_str else {}
        unwrapped = payload.get("data", payload) if isinstance(payload, dict) and payload.get("type") else payload
        topic = msg.topic
        parts = topic.split("/")

        # Extract namespace from topic: factory/{namespace}/...
        if len(parts) < 3:
            return
        namespace = parts[1]

        if "/dispatch/qr-shown" in topic:
            handle_qr_shown(client, namespace, unwrapped if isinstance(unwrapped, dict) else {})
        elif "/dispatch/availability" in topic:
            handle_availability(client, namespace, unwrapped if isinstance(unwrapped, dict) else {})
        elif "/workorder/created" in topic:
            handle_workorder_created(client, namespace, topic, payload)
        elif "/control/demo/reset" in topic:
            handle_demo_reset(client, namespace)

    except Exception as exc:
        log.error("Error on %s: %s", msg.topic, exc, exc_info=True)


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
    log.info("Starting multi-tenant dispatch arbitrator")
    log.info("Broker: %s:%s  VPN: %s", SOLACE_HOST, SOLACE_PORT, SOLACE_VPN)

    client = make_client()

    running = [True]
    def shutdown(sig, frame):
        running[0] = False
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("Arbitrator running. Handling any namespace dynamically.")
    import time
    while running[0]:
        time.sleep(1)

    client.loop_stop()
    client.disconnect()
    log.info("Arbitrator stopped")


if __name__ == "__main__":
    main()
