import logging
import requests
import subprocess
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("UniFiManager")

class UniFiManager:
    """
    Obsługa UniFi OS / Network:
    - Integration API v1 (X-API-KEY)
    - stat/alluser (Wszystkie znane i skonfigurowane urządzenia w UniFi - 160+ urządzeń)
    - stat/sta (Aktywne połączenia)
    - clients/active
    - Przypisywanie stałego IP (Fixed IP DHCP reservation)
    - Fallback skanowania ARP lokalnej sieci LAN
    """
    def __init__(self, host: str, port: int = 443, api_key: str = "", user: str = "", password: str = "", site: str = "default", verify_ssl: bool = False):
        self.host = host.rstrip("/") if host else ""
        self.port = port or 443
        self.api_key = api_key.strip() if api_key else ""
        self.user = user.strip() if user else ""
        self.password = password.strip() if password else ""
        self.site = site or "default"
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.site_id = "default"
        self.auth_mode = None

        if self.api_key:
            self.session.headers.update({
                "X-API-KEY": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json"
            })

    def _get_base_url(self) -> str:
        base = self.host
        if not (base.startswith("http://") or base.startswith("https://")):
            base = f"https://{base}"
        if not (":443" in base or ":8443" in base) and self.port != 443:
            base = f"{base}:{self.port}"
        return base

    def login(self) -> bool:
        if not self.host:
            logger.warning("Brak hosta UniFi")
            return False

        base_url = self._get_base_url()

        # 1. API KEY
        if self.api_key:
            try:
                sites_url = f"{base_url}/proxy/network/integration/v1/sites"
                resp = self.session.get(sites_url, verify=self.verify_ssl, timeout=4)
                if resp.status_code == 200:
                    data = resp.json()
                    sites = data if isinstance(data, list) else data.get("data", [])
                    if sites:
                        self.site_id = sites[0].get("id", "default")
                    self.auth_mode = "api_key"
                    return True
            except Exception as e:
                logger.debug(f"Integration API v1 test nie powiodl sie: {e}")

            try:
                fallback_url = f"{base_url}/proxy/network/api/s/{self.site}/stat/sta"
                fb_resp = self.session.get(fallback_url, verify=self.verify_ssl, timeout=4)
                if fb_resp.status_code == 200:
                    self.auth_mode = "api_key"
                    return True
            except Exception as e:
                logger.debug(f"UniFi proxy stat/sta test nie powiodl sie: {e}")

        # 2. Logowanie sesją (user/password)
        if self.user and self.password:
            try:
                login_url = f"{base_url}/api/auth/login"
                resp = self.session.post(
                    login_url,
                    json={"username": self.user, "password": self.password},
                    verify=self.verify_ssl,
                    timeout=5
                )
                if resp.status_code == 200:
                    self.auth_mode = "cookie"
                    return True
            except Exception as e:
                logger.debug(f"UniFi cookie auth nie powiodl sie: {e}")

        return False

    def get_clients(self) -> list:
        """Pobiera listę klientów z UniFi OS łącząc aktywne i zapamiętane (alluser + sta)"""
        if not self.login():
            logger.warning("Nie mozna pobrac klientow UniFi - brak autoryzacji")
            return []

        base_url = self._get_base_url()
        clients_by_mac = {}

        # 1. Pobierz wszystkie znane/skonfigurowane urządzenia w UniFi (stat/alluser)
        try:
            url_all = f"{base_url}/proxy/network/api/s/{self.site}/stat/alluser"
            resp_all = self.session.get(url_all, verify=self.verify_ssl, timeout=6)
            if resp_all.status_code == 200:
                raw_list = resp_all.json().get("data", [])
                for u in raw_list:
                    mac = u.get("mac", "").upper().replace("-", ":")
                    if mac:
                        name = u.get("name") or u.get("hostname") or f"Klient-{mac[-5:]}"
                        ip = u.get("fixed_ip") or u.get("last_ip") or u.get("ip") or ""
                        fixed = u.get("use_fixedip", False)
                        clients_by_mac[mac] = {
                            "mac": mac,
                            "ip": ip,
                            "name": name,
                            "fixed": fixed,
                            "fixed_ip": u.get("fixed_ip", ""),
                            "source": "UniFi Baza (alluser)"
                        }
        except Exception as e:
            logger.debug(f"Pobranie alluser nie powiodlo sie: {e}")

        # 2. Pobierz aktualnie połączone aktywne stacje (stat/sta) - nadpisz świeższym IP i statusem
        try:
            url_sta = f"{base_url}/proxy/network/api/s/{self.site}/stat/sta"
            resp_sta = self.session.get(url_sta, verify=self.verify_ssl, timeout=6)
            if resp_sta.status_code == 200:
                raw_sta = resp_sta.json().get("data", [])
                for s in raw_sta:
                    mac = s.get("mac", "").upper().replace("-", ":")
                    if mac:
                        name = s.get("name") or s.get("hostname") or (clients_by_mac.get(mac, {}).get("name")) or f"Klient-{mac[-5:]}"
                        ip = s.get("ip") or (clients_by_mac.get(mac, {}).get("ip")) or ""
                        fixed = s.get("use_fixedip", clients_by_mac.get(mac, {}).get("fixed", False))
                        clients_by_mac[mac] = {
                            "mac": mac,
                            "ip": ip,
                            "name": name,
                            "fixed": fixed,
                            "fixed_ip": s.get("fixed_ip") or clients_by_mac.get(mac, {}).get("fixed_ip", ""),
                            "source": "UniFi Aktywny (sta)"
                        }
        except Exception as e:
            logger.debug(f"Pobranie stat/sta nie powiodlo sie: {e}")

        # 3. Jeśli lista jest pusta, spróbuj integration v1 lub v2 clients/active
        if not clients_by_mac:
            fallback_endpoints = [
                f"{base_url}/proxy/network/v2/api/site/{self.site}/clients/active",
                f"{base_url}/proxy/network/integration/v1/sites/{self.site_id}/clients",
                f"{base_url}/api/s/{self.site}/stat/sta"
            ]
            for u in fallback_endpoints:
                try:
                    resp = self.session.get(u, verify=self.verify_ssl, timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_list = data if isinstance(data, list) else data.get("data", [])
                        for c in raw_list:
                            mac = (c.get("macAddress") or c.get("mac", "")).upper().replace("-", ":")
                            if mac:
                                clients_by_mac[mac] = {
                                    "mac": mac,
                                    "ip": c.get("ipAddress") or c.get("ip") or c.get("last_ip", ""),
                                    "name": c.get("name") or c.get("hostname") or f"UniFi-{mac[-5:]}",
                                    "fixed": c.get("useFixedIp", False) or c.get("use_fixedip", False),
                                    "fixed_ip": c.get("fixedIpAddress") or c.get("fixed_ip", ""),
                                    "source": "UniFi Fallback"
                                }
                        if clients_by_mac:
                            break
                except Exception:
                    pass

        return list(clients_by_mac.values())

    def set_fixed_ip(self, mac: str, ip: str, name: str = None) -> dict:
        """Nadaje stałe IP dla adresu MAC w kontrolerze UniFi."""
        mac_clean = mac.lower().replace("-", ":")
        if not self.login():
            return {"success": False, "error": "Nie udalo sie zautoryzowac w UniFi (sprawdz IP oraz API Key / haslo)"}

        base_url = self._get_base_url()

        # 1. Integration API v1
        try:
            clients_url = f"{base_url}/proxy/network/integration/v1/sites/{self.site_id}/clients"
            resp = self.session.get(clients_url, verify=self.verify_ssl, timeout=6)
            if resp.status_code == 200:
                clients = resp.json()
                client_list = clients if isinstance(clients, list) else clients.get("data", [])
                target_client = next((c for c in client_list if (c.get("macAddress") or c.get("mac", "")).lower() == mac_clean), None)

                payload = {
                    "macAddress": mac_clean,
                    "useFixedIp": True,
                    "fixedIpAddress": ip
                }
                if name:
                    payload["name"] = name

                if target_client and "id" in target_client:
                    cid = target_client["id"]
                    patch_resp = self.session.patch(f"{clients_url}/{cid}", json=payload, verify=self.verify_ssl, timeout=6)
                    if patch_resp.status_code in [200, 204]:
                        return {"success": True, "message": f"Ustawiono stale IP {ip} w UniFi dla {mac_clean}"}
        except Exception as e:
            logger.debug(f"Integration API v1 patch nie powiodl sie: {e}")

        # 2. Fallback na klasyczne rest/user
        try:
            rest_url = f"{base_url}/proxy/network/api/s/{self.site}/rest/user"
            resp = self.session.get(rest_url, verify=self.verify_ssl, timeout=6)
            users = resp.json().get("data", []) if resp.status_code == 200 else []
            user_obj = next((u for u in users if u.get("mac", "").lower() == mac_clean), None)

            classic_payload = {
                "mac": mac_clean,
                "use_fixedip": True,
                "fixed_ip": ip
            }
            if name:
                classic_payload["name"] = name

            if user_obj and "_id" in user_obj:
                uid = user_obj["_id"]
                p_resp = self.session.put(f"{rest_url}/{uid}", json=classic_payload, verify=self.verify_ssl, timeout=6)
                if p_resp.status_code in [200, 201]:
                    return {"success": True, "message": f"Ustawiono stale IP {ip} w UniFi dla {mac_clean}"}
            else:
                p_resp = self.session.post(rest_url, json=classic_payload, verify=self.verify_ssl, timeout=6)
                if p_resp.status_code in [200, 201]:
                    return {"success": True, "message": f"Utworzono stale IP {ip} w UniFi dla {mac_clean}"}
        except Exception as e:
            logger.error(f"Fallback rest/user nie powiodl sie: {e}")
            return {"success": False, "error": str(e)}

        return {"success": False, "error": "UniFi odrzucilo zmiane IP."}


def scan_lan_arp() -> list:
    """Skanuje tablicę ARP systemu (działa w Linuxie HA oraz Windows)"""
    devices = []
    try:
        # Próba /proc/net/arp (Linux HA kontener)
        try:
            with open("/proc/net/arp", "r") as f:
                lines = f.readlines()
                for line in lines[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip = parts[0]
                        mac = parts[3].upper()
                        if mac != "00:00:00:00:00:00" and not ip.startswith("224.") and not ip.startswith("239."):
                            devices.append({
                                "ip": ip,
                                "mac": mac,
                                "name": f"LAN ({ip})",
                                "fixed": False,
                                "source": "ARP (/proc/net/arp)"
                            })
            if devices:
                return devices
        except Exception:
            pass

        # Komenda arp -a (Windows lub Linux z net-tools)
        output = subprocess.check_output("arp -a", shell=True, text=True, stderr=subprocess.DEVNULL)
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                ip = parts[0]
                mac_candidate = parts[1].replace("-", ":").upper()
                if mac_candidate.count(":") == 5:
                    if not ip.startswith("224.") and not ip.startswith("239.") and not ip.startswith("255."):
                        devices.append({
                            "ip": ip,
                            "mac": mac_candidate,
                            "name": f"LAN ({ip})",
                            "fixed": False,
                            "source": "ARP"
                        })
    except Exception as e:
        logger.debug(f"ARP scan err: {e}")
    return devices
