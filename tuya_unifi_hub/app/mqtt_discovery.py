import json
import logging
from typing import Dict, Any

logger = logging.getLogger("MQTTDiscovery")

class MQTTDiscoveryBuilder:
    """
    Standard MQTT 1:1 z Twojego projektu ESP32-S3 (tuya_esp32s3.ino):
    default_mqtt_topic = "tuya_esp"
    lwtTopic = "tuya_esp/status" -> 'online' / 'offline'
    baseTopic = "tuya_esp/<device_id>"
    stateTopic = "tuya_esp/<device_id>/mapped/<dps_key>"
    cmdTopic = "tuya_esp/<device_id>/set/<dps_key>"
    """

    @staticmethod
    def build_config(
        component: str,
        device_id: str,
        device_name: str,
        dps_key: str,
        dps_name: str,
        extra_options: Dict[str, Any] = None
    ) -> tuple[str, dict]:
        extra_options = extra_options or {}
        
        base_topic = f"tuya_esp/{device_id}"
        lwt_topic = "tuya_esp/status"
        dev_identifier = f"tuya_local_{device_id}"

        unique_id = f"tuya_{device_id}_map_{dps_key}"
        discovery_topic = f"homeassistant/{component}/{unique_id}/config"
        state_topic = f"{base_topic}/mapped/{dps_key}"
        cmd_topic = f"{base_topic}/set/{dps_key}"

        # Nazwa urządzenia (grupuje wiele właściwości/encji pod jednym urządzeniem w MQTT)
        dev_name = (device_name or "").strip() or f"Tuya {device_id}"
        # Nazwa konkretnej właściwości (encji) wewnątrz tego urządzenia
        entity_display_name = (dps_name or "").strip() or f"{dev_name} {dps_key}"
        proto_ver = extra_options.get("version", "3.3")

        device_info = {
            "identifiers": [dev_identifier],
            "name": dev_name,
            "manufacturer": "Tuya->Mqtt (ESP32-S3)",
            "model": f"Wi-Fi v{proto_ver}"
        }

        config = {
            "name": entity_display_name,
            "unique_id": unique_id,
            "state_topic": state_topic,
            "availability_topic": lwt_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device_info
        }

        if component in ["sensor", "binary_sensor"]:
            unit = extra_options.get("unit", "")
            dev_class = extra_options.get("device_class", "")
            if unit:
                config["unit_of_measurement"] = unit
            if dev_class:
                config["device_class"] = dev_class

        elif component == "switch":
            config.update({
                "command_topic": cmd_topic,
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "ON",
                "state_off": "OFF"
            })

        elif component == "light":
            config.update({
                "command_topic": cmd_topic,
                "payload_on": "ON",
                "payload_off": "OFF"
            })

        elif component == "climate":
            config.update({
                "temperature_command_topic": f"{cmd_topic}/temp",
                "temperature_state_topic": state_topic,
                "temp_step": 0.5,
                "min_temp": 16,
                "max_temp": 30
            })

        return discovery_topic, config
