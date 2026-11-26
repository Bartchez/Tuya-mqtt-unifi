import json
import hashlib
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

        custom_on = (extra_options.get("payload_on") or "").strip() or "ON"
        custom_off = (extra_options.get("payload_off") or "").strip() or "OFF"

        if component == "switch":
            # F&Home (mqtt_switch_output) wymaga 12-znakowego HEX ID (jak MAC) oraz uniq_id "<HEX>_ch-1"
            hex_id = hashlib.md5(f"{device_id}_{dps_key}".encode("utf-8")).hexdigest()[:12].upper()
            sw_uid = f"{hex_id}_ch-1"
            sw_disc_topic = f"homeassistant/switch/{sw_uid}/config"
            sw_cfg = {
                "device": {
                    "name": entity_display_name or dev_name,
                    "mdl": "r1s1_wp",
                    "ids": hex_id,
                    "mf": "F&F Filipowski Sp. k.",
                    "hw": "0.1",
                    "sw": "v1.18.23_dev"
                },
                "name": "",
                "uniq_id": sw_uid,
                "ret": False,
                "val_tpl": "{{value_json.RCH1|default('')}}",
                "stat_t": state_topic,
                "avty_t": lwt_topic,
                "cmd_t": cmd_topic,
                "opt": False,
                "pl_on": "1",
                "pl_off": "0",
                "stat_on": "1",
                "stat_off": "0"
            }
            return sw_disc_topic, sw_cfg

        if component in ["sensor", "binary_sensor"]:
            unit = extra_options.get("unit", "")
            dev_class = extra_options.get("device_class", "")
            if unit:
                config["unit_of_measurement"] = unit
            if dev_class:
                config["device_class"] = dev_class
            if component == "binary_sensor":
                config["payload_on"] = custom_on
                config["payload_off"] = custom_off

        elif component == "light":
            config.update({
                "command_topic": cmd_topic,
                "payload_on": custom_on,
                "payload_off": custom_off
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
