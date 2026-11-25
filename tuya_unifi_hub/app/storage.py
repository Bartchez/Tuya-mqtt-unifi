import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger("ConfigManager")

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CONFIG_FILE = os.path.join(DATA_DIR, "settings.json")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
MAPPINGS_FILE = os.path.join(DATA_DIR, "mappings.json")
MATCHES_FILE = os.path.join(DATA_DIR, "matches.json")

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

class Storage:
    @staticmethod
    def load_settings() -> Dict[str, Any]:
        ensure_data_dir()
        ha_options_file = "/data/options.json"
        defaults = {
            "mqtt_host": "192.168.1.21",
            "mqtt_port": 1883,
            "mqtt_user": "",
            "mqtt_password": "",
            "unifi_host": "192.168.1.2",
            "unifi_port": 443,
            "unifi_api_key": "",
            "unifi_user": "",
            "unifi_password": "",
            "unifi_site": "default",
            "unifi_verify_ssl": False,
            "tuya_qr_token": "",
            "tuya_user_code": "",
            "tuya_api_credentials": {}
        }
        
        if os.path.exists(ha_options_file):
            try:
                with open(ha_options_file, "r", encoding="utf-8") as f:
                    ha_opts = json.load(f)
                    defaults.update(ha_opts)
            except Exception as e:
                logger.error(f"Blad odczytu /data/options.json: {e}")

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    defaults.update(saved)
            except Exception as e:
                logger.error(f"Blad odczytu settings.json: {e}")
                
        return defaults

    @staticmethod
    def save_settings(data: Dict[str, Any]):
        ensure_data_dir()
        current = Storage.load_settings()
        current.update(data)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)

    @staticmethod
    def load_devices() -> Dict[str, Any]:
        ensure_data_dir()
        if os.path.exists(DEVICES_FILE):
            try:
                with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Blad odczytu devices.json: {e}")
        return {}

    @staticmethod
    def save_devices(devices: Dict[str, Any]):
        ensure_data_dir()
        with open(DEVICES_FILE, "w", encoding="utf-8") as f:
            json.dump(devices, f, indent=2)

    @staticmethod
    def load_mappings() -> Dict[str, Any]:
        ensure_data_dir()
        if os.path.exists(MAPPINGS_FILE):
            try:
                with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Blad odczytu mappings.json: {e}")
        return {}

    @staticmethod
    def save_mappings(mappings: Dict[str, Any]):
        ensure_data_dir()
        with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(mappings, f, indent=2)

    @staticmethod
    def load_matches() -> Dict[str, Any]:
        """Pobiera mapowania powiązań Tuya <-> UniFi (dev_id -> {local_ip, mac, status})"""
        ensure_data_dir()
        if os.path.exists(MATCHES_FILE):
            try:
                with open(MATCHES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Blad odczytu matches.json: {e}")
        return {}

    @staticmethod
    def save_matches(matches: Dict[str, Any]):
        ensure_data_dir()
        with open(MATCHES_FILE, "w", encoding="utf-8") as f:
            json.dump(matches, f, indent=2)
