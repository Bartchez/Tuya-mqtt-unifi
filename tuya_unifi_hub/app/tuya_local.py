import time
import socket
import json
import logging
import threading
from typing import Dict, Any, Callable, Optional
import tinytuya

logger = logging.getLogger("TuyaLocalManager")

# Mapowanie popularnych nazw kodowych z Tuya Cloud na numeryczne identyfikatory DPS w Tuya LAN (TinyTuya)
COMMON_DP_CODE_TO_IDS = {
    # Czujniki obecności / radary mmWave (kategoria hps)
    "presence_state": ["1"],
    "sensitivity": ["2"],
    "near_detection": ["3"],
    "far_detection": ["4"],
    "self_test": ["6"],
    "target_dis_closest": ["9"],
    "illuminance_value": ["104", "12"],
    "fading_time": ["102", "105"],
    "detection_delay": ["101"],
    # Przełączniki / gniazdka / oświetlenie
    "switch": ["1"],
    "switch_1": ["1"],
    "switch_2": ["2"],
    "switch_3": ["3"],
    "switch_4": ["4"],
    "switch_led": ["20", "1"],
    "work_mode": ["21", "2"],
    "bright_value": ["22", "3"],
    "bright_value_v2": ["22", "3"],
    "temp_value": ["23", "4"],
    "temp_value_v2": ["23", "4"],
    "colour_data": ["24", "5"],
    "colour_data_v2": ["24", "5"],
    # Czujniki klimatu / stacje pogodowe / nawilżacze
    "temp_current": ["1", "18", "3"],
    "humidity_value": ["2", "19"],
    "temp_current_external": ["38", "1", "18"],
    "windspeed_gust": ["101", "10"],
    "battery_percentage": ["4", "15"],
}


