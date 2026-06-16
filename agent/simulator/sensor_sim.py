"""
Multi-Tenant Sensor Simulator for SAP PM Demo

Subscribes to factory/+/control/+/+ so ANY namespace (SE name) is handled
dynamically. When an SE starts a demo, a new session is created with
independent machine states and drift tracking.

Control topics (per namespace):
  factory/{name}/control/demo/start       -> create session, start publishing
  factory/{name}/control/demo/stop        -> stop session, clear drift
  factory/{name}/control/demo/reset       -> hard reset: remove session
  factory/{name}/control/anomaly/trigger  -> start machine-02 drift

Publish topics (per namespace):
  factory/{name}/{machine_id}/sensors     -> sensor readings
  factory/{name}/control/demo/state       -> broadcasts session state
"""

import os
import ssl
import json
import time
import random
import signal
import logging
import threading
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("simulator")

load_dotenv()

SOLACE_HOST     = os.getenv("SOLACE_HOST",     "localhost")
SOLACE_PORT     = int(os.getenv("SOLACE_PORT", "8883"))
SOLACE_VPN      = os.getenv("SOLACE_VPN",      "default")
SOLACE_USERNAME = os.getenv("SOLACE_USERNAME", "admin")
SOLACE_PASSWORD = os.getenv("SOLACE_PASSWORD", "admin")
SOLACE_CA_CERT  = os.getenv("SOLACE_CA_CERT",  None)
USE_TLS         = SOLACE_PORT != 1883

PUBLISH_INTERVAL_SEC = 5
MACHINES = ["machine-01", "machine-02", "machine-03"]

# Multi-tenant: wildcard subscription catches all namespaces
CONTROL_SUBSCRIBE_TOPIC = "factory/+/control/+/+"

# Normal sensor ranges
NORMAL = {
    "temperature":  {"base": 75.0, "noise": 3.0},
    "vibration":    {"base": 50.0, "noise": 2.0},
    "pressure":     {"base":  6.0, "noise": 0.2},
    "motor_current":{"base": 12.0, "noise": 0.5},
}

# Anomaly drift targets
DRIFT_TARGETS = {
    "temperature":   115.0,
    "vibration":     120.0,
    "pressure":        2.5,
    "motor_current":  28.0,
}

DRIFT_RATE = 0.03  # per publish cycle

# ── Multi-tenant session state ───────────────────────────────
sessions_lock = threading.Lock()
sessions = {}  # namespace -> session dict


def create_session(namespace):
    """Create a fresh session for an SE."""
    return {
        "namespace": namespace,
        "active": True,
        "anomaly_triggered": False,
        "drift_progress": 0.0,
        "machine_drift": {},  # machine_id -> per-machine drift state
    }


def get_session(namespace, create=False):
    """Get or optionally create a session."""
    with sessions_lock:
        if namespace not in sessions and create:
            sessions[namespace] = create_session(namespace)
            log.info("Session created for '%s'", namespace)
        return sessions.get(namespace)


def remove_session(namespace):
    with sessions_lock:
        if namespace in sessions:
            del sessions[namespace]
            log.info("Session removed for '%s'", namespace)


# ── Sensor generation ────────────────────────────────────────

def generate_reading(machine_id, session):
    """Generate a sensor reading, applying drift if anomaly is triggered."""
    reading = {}
    drift_progress = session.get("drift_progress", 0.0)
    is_drifting = session.get("anomaly_triggered", False) and machine_id == "machine-02"

    for sensor, params in NORMAL.items():
        base = params["base"]
        noise = params["noise"]
        normal_value = base + random.uniform(-noise, noise)

        if is_drifting:
            target = DRIFT_TARGETS[sensor]
            drifted = base + (target - base) * drift_progress
            value = drifted + random.uniform(-noise * 0.5, noise * 0.5)
        else:
            value = normal_value

        reading[sensor] = round(value, 2)

    return reading


def publish_reading(client, namespace, machine_id, reading):
    """Publish a sensor reading for a specific namespace."""
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = {
        "machine_id": machine_id,
        "timestamp": timestamp,
        **reading,
    }
    topic = f"factory/{namespace}/{machine_id}/sensors"
    try:
        client.publish(topic, json.dumps(payload), qos=0)
    except Exception as e:
        log.error("Publish failed (%s): %s", topic, e)


