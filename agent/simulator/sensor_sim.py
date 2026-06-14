"""
Sensor Simulator for SAP PM Demo

Generates realistic sensor data for three machines (machine-01, machine-02, machine-03)
and publishes to AEM via MQTT/Solace.

Topics published:
  factory/line-A/{machine_id}/sensors

Each reading includes:
  - temperature (°C)
  - vibration (Hz)
  - pressure (bar)
  - motor_current (A)
  - drift_factor (0.0-1.0, machine-02 only — simulates bearing failure)

Run with:
    python simulator/sensor_sim.py

NOTE: This file is a starter template. If you have an existing sensor simulator from
the auto-mfg-agent-dev project, replace this file with that one. The agent and dashboard
will work with any simulator that publishes the topic/payload format above.
"""

import os
import ssl
import json
import time
import random
import logging
import signal
import sys
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# ── Setup ────────────────────────────────────────────────────────────────────

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

# ── Sensor data generation ───────────────────────────────────────────────────

# Track drift for machine-02 (simulates progressive bearing failure)
machine_state = {
    "machine-02": {
        "drift_factor": 0.0,
        "drift_active": False,
    }
}

# Operating ranges (normal):
#   Temperature: 65-85°C
#   Vibration:   45-55 Hz
#   Pressure:    5.5-6.5 bar
#   Motor:       10-14 A

def generate_reading(machine_id: str) -> dict:
    """Generate one sensor reading for a machine."""
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Base normal values with slight noise
    temp = 75 + random.uniform(-3, 3)
    vibration = 50 + random.uniform(-2, 2)
    pressure = 6.0 + random.uniform(-0.2, 0.2)
    motor = 12 + random.uniform(-0.5, 0.5)
    drift = 0.0
    
    # machine-02 has progressive drift if anomaly is active
    if machine_id == "machine-02" and machine_state["machine-02"]["drift_active"]:
        drift = machine_state["machine-02"]["drift_factor"]
        # Drift increases over time
        machine_state["machine-02"]["drift_factor"] = min(1.0, drift + 0.01)
        # As drift increases, sensors deviate
        temp += drift * 15  # rises toward 90°C
        vibration += drift * 15  # rises toward 65 Hz
    
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


# ── MQTT setup ───────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to Solace broker at %s:%s", SOLACE_HOST, SOLACE_PORT)
    else:
        log.error("MQTT connection failed — rc=%s", rc)


def on_disconnect(client, userdata, rc, properties=None, reason=None):
    log.warning("Disconnected from broker (rc=%s). Will auto-reconnect.", rc)


def make_client() -> mqtt.Client:
    client = mqtt.Client(client_id="sensor-simulator", protocol=mqtt.MQTTv5)
    client.username_pw_set(SOLACE_USERNAME, SOLACE_PASSWORD)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    
    if USE_TLS:
        ctx = ssl.create_default_context()
        if SOLACE_CA_CERT:
            ctx.load_verify_locations(cafile=SOLACE_CA_CERT)
        client.tls_set_context(ctx)
    
    client.connect(SOLACE_HOST, SOLACE_PORT, keepalive=60)
    client.loop_start()
    return client


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("Starting sensor simulator")
    log.info("Broker: %s:%s  VPN: %s", SOLACE_HOST, SOLACE_PORT, SOLACE_VPN)
    
    client = make_client()
    
    # Graceful shutdown
    running = True
    def shutdown(sig, frame):
        nonlocal running
        log.info("Shutting down...")
        running = False
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    log.info("Publishing sensor data every %d seconds", PUBLISH_INTERVAL_SEC)
    log.info("Press Ctrl+C to stop")
    
    # Optional: start anomaly on machine-02 after a delay
    anomaly_start_time = None
    if os.getenv("AUTO_ANOMALY", "true").lower() == "true":
        delay_sec = int(os.getenv("ANOMALY_DELAY_SEC", "60"))
        log.info("Anomaly on machine-02 will start in %d seconds", delay_sec)
        anomaly_start_time = time.time() + delay_sec
    
    while running:
        # Check if anomaly should start
        if anomaly_start_time and time.time() >= anomaly_start_time:
            if not machine_state["machine-02"]["drift_active"]:
                log.warning("🚨 ANOMALY STARTED on machine-02 — bearing degradation")
                machine_state["machine-02"]["drift_active"] = True
                anomaly_start_time = None  # only trigger once
        
        # Publish readings for all machines
        for machine_id in MACHINES:
            reading = generate_reading(machine_id)
            topic = f"factory/line-A/{machine_id}/sensors"
            try:
                client.publish(topic, json.dumps(reading), qos=1)
                log.info("Published to %s: T=%.1f V=%.1f", 
                         topic, reading["temperature"], reading["vibration"])
            except Exception as exc:
                log.error("Failed to publish: %s", exc)
        
        time.sleep(PUBLISH_INTERVAL_SEC)
    
    client.loop_stop()
    client.disconnect()
    log.info("Simulator stopped")


if __name__ == "__main__":
    main()
