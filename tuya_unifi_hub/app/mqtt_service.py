import json
import logging
import threading
import time
from typing import Dict, Any, Callable, Optional
import paho.mqtt.client as mqtt

logger = logging.getLogger("MQTTService")

class MQTTService:
    def __init__(self, host: str = "192.168.1.21", port: int = 1883, user: str = "ffdevice", password: str = "ffdevice"):
        self.host = host or "192.168.1.21"
        self.port = int(port or 1883)
        self.user = user or "ffdevice"
        self.password = password or "ffdevice"
        self.client = None
        self.is_connected = False
        self.command_handlers: Dict[str, Callable] = {}
        self._lock = threading.Lock()
        # Callback wywoływany po każdym połączeniu z brokerem (np. do republowania discovery)
        self.on_connected_callback: Optional[Callable] = None

    def start(self):
        try:
            self.client = mqtt.Client(client_id="TuyaBridge_HA", protocol=mqtt.MQTTv311)
            if self.user and self.password:
                self.client.username_pw_set(self.user, self.password)

            # Ustaw LWT (Last Will) dokładnie jak w ESP32
            self.client.will_set("tuya_esp/status", "offline", qos=1, retain=True)

            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message

            logger.info(f"Laczenie z brokerem MQTT {self.host}:{self.port}...")
            self.client.connect_async(self.host, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Blad uruchomienia klienta MQTT: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.is_connected = True
            logger.info("Polaczono z brokerem MQTT!")
            # Wyślij natychmiast 'online' na tuya_esp/status
            self.client.publish("tuya_esp/status", "online", qos=1, retain=True)
            # Nasłuchuj komend
            self.client.subscribe("tuya_esp/+/set/#")
            # Republuj wszystkie discovery i stany po każdym (re)połączeniu
            if self.on_connected_callback:
                try:
                    threading.Thread(target=self.on_connected_callback, daemon=True).start()
                except Exception as e:
                    logger.error(f"Blad on_connected_callback: {e}")
        else:
            logger.error(f"Blad polaczenia z MQTT, kod: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        logger.warning(f"Rozlaczono z brokerem MQTT (kod: {rc})")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload_raw = msg.payload.decode("utf-8", errors="ignore").strip()
        logger.info(f"Odebrano komende MQTT [{topic}]: {payload_raw}")

        # Parsowanie tuya_esp/<dev_id>/set/<dps_key>
        parts = topic.split("/")
        if len(parts) >= 4 and parts[0] == "tuya_esp" and parts[2] == "set":
            dev_id = parts[1]
            dps_key = parts[3]
            handler = self.command_handlers.get(dev_id)
            if handler:
                handler(dev_id, dps_key, payload_raw)

    def register_command_handler(self, dev_id: str, callback: Callable):
        with self._lock:
            self.command_handlers[dev_id] = callback

    def publish_status_online(self):
        if self.client and self.is_connected:
            self.client.publish("tuya_esp/status", "online", qos=1, retain=True)

    def publish_mapped_value(self, device_id: str, dps_key: str, value: Any):
        if not self.client or not self.is_connected:
            return
        
        topic = f"tuya_esp/{device_id}/mapped/{dps_key}"
        
        # Konwersja booleana na 'ON'/'OFF' zgodnie z ESP32
        if isinstance(value, bool):
            payload = "ON" if value else "OFF"
        elif str(value).lower() in ["true", "presence", "motion", "on", "1"]:
            payload = "ON"
        elif str(value).lower() in ["false", "none", "off", "0"]:
            payload = "OFF"
        else:
            payload = str(value)

        self.client.publish(topic, payload, retain=True)
        logger.info(f"Wyslano MQTT [{topic}] -> {payload}")

    def publish_raw_state(self, device_id: str, dps: dict):
        if not self.client or not self.is_connected or not dps:
            return
        topic = f"tuya_esp/{device_id}/state"
        payload = json.dumps(dps, ensure_ascii=False)
        self.client.publish(topic, payload, retain=True)

    def publish_discovery(self, topic: str, config_dict: dict):
        if not self.client or not self.is_connected:
            return
        payload = json.dumps(config_dict, ensure_ascii=False)
        self.client.publish(topic, payload, retain=True)
        logger.info(f"Opublikowano Discovery: {topic}")

    def remove_discovery(self, topic: str):
        if not self.client or not self.is_connected:
            return
        self.client.publish(topic, "", retain=True)

    def wait_for_connection(self, timeout: float = 15.0) -> bool:
        """Czeka na połączenie z brokerem MQTT (maksymalnie timeout sekund)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_connected:
                return True
            time.sleep(0.2)
        return False
