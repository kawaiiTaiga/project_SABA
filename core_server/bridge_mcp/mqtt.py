import threading
import uuid
import json
import paho.mqtt.client as mqtt
from typing import Optional, Callable
from .config import MQTT_HOST, MQTT_PORT, KEEPALIVE, SUB_ALL, TOPIC_ANN, TOPIC_STAT, TOPIC_EV, TOPIC_PORTS_ANN, TOPIC_PORTS_DATA
from .utils import log
from .device_store import DeviceStore
from .command import CommandWaiter
import secrets
import string

def generate_token(length=32):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

_mqtt_pub_client = None
_mqtt_pub_lock = threading.Lock()

def get_mqtt_pub_client():
    """재사용 가능한 MQTT publish 클라이언트"""
    global _mqtt_pub_client
    
    with _mqtt_pub_lock:
        if _mqtt_pub_client is None or not _mqtt_pub_client.is_connected():
            _mqtt_pub_client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"bridge-pub-{uuid.uuid4().hex[:6]}",
                protocol=mqtt.MQTTv5
            )
            _mqtt_pub_client.connect(MQTT_HOST, MQTT_PORT, keepalive=KEEPALIVE)
            _mqtt_pub_client.loop_start()
        return _mqtt_pub_client

def publish_to_inport(device_id: str, port_name: str, value: float) -> bool:
    """InPort로 값 발행 (ports/set 토픽)"""
    topic = f"mcp/dev/{device_id}/ports/set"
    payload = {
        "port": port_name,
        "value": value
    }
    
    try:
        client = get_mqtt_pub_client()
        result = client.publish(topic, json.dumps(payload), qos=0, retain=False)
        # log(f"[MQTT] Published to InPort: {device_id}/{port_name} = {value}")
        return result.rc == 0
    except Exception as e:
        # log(f"[MQTT] Failed to publish to InPort: {e}")
        return False

def parse_topic(topic: str):
    """토픽 파싱: mcp/dev/{device_id}/{leaf...}"""
    parts = topic.split("/")
    if len(parts) >= 4:
        device_id = parts[2]
        leaf = "/".join(parts[3:])  # ports/announce, ports/data 등 처리
        return device_id, leaf
    return None, None

def start_mqtt_listener(device_store: DeviceStore, cmd_waiter: CommandWaiter, port_store, port_router):
    def mqtt_thread():
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"bridge-mcp-{uuid.uuid4().hex[:6]}",
            protocol=mqtt.MQTTv5
        )
        client.enable_logger()

        def on_connect(c, userdata, flags, reason_code, properties=None):
            log(f"[mqtt] connected rc={reason_code} host={MQTT_HOST}:{MQTT_PORT}")
            if SUB_ALL:
                sub = ("mcp/#", 0)
                c.subscribe(sub)
                log(f"[mqtt] subscribe {sub}")
            else:
                c.subscribe(TOPIC_ANN); log(f"[mqtt] subscribe {TOPIC_ANN}")
                c.subscribe(TOPIC_STAT); log(f"[mqtt] subscribe {TOPIC_STAT}")
                c.subscribe(TOPIC_EV); log(f"[mqtt] subscribe {TOPIC_EV}")
                c.subscribe(TOPIC_PORTS_ANN); log(f"[mqtt] subscribe {TOPIC_PORTS_ANN}")
                c.subscribe(TOPIC_PORTS_DATA); log(f"[mqtt] subscribe {TOPIC_PORTS_DATA}")

        def on_message(c, userdata, msg):
            if "ports/data" not in msg.topic:
                log(f"[mqtt] RX {msg.topic} {len(msg.payload)}B")
            dev_id, leaf = parse_topic(msg.topic)
            if not dev_id or not leaf:
                return
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except Exception:
                log("[mqtt] JSON parse error from broker")
                return

            if leaf == "announce":
                device_store.upsert_announce(dev_id, payload)
                # Check if device needs claiming
                if not device_store.get_token(dev_id):
                    token = generate_token()
                    device_store.set_token(dev_id, token)
                    
                    claim_topic = f"mcp/dev/{dev_id}/claim"
                    claim_payload = {"token": token}
                    
                    try:
                        pub = get_mqtt_pub_client()
                        pub.publish(claim_topic, json.dumps(claim_payload), qos=1, retain=False)
                        log(f"[CLAIM] Sent new token to {dev_id}")
                    except Exception as e:
                        log(f"[CLAIM] Failed to send token: {e}")
            elif leaf == "status":
                device_store.update_status(dev_id, payload)
            elif leaf == "events":
                rid = payload.get("request_id")
                if rid:
                    cmd_waiter.resolve(rid, payload)
            elif leaf == "ports/announce":
                # 포트 announce 처리
                port_store.upsert_ports_announce(dev_id, payload)
            elif leaf == "ports/data":
                # OutPort 데이터 → 라우팅
                port_name = payload.get("port")
                value = payload.get("value")
                if port_name is not None and value is not None:
                    try:
                        value = float(value)
                        routed = port_router.route(dev_id, port_name, value)
                        if routed > 0:
                            pass
                            # log(f"[ROUTING] {dev_id}/{port_name} routed to {routed} targets")
                    except (ValueError, TypeError) as e:
                        pass
                        # log(f"[ROUTING] Invalid value for {dev_id}/{port_name}: {e}")

        client.on_connect = on_connect
        client.on_message = on_message

        client.connect(MQTT_HOST, MQTT_PORT, keepalive=KEEPALIVE)
        client.loop_forever(retry_first_connection=True)

    threading.Thread(target=mqtt_thread, daemon=True).start()
