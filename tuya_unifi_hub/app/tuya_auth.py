import os
import io
import json
import base64
import logging
import pyqrcode
from typing import Dict, Any, List

from tuya_sharing import LoginControl, Manager

logger = logging.getLogger("TuyaAuth")

class TuyaLocalKeyExtractorService:
    CLIENT_ID = "HA_3y9q4ak7g4ephrvke"

    def __init__(self):
        self.login_control = LoginControl()
        self.manager = None
        self.token_info = None
        self.user_code = ""
        self.schema = "smartlife"

    def create_qr_code(self, user_code: str, schema: str = "smartlife") -> dict:
        try:
            self.user_code = user_code.strip()
            self.schema = schema.strip() if schema else "smartlife"
            client_id = self.CLIENT_ID
            schema_name = self.schema

            logger.info(f"Pobieranie kodu QR z Tuya: client_id={client_id}, schema={schema_name}, user_code={self.user_code}")
            ret = self.login_control.qr_code(client_id, schema_name, self.user_code)
            logger.info(f"Odpowiedz Tuya qr_code: {ret}")

            if not ret.get("success", False):
                err_msg = ret.get("msg") or ret.get("error") or "Nie udalo sie wygenerowac kodu"
                return {"success": False, "error": f"{err_msg} (kod: {ret.get('code')})"}

            result = ret.get("result", {})
            token = result.get("qrcode") or result.get("token")
            if not token:
                return {"success": False, "error": "Brak tokenu QR w odpowiedzi Tuya"}

            qr_content = f"tuyaSmart--qrLogin?token={token}"
            
            qr = pyqrcode.create(qr_content)
            buf = io.BytesIO()
            qr.png(buf, scale=7)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            return {
                "success": True,
                "token": token,
                "qr_content": qr_content,
                "qr_image": f"data:image/png;base64,{img_b64}"
            }
        except Exception as e:
            logger.error(f"Wyjatek generowania Tuya QR: {e}")
            return {"success": False, "error": str(e)}

    def check_qr_login(self, token: str) -> dict:
        try:
            res = self.login_control.login_result(token, self.CLIENT_ID, self.user_code)
            
            ret = False
            info = {}
            if isinstance(res, tuple):
                ret, info = res
            elif isinstance(res, dict):
                ret = res.get("success", False)
                info = res.get("result", res)

            if ret and info:
                logger.info(f"Sukces autoryzacji Tuya dla usera: {info.get('username')}")
                self.token_info = info
                terminal_id = info.get("terminal_id", "")
                endpoint = info.get("endpoint", "https://openapi.tuyaeu.com")

                # Inicjalizacja oficjalnego obiektu Manager z tuya_sharing (zgodnie z extractor.py)
                self.manager = Manager(
                    self.CLIENT_ID,
                    self.user_code,
                    terminal_id,
                    endpoint,
                    self.token_info
                )

                self.manager.update_device_cache()
                devices_map = getattr(self.manager, "device_map", {})
                logger.info(f"Pobrano {len(devices_map)} urzadzen z Tuya!")

                # Identyfikacja bramek (gateways) - zgodnie z extractor.py
                gateways = {}
                for dev_id, dev in devices_map.items():
                    if not getattr(dev, "node_id", ""):
                        gateways[dev_id] = dev

                devices_parsed = []
                for dev_id, dev in devices_map.items():
                    node_id = getattr(dev, "node_id", "") or ""
                    gw_id = getattr(dev, "gateway_id", "") or getattr(dev, "parent_id", "") or ""
                    local_key = getattr(dev, "local_key", "") or ""
                    ip = getattr(dev, "ip", "") or ""

                    # Dopasowanie podbramkowe
                    if node_id and not gw_id and local_key:
                        for g_id, g_dev in gateways.items():
                            if getattr(g_dev, "local_key", "") == local_key:
                                gw_id = g_id
                                break

                    if node_id and gw_id in gateways and not local_key:
                        local_key = getattr(gateways[gw_id], "local_key", "")

                    if node_id and gw_id in gateways and not ip:
                        ip = getattr(gateways[gw_id], "ip", "")

                    # Pobranie statusu (DPS) z obiektu dev
                    status_dict = {}
                    raw_status = getattr(dev, "status", {})
                    if isinstance(raw_status, dict):
                        status_dict = raw_status
                    elif isinstance(raw_status, list):
                        for item in raw_status:
                            if isinstance(item, dict) and "code" in item and "value" in item:
                                status_dict[item["code"]] = item["value"]

                    devices_parsed.append({
                        "id": dev_id,
                        "name": getattr(dev, "name", f"Tuya {dev_id}"),
                        "local_key": local_key,
                        "ip": ip,
                        "mac": getattr(dev, "mac", ""),
                        "node_id": node_id,
                        "gateway_id": gw_id,
                        "category": getattr(dev, "category", ""),
                        "product_name": getattr(dev, "product_name", ""),
                        "version": "3.3",
                        "dps": status_dict
                    })

                return {
                    "status": "confirmed",
                    "count": len(devices_parsed),
                    "devices": devices_parsed
                }

            return {"status": "waiting"}

        except Exception as e:
            logger.error(f"Wyjatek check_qr_login: {e}")
            return {"status": "error", "error": str(e)}

    def refresh_cloud_devices(self) -> list:
        """Odświeża urządzenia i ich parametry z chmury Tuya, jeśli sesja jest aktywna."""
        if not self.manager:
            return []
        try:
            self.manager.update_device_cache()
            devices_map = getattr(self.manager, "device_map", {})
            gateways = {}
            for dev_id, dev in devices_map.items():
                if not getattr(dev, "node_id", ""):
                    gateways[dev_id] = dev

            result = []
            for dev_id, dev in devices_map.items():
                node_id = getattr(dev, "node_id", "") or ""
                gw_id = getattr(dev, "gateway_id", "") or getattr(dev, "parent_id", "") or ""
                local_key = getattr(dev, "local_key", "") or ""
                ip = getattr(dev, "ip", "") or ""

                if node_id and not gw_id and local_key:
                    for g_id, g_dev in gateways.items():
                        if getattr(g_dev, "local_key", "") == local_key:
                            gw_id = g_id
                            break

                if node_id and gw_id in gateways and not local_key:
                    local_key = getattr(gateways[gw_id], "local_key", "")

                if node_id and gw_id in gateways and not ip:
                    ip = getattr(gateways[gw_id], "ip", "")

                status_dict = {}
                raw_status = getattr(dev, "status", {})
                if isinstance(raw_status, dict):
                    status_dict = raw_status
                elif isinstance(raw_status, list):
                    for item in raw_status:
                        if isinstance(item, dict) and "code" in item and "value" in item:
                            status_dict[item["code"]] = item["value"]

                result.append({
                    "id": dev_id,
                    "name": getattr(dev, "name", f"Tuya {dev_id}"),
                    "local_key": local_key,
                    "ip": ip,
                    "mac": getattr(dev, "mac", ""),
                    "node_id": node_id,
                    "gateway_id": gw_id,
                    "category": getattr(dev, "category", ""),
                    "product_name": getattr(dev, "product_name", ""),
                    "version": "3.3",
                    "dps": status_dict
                })
            return result
        except Exception as e:
            logger.error(f"Blad refresh_cloud_devices: {e}")
            return []