def broadcast_state(client, namespace, session):
    """Broadcast session state so the dashboard can sync."""
    status = "STOPPED"
    if session and session.get("active"):
        status = "ANOMALY_ACTIVE" if session.get("anomaly_triggered") else "ACTIVE"

    payload = {
        "specversion": "1.0",
        "type": "com.factory.control.demo.state.v1",
        "source": f"urn:com:factory:{namespace}:simulator",
        "id": str(uuid.uuid4()),
        "time": datetime.now(timezone.utc).isoformat(),
        "datacontenttype": "application/json",
        "data": {
            "status": status,
            "namespace": namespace,
            "anomaly_triggered": session.get("anomaly_triggered", False) if session else False,
            "drift_progress": round(session.get("drift_progress", 0.0), 3) if session else 0.0,
        },
    }
    topic = f"factory/{namespace}/control/demo/state"
    try:
        client.publish(topic, json.dumps(payload), qos=0)
    except Exception as e:
        log.error("State broadcast failed (%s): %s", topic, e)


# ── MQTT callbacks ───────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to Solace broker at %s:%s", SOLACE_HOST, SOLACE_PORT)
        client.subscribe(CONTROL_SUBSCRIBE_TOPIC, qos=0)
        log.info("Subscribed: %s (multi-tenant wildcard)", CONTROL_SUBSCRIBE_TOPIC)
    else:
        log.error("Connection failed: rc=%s", rc)


def on_disconnect(client, userdata, rc, properties=None, reason=None):
    log.warning("Disconnected (rc=%s). Auto-reconnecting.", rc)


def on_message(client, userdata, msg):
    """Handle control events from any namespace."""
    try:
        topic_parts = msg.topic.split("/")
        # Expected: factory/{namespace}/control/{category}/{action}
        if len(topic_parts) < 5 or topic_parts[2] != "control":
            return

        namespace = topic_parts[1]
        category = topic_parts[3]
        action = topic_parts[4]

        payload = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        data = payload.get("data", payload) if isinstance(payload, dict) and payload.get("type") else payload

        if category == "demo":
            if action == "start":
                session = get_session(namespace, create=True)
                session["active"] = True
                session["anomaly_triggered"] = False
                session["drift_progress"] = 0.0
                broadcast_state(client, namespace, session)
                log.info("[%s] Demo STARTED", namespace)

            elif action == "stop":
                session = get_session(namespace)
                if session:
                    session["active"] = False
                    session["anomaly_triggered"] = False
                    session["drift_progress"] = 0.0
                    broadcast_state(client, namespace, session)
                log.info("[%s] Demo STOPPED", namespace)

            elif action == "reset":
                session = get_session(namespace)
                if session:
                    session["active"] = False
                    session["anomaly_triggered"] = False
                    session["drift_progress"] = 0.0
                    broadcast_state(client, namespace, session)
                remove_session(namespace)
                log.info("[%s] Demo RESET", namespace)

        elif category == "anomaly":
            if action == "trigger":
                session = get_session(namespace)
                if session and session["active"]:
                    session["anomaly_triggered"] = True
                    session["drift_progress"] = 0.0
                    broadcast_state(client, namespace, session)
                    log.info("[%s] Anomaly TRIGGERED on machine-02", namespace)

    except Exception as e:
        log.error("Error handling control event on %s: %s", msg.topic, e, exc_info=True)


# ── Main loop ────────────────────────────────────────────────

def make_client():
    client = mqtt.Client(client_id="sensor-simulator", protocol=mqtt.MQTTv5)
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
    log.info("Starting multi-tenant sensor simulator")
    log.info("Broker: %s:%s  VPN: %s", SOLACE_HOST, SOLACE_PORT, SOLACE_VPN)

    client = make_client()

    running = [True]
    def shutdown(sig, frame):
        running[0] = False
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("Simulator running. Waiting for SEs to start demos...")

    while running[0]:
        # Snapshot active sessions
        with sessions_lock:
            active = [(ns, dict(s)) for ns, s in sessions.items() if s.get("active")]

        for namespace, session in active:
            # Advance drift
            if session.get("anomaly_triggered") and session["drift_progress"] < 1.0:
                with sessions_lock:
                    if namespace in sessions:
                        sessions[namespace]["drift_progress"] = min(
                            1.0, sessions[namespace]["drift_progress"] + DRIFT_RATE
                        )
                        session = dict(sessions[namespace])

            # Publish sensor data for each machine
            for machine_id in MACHINES:
                reading = generate_reading(machine_id, session)
                publish_reading(client, namespace, machine_id, reading)

        time.sleep(PUBLISH_INTERVAL_SEC)

    client.loop_stop()
    client.disconnect()
    log.info("Simulator stopped")


if __name__ == "__main__":
    main()
