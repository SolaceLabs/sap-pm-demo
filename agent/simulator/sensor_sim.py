"""
Sensor Simulator for SAP PM Demo

Generates realistic sensor data for three machines (machine-01, machine-02, machine-03)
and publishes to AEM via MQTT/Solace.

DEMO CONTROL (Phase 1):
  The simulator subscribes to factory/line-A/control/+/+ topics so the dashboard
  can drive the demo via control events. Default state: STOPPED (publishes baseline
  readings only, no anomaly).

  Control events the simulator reacts to:
    factory/line-A/control/demo/start       -> demo active (no behavior change yet)
    factory/line-A/control/demo/stop        -> demo stopped, drift cleared
    factory/line-A/control/demo/reset       -> hard reset: drift cleared, counters reset
    factory/line-A/control/anomaly/trigger  -> start machine-02 drift sequence

Topics published:
  factory/line-A/{machine_id}/sensors
  factory/line-A/control/demo/state         -> broadcasts current state to UI

Each reading includes:
  - temperature (degrees C)
  - vibration (Hz)
  - pressure (bar)
  - motor_current (A)
  - drift_factor (0.0-1.0, machine-02 only - simulates bearing failure)

Run with:
    python simulator/sensor_sim.py
"""

import os
import ssl
import json
import time
import random
import logging
import signal
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("sensor-sim")

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

# Control topics
CONTROL_SUBSCRIBE_TOPIC = "factory/line-A/control/+/+"
STATE_PUBLISH_TOPIC     = "factory/line-A/control/demo/state"

# Tracks whether anomaly drift is active on machine-02
machine_state = {
    "machine-02": {
        "drift_factor": 0.0,
        "drift_active": False,
    }
}

# Demo session state - set by control events
demo_state = {
    "active": False,
    "session_id": None,
}


def generate_reading(machine_id):
    """Generate one sensor reading for a machine."""
    timestamp = datetime.now(timezone.utc).isoformat()

    temp = 75 + random.uniform(-3, 3)
    vibration = 50 + random.uniform(-2, 2)
    pressure = 6.0 + random.uniform(-0.2, 0.2)
    motor = 12 + random.uniform(-0.5, 0.5)
    drift = 0.0

    if machine_id == "machine-02" and machine_state["machine-02"]["drift_active"]:
        drift = machine_state["machine-02"]["drift_factor"]
        machine_state["machine-02"]["drift_factor"] = min(1.0, drift + 0.03)
        temp += drift * 15
        vibration += drift * 15

    reading = {
        "machine_id": machine_id,
        "timestamp": timestamp,
        "temperature": round(temp, 2),
        "vibration": round(vibration, 2),
        "pressure": round(pressure, 2),
        "motor_current": round(motor, 2),
    }

    if machine_id == "machine-02":
        reading["drift_factor"] = round(drift, 2)

    return reading


def reset_machine_state():
    """Clear all anomaly drift state."""
    machine_state["machine-02"]["drift_factor"] = 0.0
    machine_state["machine-02"]["drift_active"] = False


def broadcast_state(client, status, message):
    """Publish a state-change event so dashboards can sync UI."""
    if client is None or not client.is_connected():
        return
    event = {
        "specversion": "1.0",
        "type": "com.factory.demo.state.v1",
        "source": "urn:com:factory:line-A:simulator",
        "id": str(uuid.uuid4()),
        "time": datetime.now(timezone.utc).isoformat(),
        "datacontenttype": "application/json",
        "data": {
            "status": status,
            "message": message,
            "demo_active": demo_state["active"],
            "session_id": demo_state["session_id"],
            "anomaly_active": machine_state["machine-02"]["drift_active"],
        },
    }
    try:
        client.publish(STATE_PUBLISH_TOPIC, json.dumps(event), qos=1)
        log.info("State broadcast: %s - %s", status, message)
    except Exception as exc:
        log.error("Failed to broadcast state: %s", exc)


