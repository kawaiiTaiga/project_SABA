#!/usr/bin/env python3
import os, sys
import paho.mqtt.client as mqtt

HOST = os.getenv("MQTT_HOST","127.0.0.1")
PORT = int(os.getenv("MQTT_PORT","1883"))

def log(*a,**k): print(*a, file=sys.stderr, flush=True, **k)

def on_connect(c,u,f,rc,p=None):
    log(f"[sniff] connected rc={rc} host={HOST}:{PORT}")
    c.subscribe("mcp/#")

def on_message(c,u,m):
    try: s = m.payload.decode("utf-8","ignore")
    except: s = f"<{len(m.payload)} bytes>"
    log(f"[sniff] {m.topic}: {s[:200]}")

cli = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
cli.on_connect = on_connect; cli.on_message = on_message
cli.connect(HOST, PORT, keepalive=60)
cli.loop_forever(retry_first_connection=True)