class TuyaLocalManager:
    """
    Zarządza lokalną komunikacją z urządzeniami Tuya w sieci LAN przez protokół 3.1, 3.3, 3.4, 3.5.
    Obsługuje urządzenia Wi-Fi oraz podbramkowe Zigbee/BLE (przez bramkę Tuya).
    Automatycznie wykrywa wersję protokołu (3.3 / 3.4 / 3.5 / 3.1) i mapuje nazwy kodowe Cloud na numeryczne DPS LAN.
    """
    def __init__(
        self,
        on_status_update: Callable[[str, dict], None],
        on_version_detected: Optional[Callable[[str, str], None]] = None
    ):
        self.on_status_update = on_status_update  # callback(device_id, dps_dict)
        self.on_version_detected = on_version_detected  # callback(device_id, version_str)
        self.devices: Dict[str, dict] = {}
        self.device_clients: Dict[str, Any] = {}
        self.running = False
        self._poll_thread = None
        self._lock = threading.Lock()

    @staticmethod
    def resolve_dps_value(dps: dict, dps_key: str):
        """Odczytuje wartość dla klucza DPS (zarówno numerycznego '1', jak i nazwy z chmury np. 'presence_state')."""
        if not dps or not isinstance(dps, dict):
            return None
        key_str = str(dps_key)
        if key_str in dps:
            return dps[key_str]
        # Próba mapowania nazwy kodowej z Tuya Cloud na numeryczne ID z Tuya LAN
        candidates = COMMON_DP_CODE_TO_IDS.get(key_str.lower(), [])
        for cid in candidates:
            if cid in dps:
                return dps[cid]
        return None

    @staticmethod
    def resolve_dps_id(dps_key: str, available_dps: Optional[dict] = None) -> str:
        """Tłumaczy nazwę kodową z Tuya Cloud na numeryczny identyfikator DPS do wysłania komendy LAN."""
        key_str = str(dps_key)
        if key_str.isdigit():
            return key_str
        candidates = COMMON_DP_CODE_TO_IDS.get(key_str.lower(), [])
        if available_dps and isinstance(available_dps, dict):
            for cid in candidates:
                if cid in available_dps:
                    return cid
        if candidates:
            return candidates[0]
        return key_str

    def update_device_list(self, devices: Dict[str, dict]):
        with self._lock:
            self.devices = devices
            self.device_clients.clear()

            # Najpierw stwórz klientów dla bramek (urządzenia posiadające bezpośredni IP)
            gateways = {}
            for dev_id, info in self.devices.items():
                ip = info.get("ip")
                local_key = info.get("local_key")
                node_id = info.get("node_id")
                try:
                    version = float(info.get("version", 3.3))
                except (ValueError, TypeError):
                    version = 3.3

                if ip and local_key and not node_id:
                    try:
                        gw = tinytuya.Device(dev_id, ip, local_key)
                        gw.set_version(version)
                        gw.set_socketTimeout(2.0)
                        gw.set_socketPersistent(False)
                        gateways[dev_id] = gw
                        self.device_clients[dev_id] = gw
                    except Exception as e:
                        logger.error(f"Nie mozna zainicjalizowac urzadzenia LAN dla {dev_id}: {e}")

            # Następnie obsłuż urządzenia podbramkowe (Zigbee / BLE pod bramką) oraz pozostałe Wi-Fi
            for dev_id, info in self.devices.items():
                if dev_id in self.device_clients:
                    continue

                ip = info.get("ip")
                local_key = info.get("local_key")
                node_id = info.get("node_id")
                gw_id = info.get("gateway_id")
                try:
                    version = float(info.get("version", 3.3))
                except (ValueError, TypeError):
                    version = 3.3

                # Urządzenie pod bramką (Zigbee)
                if node_id and gw_id and gw_id in gateways:
                    try:
                        parent_gw = gateways[gw_id]
                        sub_dev = tinytuya.OutletDevice(
                            dev_id=dev_id,
                            cid=node_id,
                            parent=parent_gw
                        )
                        self.device_clients[dev_id] = sub_dev
                        logger.info(f"Zainicjalizowano urzadzenie Zigbee/Sub {dev_id} pod bramka {gw_id} (CID: {node_id})")
                        continue
                    except Exception as e:
                        logger.error(f"Blad laczenia urzadzenia podbramkowego {dev_id}: {e}")

                # Standardowe urządzenie Wi-Fi
                if ip and local_key:
                    try:
                        d = tinytuya.OutletDevice(dev_id, ip, local_key)
                        d.set_version(version)
                        d.set_socketTimeout(2.0)
                        d.set_socketPersistent(False)
                        self.device_clients[dev_id] = d
                    except Exception as e:
                        logger.error(f"Nie mozna zainicjalizowac klienta lokalnego Tuya dla {dev_id}: {e}")

    def start(self):
        self.running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logger.info("Uruchomiono watek lokalnego odpytywania Tuya LAN")

    def stop(self):
        self.running = False

    def send_dps_command(self, device_id: str, dps_updates: dict) -> bool:
        """Wysyła polecenie zmiany parametrów (DPS) bezpośrednio do urządzenia przez LAN."""
        client = self.device_clients.get(device_id)
        if not client:
            logger.error(f"Brak polaczenia lokalnego dla urzadzenia {device_id} (sprawdz IP i local_key)")
            return False

        dev_info = self.devices.get(device_id, {})
        available_dps = dev_info.get("dps", {})
        translated_updates = {}
        for k, v in dps_updates.items():
            resolved_id = self.resolve_dps_id(k, available_dps)
            translated_updates[resolved_id] = v

        try:
            logger.info(f"Wysylanie lokalnego polecenia do {device_id}: {translated_updates}")
            payload = client.generate_payload(tinytuya.CONTROL, translated_updates)
            client.send(payload)
            time.sleep(0.1)
            status = client.status()
            if status and isinstance(status, dict) and "dps" in status:
                self.on_status_update(device_id, status["dps"])
            return True
        except Exception as e:
            logger.error(f"Blad wysylania komendy do {device_id}: {e}")
            return False

    def poll_device_status(self, device_id: str) -> dict:
        client = self.device_clients.get(device_id)
        if not client:
            return {}
        try:
            client.set_socketTimeout(2.0)
            data = client.status()
            if data and isinstance(data, dict) and "dps" in data and data["dps"]:
                return data["dps"]
        except Exception as e:
            logger.debug(f"Odpytanie {device_id} (domyslna wersja) zakonczone bledem: {e}")

        # Auto-detekcja wersji protokołu dla urządzeń Wi-Fi (np. czujniki v3.4 / v3.5 / v3.1)
        info = self.devices.get(device_id, {})
        ip = info.get("ip")
        local_key = info.get("local_key")
        node_id = info.get("node_id")
        if ip and local_key and not node_id:
            try:
                current_ver = float(info.get("version", 3.3))
            except (ValueError, TypeError):
                current_ver = 3.3

            for v in [3.4, 3.3, 3.5, 3.1]:
                if abs(v - current_ver) < 0.01:
                    continue
                try:
                    client.set_version(v)
                    client.set_socketTimeout(2.0)
                    data = client.status()
                    if data and isinstance(data, dict) and "dps" in data and data["dps"]:
                        logger.info(f"Auto-wykryto wersje protokolu v{v} dla {device_id} ({ip})!")
                        info["version"] = str(v)
                        if self.on_version_detected:
                            self.on_version_detected(device_id, str(v))
                        return data["dps"]
                except Exception:
                    pass
            # Przywróć poprzednią wersję jeśli żadna nie odpowiedziała
            try:
                client.set_version(current_ver)
            except Exception:
                pass

        return {}

    def test_connection(self, ip: str, dev_id: str = "", local_key: str = "", version: float = 3.3) -> dict:
        """Testuje łączność TCP na porcie 6668 oraz odpytuje stany DPS tinytuya (z auto-detekcją wersji)."""
        tcp_ok = False
        ping_latency = None
        error_msg = None

        t0 = time.time()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.5)
            s.connect((ip, 6668))
            s.close()
            tcp_ok = True
            ping_latency = round((time.time() - t0) * 1000, 1)
        except Exception as e:
            error_msg = f"Port 6668 niedostępny: {e}"

        tuya_status = None
        detected_version = None
        if tcp_ok and dev_id and local_key:
            versions_to_try = [version, 3.4, 3.3, 3.5, 3.1]
            seen = set()
            versions_to_try = [v for v in versions_to_try if not (v in seen or seen.add(v))]

            for v in versions_to_try:
                try:
                    d = tinytuya.OutletDevice(dev_id, ip, local_key)
                    d.set_version(float(v))
                    d.set_socketTimeout(2.5)
                    res = d.status()
                    if isinstance(res, dict) and "dps" in res and res["dps"]:
                        tuya_status = res["dps"]
                        detected_version = str(v)
                        break
                except Exception:
                    pass

        return {
            "tcp_ok": tcp_ok,
            "latency_ms": ping_latency,
            "dps": tuya_status,
            "detected_version": detected_version,
            "error": error_msg
        }

    def _poll_loop(self):
        while self.running:
            for dev_id in list(self.devices.keys()):
                if not self.running:
                    break
                dps = self.poll_device_status(dev_id)
                if dps and isinstance(dps, dict) and len(dps) > 0:
                    self.on_status_update(dev_id, dps)
                time.sleep(0.5)
            time.sleep(4.0)