def handle_control_event(client, topic, payload):
    """React to demo control events from the dashboard."""
    parts = topic.split("/")
    if len(parts) < 5:
        log.warning("Ignoring malformed control topic: %s", topic)
        return

    category = parts[3]
    action = parts[4]

    log.info("Control event received: %s/%s", category, action)

    if category == "demo" and action == "start":
        demo_state["active"] = True
        demo_state["session_id"] = payload.get("session_id") or str(uuid.uuid4())[:8]
        broadcast_state(client, "ACTIVE", "Demo started (session " + str(demo_state["session_id"]) + ")")

    elif category == "demo" and action == "stop":
        demo_state["active"] = False
        reset_machine_state()
        broadcast_state(client, "STOPPED", "Demo stopped by user")

    elif category == "demo" and action == "reset":
        reason = payload.get("reason", "manual")
        demo_state["active"] = False
        demo_state["session_id"] = None
        reset_machine_state()
        broadcast_state(client, "RESET", "Demo reset (" + reason + ")")

    elif category == "anomaly" and action == "trigger":
        if not machine_state["machine-02"]["drift_active"]:
            log.warning("ANOMALY TRIGGERED on machine-02 - bearing degradation starts now")
            machine_state["machine-02"]["drift_active"] = True
            machine_state["machine-02"]["drift_factor"] = 0.05
            broadcast_state(client, "ANOMALY_ACTIVE", "Anomaly triggered on machine-02")
        else:
            log.info("Anomaly already active on machine-02, ignoring trigger")

    else:
        log.info("Unhandled control event: %s/%s", category, action)


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to Solace broker at %s:%s", SOLACE_HOST, SOLACE_PORT)
        client.subscribe(CONTROL_SUBSCRIBE_TOPIC, qos=1)
        log.info("Subscribed to control topics: %s", CONTROL_SUBSCRIBE_TOPIC)
        broadcast_state(client, "READY", "Simulator connected, awaiting commands")
    else:
        log.error("MQTT connection failed - rc=%s", rc)


def on_disconnect(client, userdata, rc, properties=None, reason=None):
    log.warning("Disconnected from broker (rc=%s). Will auto-reconnect.", rc)


def on_message(client, userdata, msg):
    """Route incoming messages - currently only control events."""
    try:
        payload_str = msg.payload.decode("utf-8")
        payload = json.loads(payload_str) if payload_str else {}

        # Unwrap CloudEvents envelope if present
        if isinstance(payload, dict) and "data" in payload and "type" in payload:
            payload = payload.get("data") or {}

        handle_control_event(client, msg.topic, payload)
    except Exception as exc:
        log.error("Failed to process control message on %s: %s", msg.topic, exc)


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
    log.info("Starting sensor simulator (Phase 1: demo-controlled mode)")
    log.info("Broker: %s:%s  VPN: %s", SOLACE_HOST, SOLACE_PORT, SOLACE_VPN)
    log.info("Anomalies are TRIGGERED by the dashboard - no auto-anomaly")

    client = make_client()

    running = True
    def shutdown(sig, frame):
        nonlocal running
        log.info("Shutting down...")
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("Publishing sensor data every %d seconds", PUBLISH_INTERVAL_SEC)
    log.info("Press Ctrl+C to stop")

    while running:
        # Only publish sensor data when the demo is active.
        # This prevents the agent from seeing data and creating
        # spurious notifications before the SE clicks "Start Demo".
        if not demo_state["active"]:
            time.sleep(PUBLISH_INTERVAL_SEC)
            continue

        for machine_id in MACHINES:
            reading = generate_reading(machine_id)
            topic = "factory/line-A/" + machine_id + "/sensors"
            try:
                client.publish(topic, json.dumps(reading), qos=1)
                is_anomaly = machine_id == "machine-02" and machine_state["machine-02"]["drift_active"]
                marker = "[!]" if is_anomaly else "[.]"
                log.info("%s Published to %s: T=%.1f V=%.1f",
                         marker, topic, reading["temperature"], reading["vibration"])
            except Exception as exc:
                log.error("Failed to publish: %s", exc)

        time.sleep(PUBLISH_INTERVAL_SEC)

    client.loop_stop()
    client.disconnect()
    log.info("Simulator stopped")


if __name__ == "__main__":
    main()
