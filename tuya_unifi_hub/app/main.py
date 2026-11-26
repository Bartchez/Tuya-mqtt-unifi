import os
import time
import logging
import asyncio
import threading
from typing import Dict, Any, List
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from storage import Storage
from unifi_service import UniFiManager, scan_lan_arp
from tuya_auth import TuyaLocalKeyExtractorService
from tuya_local import TuyaLocalManager
from mqtt_service import MQTTService
from mqtt_discovery import MQTTDiscoveryBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("TuyaBridgeApp")

app = FastAPI(title="Tuya UniFi Hub", root_path_in_servers=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

HTML_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")

settings = Storage.load_settings()
devices = Storage.load_devices()
mappings = Storage.load_mappings()
matches = Storage.load_matches()

# Pamięć podręczna wykrytych klientów UniFi / LAN
network_clients_cache = []

mqtt_service = MQTTService(
    host=settings.get("mqtt_host", "192.168.1.21"),
    port=settings.get("mqtt_port", 1883),
    user=settings.get("mqtt_user", "ffdevice"),
    password=settings.get("mqtt_password", "ffdevice")
)

def on_local_status_update(device_id: str, dps: dict):
    if device_id in devices:
        existing_dps = devices[device_id].get("dps")
        if not isinstance(existing_dps, dict):
            existing_dps = {}
        existing_dps.update(dps)
        devices[device_id]["dps"] = existing_dps
        devices[device_id]["last_seen"] = time.time()
        Storage.save_devices(devices)

    mqtt_service.publish_status_online()
    mqtt_service.publish_raw_state(device_id, dps)

    for m in mappings.values():
        if m.get("device_id") == device_id:
            dps_k = str(m.get("dps_key"))
            val = TuyaLocalManager.resolve_dps_value(dps, dps_k)
            if val is not None:
                mqtt_service.publish_mapped_value(device_id, dps_k, val, m.get("extra", {}), component=m.get("component", "sensor"))

def on_version_detected(device_id: str, version_str: str):
    if device_id in devices and str(devices[device_id].get("version", "")) != str(version_str):
        devices[device_id]["version"] = str(version_str)
        Storage.save_devices(devices)
        logger.info(f"Zapisano auto-wykryta wersje protokolu v{version_str} dla {device_id}")

tuya_local = TuyaLocalManager(
    on_status_update=on_local_status_update,
    on_version_detected=on_version_detected
)

def on_mqtt_command(device_id: str, dps_key: str, payload_str: str):
    logger.info(f"Odebrano rozkaz MQTT dla {device_id} (DPS: {dps_key}): {payload_str}")
    val = payload_str
    # Sprawdź własne payload_on / payload_off z mapowania
    matched_extra = {}
    for m in mappings.values():
        if m.get("device_id") == device_id and str(m.get("dps_key")) == str(dps_key):
            matched_extra = m.get("extra", {}) or {}
            break
    custom_on = (matched_extra.get("payload_on") or "").strip().upper()
    custom_off = (matched_extra.get("payload_off") or "").strip().upper()
    p_up = payload_str.strip().upper()

    if p_up in ["ON", "TRUE", "1"] or (custom_on and p_up == custom_on):
        val = True
    elif p_up in ["OFF", "FALSE", "0"] or (custom_off and p_up == custom_off):
        val = False
    threading.Thread(
        target=tuya_local.send_dps_command,
        args=(device_id, {str(dps_key): val}),
        daemon=True
    ).start()

def publish_all_mappings():
    """Republuje wszystkie discovery i ostatnie stany DPS po połączeniu z MQTT."""
    time.sleep(0.5)
    logger.info("Republowanie wszystkich mapowań MQTT po połączeniu z brokerem...")
    
    current_mappings = Storage.load_mappings()
    current_devices = Storage.load_devices()
    
    for m in current_mappings.values():
        try:
            dev = current_devices.get(m["device_id"], {})
            entity_name = (m.get("entity_name") or "").strip()
            extra = dict(m.get("extra", {}) or {})
            extra["version"] = dev.get("version", "3.3")
            topic, cfg = MQTTDiscoveryBuilder.build_config(
                component=m["component"],
                device_id=m["device_id"],
                device_name=dev.get("name", m["device_id"]),
                dps_key=str(m["dps_key"]),
                dps_name=entity_name,
                extra_options=extra
            )
            mqtt_service.publish_discovery(topic, cfg)
            mqtt_service.register_command_handler(m["device_id"], on_mqtt_command)

            dps_cache = dev.get("dps", {})
            dps_k = str(m.get("dps_key"))
            val = TuyaLocalManager.resolve_dps_value(dps_cache, dps_k)
            if val is not None:
                mqtt_service.publish_mapped_value(m["device_id"], dps_k, val, m.get("extra", {}), component=m.get("component", "sensor"))
        except Exception as e:
            logger.error(f"Blad republowania mapowania {m}: {e}")
    
    mqtt_service.publish_status_online()
    logger.info(f"Republowanie zakończone — {len(current_mappings)} mapowań.")

@app.on_event("startup")
def startup_event():
    try:
        mqtt_service.on_connected_callback = publish_all_mappings
        mqtt_service.start()
        tuya_local.update_device_list(devices)
        tuya_local.start()
        logger.info("Addon uruchomiony pomyślnie.")
    except Exception as e:
        logger.error(f"Blad startup: {e}")

# --- STRONA GŁÓWNA ---

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    try:
        with open(HTML_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        ingress_path = request.headers.get("X-Ingress-Path", "")
        if not ingress_path:
            ingress_path = os.environ.get("INGRESS_PATH", "")
        if not ingress_path:
            ingress_path = ""

        content = content.replace("{{ root_path }}", ingress_path)

        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
            }
        )
    except Exception as e:
        logger.error(f"Blad ladowania strony: {e}")
        return HTMLResponse(content=f"<h3>Blad renderowania: {e}</h3>", status_code=500)

# --- ENDPOINTY PODSTAWOWE ---

@app.get("/api/health")
async def health_check(request: Request):
    return {
        "status": "ok",
        "mqtt_connected": mqtt_service.is_connected,
        "devices_count": len(devices),
        "mappings_count": len(mappings),
        "ingress_path": request.headers.get("X-Ingress-Path", "(brak - dostep bezposredni)"),
    }

@app.get("/api/settings")
async def get_settings():
    return Storage.load_settings()

@app.post("/api/settings")
async def post_settings(req: Request):
    body = await req.json()
    Storage.save_settings(body)
    return {"status": "ok"}

@app.get("/api/devices")
async def get_devices():
    return Storage.load_devices()

@app.post("/api/devices/{device_id}")
async def save_device(device_id: str, req: Request):
    body = await req.json()
    devices[device_id] = body
    Storage.save_devices(devices)
    tuya_local.update_device_list(devices)
    mqtt_service.register_command_handler(device_id, on_mqtt_command)

    # Republuj discovery jeśli nazwa urządzenia uległa zmianie
    for m in mappings.values():
        if m.get("device_id") == device_id:
            topic, cfg = MQTTDiscoveryBuilder.build_config(
                component=m["component"],
                device_id=device_id,
                device_name=body.get("name", device_id),
                dps_key=str(m["dps_key"]),
                dps_name=m["entity_name"],
                extra_options=m.get("extra", {})
            )
            mqtt_service.publish_discovery(topic, cfg)

    return {"status": "ok", "device": body}

@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: str):
    if device_id in devices:
        del devices[device_id]
        Storage.save_devices(devices)
        tuya_local.update_device_list(devices)
    if device_id in matches:
        del matches[device_id]
        Storage.save_matches(matches)
    return {"status": "ok"}

@app.get("/api/devices/{device_id}/poll")
async def poll_device(device_id: str):
    try:
        dps = await asyncio.to_thread(tuya_local.poll_device_status, device_id)
        if dps:
            on_local_status_update(device_id, dps)
            return {"dps": dps, "count": len(dps)}
        else:
            return {"dps": {}, "error": "Brak odpowiedzi od urzadzenia (sprawdz IP i Local Key)"}
    except Exception as e:
        return {"dps": {}, "error": str(e)}

@app.get("/api/mappings")
async def get_mappings():
    return Storage.load_mappings()

@app.post("/api/mappings")
async def create_mapping(req: Request):
    body = await req.json()
    map_id = body.get("id")
    entity_name = body.get("entity_name", "").strip()
    dev_id = body.get("device_id")
    mappings[map_id] = body
    Storage.save_mappings(mappings)

    dev = devices.get(dev_id, {})

    extra = dict(body.get("extra", {}) or {})
    extra["version"] = dev.get("version", "3.3")

    topic, cfg = MQTTDiscoveryBuilder.build_config(
        component=body["component"],
        device_id=dev_id,
        device_name=dev.get("name", dev_id),
        dps_key=str(body["dps_key"]),
        dps_name=entity_name,
        extra_options=extra
    )
    mqtt_service.publish_discovery(topic, cfg)
    mqtt_service.register_command_handler(dev_id, on_mqtt_command)

    # Natychmiast wyślij ostatnią znaną wartość z cache (nie blokuj odpowiedzi HTTP)
    dps_cache = dev.get("dps", {}) or {}
    dps_k = str(body["dps_key"])
    val = TuyaLocalManager.resolve_dps_value(dps_cache, dps_k)
    if val is not None:
        mqtt_service.publish_mapped_value(dev_id, dps_k, val, extra, component=body.get("component", "sensor"))

    # W tle odpytaj urządzenie przez LAN, aby zaktualizować świeżą wartością
    def _bg_poll(target_dev_id: str):
        try:
            fresh_dps = tuya_local.poll_device_status(target_dev_id)
            if fresh_dps:
                on_local_status_update(target_dev_id, fresh_dps)
        except Exception as bg_err:
            logger.debug(f"Blad odpytywania w tle dla {target_dev_id}: {bg_err}")

    threading.Thread(target=_bg_poll, args=(dev_id,), daemon=True).start()

    return {"status": "ok"}

@app.delete("/api/mappings/{map_id}")
async def delete_mapping(map_id: str):
    if map_id in mappings:
        m = mappings[map_id]
        dev = devices.get(m["device_id"], {})
        topic, _ = MQTTDiscoveryBuilder.build_config(
            component=m["component"],
            device_id=m["device_id"],
            device_name=dev.get("name", ""),
            dps_key=str(m["dps_key"]),
            dps_name=""
        )
        mqtt_service.remove_discovery(topic)
        del mappings[map_id]
        Storage.save_mappings(mappings)
    return {"status": "ok"}

@app.post("/api/mappings/{map_id}/test")
async def test_mapping(map_id: str):
    """Testuje konkretne mapowanie: odpytuje urządzenie po LAN, tłumaczy DPS, publikuje Discovery i wartość do MQTT."""
    m = mappings.get(map_id)
    if not m:
        return {"success": False, "error": f"Nie znaleziono mapowania {map_id}"}

    dev_id = m["device_id"]
    dps_k = str(m["dps_key"])
    entity_name = (m.get("entity_name") or "").strip()
    dev = devices.get(dev_id, {})

    # 1. Próba świeżego odczytu po LAN (w osobnym wątku, bez blokowania FastAPI)
    fresh_dps = await asyncio.to_thread(tuya_local.poll_device_status, dev_id)
    lan_ok = bool(fresh_dps and isinstance(fresh_dps, dict) and len(fresh_dps) > 0)

    if lan_ok:
        on_local_status_update(dev_id, fresh_dps)
        active_dps = fresh_dps
        source = "LAN (odczyt na żywo)"
    else:
        active_dps = dev.get("dps", {}) or {}
        source = "Cache (brak odpowiedzi LAN)"

    resolved_id = TuyaLocalManager.resolve_dps_id(dps_k, active_dps)
    raw_val = TuyaLocalManager.resolve_dps_value(active_dps, dps_k)
    value_found = raw_val is not None

    # 2. Republuj Discovery z aktualną nazwą z mapowania i wyślij wartość do MQTT
    extra = dict(m.get("extra", {}) or {})
    extra["version"] = dev.get("version", "3.3")

    # Wyznacz dokładny payload wysyłany do MQTT (z uwzględnieniem własnych zamian)
    mqtt_payload = MQTTService.format_mapped_payload(raw_val, extra, component=m.get("component", "sensor")) if value_found else None

    discovery_topic, cfg = MQTTDiscoveryBuilder.build_config(
        component=m["component"],
        device_id=dev_id,
        device_name=dev.get("name", dev_id),
        dps_key=dps_k,
        dps_name=entity_name,
        extra_options=extra
    )

    mqtt_connected = bool(mqtt_service.is_connected)
    if mqtt_connected:
        mqtt_service.publish_discovery(discovery_topic, cfg)
        mqtt_service.register_command_handler(dev_id, on_mqtt_command)
        if value_found:
            mqtt_service.publish_mapped_value(dev_id, dps_k, raw_val, extra, component=m.get("component", "sensor"))

    return {
        "success": lan_ok and mqtt_connected and value_found,
        "lan_ok": lan_ok,
        "mqtt_connected": mqtt_connected,
        "value_found": value_found,
        "source": source,
        "device_id": dev_id,
        "device_name": dev.get("name", dev_id),
        "ip": dev.get("ip", ""),
        "version": dev.get("version", "3.3"),
        "dps_key": dps_k,
        "resolved_dps_id": resolved_id,
        "raw_value": raw_val,
        "mqtt_payload": mqtt_payload,
        "state_topic": cfg.get("state_topic") or cfg.get("stat_t"),
        "discovery_topic": discovery_topic,
        "broker_device_name": cfg.get("device", {}).get("name"),
        "broker_entity_name": cfg.get("name") or entity_name,
        "all_dps": active_dps,
    }

@app.post("/api/mappings/{map_id}/publish")
async def force_publish_mapping(map_id: str, req: Request):
    """Wymusza natychmiastowe wysłanie Discovery oraz aktualnej wartości mapowania do brokera MQTT."""
    m = mappings.get(map_id)
    if not m:
        return {"success": False, "error": f"Nie znaleziono mapowania {map_id}"}

    if not mqtt_service.is_connected:
        return {"success": False, "error": "Broker MQTT jest rozłączony"}

    body = {}
    try:
        raw = await req.body()
        if raw:
            body = await req.json()
    except Exception:
        body = {}

    dev_id = m["device_id"]
    dps_k = str(m["dps_key"])
    entity_name = (m.get("entity_name") or "").strip()
    dev = devices.get(dev_id, {})

    custom_val = body.get("value") if isinstance(body, dict) else None
    source = "Wartość ręczna"
    val_to_send = custom_val

    if val_to_send is None:
        fresh_dps = await asyncio.to_thread(tuya_local.poll_device_status, dev_id)
        if fresh_dps and isinstance(fresh_dps, dict):
            on_local_status_update(dev_id, fresh_dps)
            val_to_send = TuyaLocalManager.resolve_dps_value(fresh_dps, dps_k)
            source = "LAN (na żywo)"
        if val_to_send is None:
            cached_dps = dev.get("dps", {}) or {}
            val_to_send = TuyaLocalManager.resolve_dps_value(cached_dps, dps_k)
            source = "Cache"
        if val_to_send is None:
            val_to_send = "OFF"
            source = "Domyślna (OFF)"

    extra = dict(m.get("extra", {}) or {})
    extra["version"] = dev.get("version", "3.3")
    discovery_topic, cfg = MQTTDiscoveryBuilder.build_config(
        component=m["component"],
        device_id=dev_id,
        device_name=dev.get("name", dev_id),
        dps_key=dps_k,
        dps_name=entity_name,
        extra_options=extra
    )

    mqtt_service.publish_status_online()
    mqtt_service.publish_discovery(discovery_topic, cfg)
    mqtt_service.register_command_handler(dev_id, on_mqtt_command)
    sent_payload = mqtt_service.publish_mapped_value(dev_id, dps_k, val_to_send, extra, component=m.get("component", "sensor"))

    return {
        "success": True,
        "topic": cfg.get("state_topic") or cfg.get("stat_t"),
        "payload": sent_payload,
        "source": source
    }

# --- ENDPOINTY UNIFI & SIECI LAN ---

def get_unifi_mgr() -> UniFiManager:
    cfg = Storage.load_settings()
    return UniFiManager(
        host=cfg.get("unifi_host", "192.168.1.2"),
        port=cfg.get("unifi_port", 443),
        api_key=cfg.get("unifi_api_key", ""),
        user=cfg.get("unifi_user", ""),
        password=cfg.get("unifi_password", ""),
        site=cfg.get("unifi_site", "default"),
        verify_ssl=cfg.get("unifi_verify_ssl", False)
    )

@app.get("/api/unifi/test")
async def unifi_test():
    mgr = get_unifi_mgr()
    success = mgr.login()
    return {"success": success, "error": None if success else "Nie mozna zautoryzowac w UniFi (sprawdz IP oraz API Key / uzytkownika)"}

@app.get("/api/network/clients")
async def network_clients(refresh: bool = False):
    """Pobiera listę klientów z kontrolera UniFi oraz ARP"""
    global network_clients_cache
    if not refresh and network_clients_cache:
        return {"clients": network_clients_cache, "count": len(network_clients_cache)}

    clients_by_mac = {}

    # 1. ARP ze skanera
    arp_devs = scan_lan_arp()
    for d in arp_devs:
        mac = d["mac"]
        clients_by_mac[mac] = d

    # 2. UniFi Controller API
    try:
        mgr = get_unifi_mgr()
        unifi_list = mgr.get_clients()
        for c in unifi_list:
            mac = c["mac"]
            clients_by_mac[mac] = c
    except Exception as e:
        logger.error(f"Blad pobierania klientow z UniFi: {e}")

    network_clients_cache = list(clients_by_mac.values())
    return {"clients": network_clients_cache, "count": len(network_clients_cache)}

@app.post("/api/unifi/set_fixed_ip")
async def unifi_set_fixed_ip(req: Request):
    body = await req.json()
    mac = body.get("mac")
    ip = body.get("ip")
    name = body.get("name")
    dev_id = body.get("device_id")

    mgr = get_unifi_mgr()
    result = mgr.set_fixed_ip(mac, ip, name)

    if result.get("success") and dev_id:
        if dev_id in devices:
            devices[dev_id]["ip"] = ip
            devices[dev_id]["mac"] = mac
            Storage.save_devices(devices)
            tuya_local.update_device_list(devices)

        matches[dev_id] = {
            "local_ip": ip,
            "mac": mac,
            "status": "Zapisany stały IP w UniFi",
            "updated_at": time.time()
        }
        Storage.save_matches(matches)

    return result

# --- ENDPOINTY ZAAWANSOWANEGO DOPASOWYWANIA ---

@app.get("/api/matches")
async def get_matches():
    current_devs = Storage.load_devices()
    current_matches = Storage.load_matches()

    items = []
    for dev_id, d in current_devs.items():
        m_info = current_matches.get(dev_id, {})
        local_ip = m_info.get("local_ip") or d.get("ip", "")
        mac = m_info.get("mac") or d.get("mac", "")
        status = m_info.get("status") or ("Skonfigurowany" if local_ip else "Oczekuje na przypisanie")
        
        items.append({
            "device_id": dev_id,
            "name": d.get("name", dev_id),
            "category": d.get("category", "-"),
            "cloud_ip": d.get("cloud_ip", "") or d.get("ip", ""),
            "local_ip": local_ip,
            "mac": mac,
            "local_key": d.get("local_key", ""),
            "is_sub": bool(d.get("node_id") or d.get("gateway_id")),
            "status": status
        })

    return {"matches": items, "count": len(items)}

@app.post("/api/matches/auto")
async def auto_match():
    current_devs = Storage.load_devices()
    clients_resp = await network_clients(refresh=True)
    clients = clients_resp.get("clients", [])

    matched_count = 0
    for dev_id, tdev in current_devs.items():
        if dev_id in matches and matches[dev_id].get("status", "").startswith("Wymuszony"):
            continue

        tuya_name = tdev.get("name", "").lower().strip()
        tuya_cloud_ip = tdev.get("ip", "").strip()

        found_mac = None
        found_ip = None
        found_name = ""

        for c in clients:
            c_name = (c.get("name") or "").lower().strip()
            c_ip = c.get("ip", "")
            if tuya_name and c_name and (tuya_name == c_name or tuya_name in c_name or c_name in tuya_name):
                found_mac = c.get("mac")
                found_ip = c_ip
                found_name = c.get("name", "")
                break

        if not found_mac and tuya_cloud_ip and not tuya_cloud_ip.startswith("10.") and not tuya_cloud_ip.startswith("172."):
            for c in clients:
                if c.get("ip") == tuya_cloud_ip:
                    found_mac = c.get("mac")
                    found_ip = tuya_cloud_ip
                    found_name = c.get("name", "")
                    break

        if found_mac and found_ip:
            matches[dev_id] = {
                "local_ip": found_ip,
                "mac": found_mac,
                "status": f"Dopasowano automatycznie ({found_name})",
                "updated_at": time.time()
            }
            current_devs[dev_id]["ip"] = found_ip
            current_devs[dev_id]["mac"] = found_mac
            matched_count += 1
        else:
            if tdev.get("node_id"):
                matches[dev_id] = {
                    "local_ip": "-",
                    "mac": "-",
                    "status": "Zigbee za bramka",
                    "updated_at": time.time()
                }
            elif dev_id not in matches:
                matches[dev_id] = {
                    "local_ip": current_devs[dev_id].get("ip", ""),
                    "mac": current_devs[dev_id].get("mac", ""),
                    "status": "Niepowiazane",
                    "updated_at": time.time()
                }

    devices.update(current_devs)
    Storage.save_devices(devices)
    Storage.save_matches(matches)
    tuya_local.update_device_list(devices)

    return {"success": True, "matched": matched_count, "total": len(devices)}

@app.post("/api/matches/bind")
async def bind_device(req: Request):
    body = await req.json()
    dev_id = body.get("device_id")
    mac = body.get("mac")
    ip = body.get("ip")
    client_name = body.get("client_name", "")

    if not dev_id or not mac or not ip:
        return {"success": False, "error": "Brak wymaganych pol: device_id, mac, ip"}

    matches[dev_id] = {
        "local_ip": ip,
        "mac": mac,
        "status": f"Recznie powiazany ({client_name})" if client_name else "Recznie powiazany",
        "updated_at": time.time()
    }
    Storage.save_matches(matches)

    if dev_id in devices:
        devices[dev_id]["ip"] = ip
        devices[dev_id]["mac"] = mac
        Storage.save_devices(devices)
        tuya_local.update_device_list(devices)

    return {"success": True, "match": matches[dev_id]}

@app.post("/api/matches/unbind")
async def unbind_device(req: Request):
    body = await req.json()
    dev_id = body.get("device_id")
    if dev_id in matches:
        del matches[dev_id]
        Storage.save_matches(matches)
    return {"success": True}

@app.post("/api/matches/force_ip")
async def force_local_ip(req: Request):
    body = await req.json()
    dev_id = body.get("device_id")
    new_ip = body.get("ip", "").strip()
    mac = body.get("mac", "").strip()

    if not dev_id or not new_ip:
        return {"success": False, "error": "Wymagany device_id oraz docelowy ip"}

    matches[dev_id] = {
        "local_ip": new_ip,
        "mac": mac or (devices.get(dev_id, {}).get("mac", "")),
        "status": "Wymuszony lokalny IP",
        "updated_at": time.time()
    }
    Storage.save_matches(matches)

    if dev_id in devices:
        devices[dev_id]["ip"] = new_ip
        if mac:
            devices[dev_id]["mac"] = mac
        Storage.save_devices(devices)
        tuya_local.update_device_list(devices)

    return {"success": True, "match": matches[dev_id]}

@app.post("/api/matches/test_lan")
async def test_lan_connection(req: Request):
    body = await req.json()
    dev_id = body.get("device_id", "")
    ip = body.get("ip", "").strip()

    if not ip and dev_id in devices:
        ip = devices[dev_id].get("ip", "")

    if not ip:
        return {"success": False, "error": "Brak adresu IP do przetestowania"}

    dev_info = devices.get(dev_id, {})
    local_key = dev_info.get("local_key", "")
    try:
        ver = float(dev_info.get("version", 3.3))
    except (ValueError, TypeError):
        ver = 3.3

    result = await asyncio.to_thread(tuya_local.test_connection, ip, dev_id, local_key, ver)
    if dev_id and dev_id in devices:
        updated = False
        if result.get("detected_version") and str(devices[dev_id].get("version", "")) != str(result["detected_version"]):
            devices[dev_id]["version"] = str(result["detected_version"])
            updated = True
        if ip and devices[dev_id].get("ip") != ip:
            devices[dev_id]["ip"] = ip
            updated = True
        if updated:
            Storage.save_devices(devices)
            tuya_local.update_device_list(devices)
        if result.get("dps"):
            on_local_status_update(dev_id, result["dps"])

    return {"success": result["tcp_ok"], "details": result}

# --- ENDPOINTY TUYA QR & LOCAL KEY EXTRACTOR ---

tuya_extractor = TuyaLocalKeyExtractorService()

@app.post("/api/tuya/qr/generate")
async def tuya_generate_qr(req: Request):
    body = await req.json()
    user_code = body.get("user_code", "").strip()
    schema = body.get("schema", "smartlife").strip()
    
    if user_code:
        Storage.save_settings({"tuya_user_code": user_code})

    qr_data = tuya_extractor.create_qr_code(user_code, schema=schema)
    return qr_data

def _merge_cloud_device(d: dict):
    dev_id = d["id"]
    d["cloud_ip"] = d.get("ip", "")
    if dev_id in devices:
        old = devices[dev_id]
        # Zachowaj wymuszony/lokalny IP, MAC, wersję protokołu oraz własną nazwę
        if dev_id in matches and matches[dev_id].get("local_ip") and matches[dev_id]["local_ip"] != "-":
            d["ip"] = matches[dev_id]["local_ip"]
        elif old.get("ip"):
            d["ip"] = old["ip"]
        if old.get("mac"):
            d["mac"] = old["mac"]
        if old.get("version"):
            d["version"] = old["version"]
        if old.get("name"):
            d["name"] = old["name"]
        # Połącz DPS zamiast nadpisywać
        merged_dps = dict(d.get("dps") or {})
        if isinstance(old.get("dps"), dict):
            merged_dps.update(old["dps"])
        d["dps"] = merged_dps
    devices[dev_id] = d

@app.get("/api/tuya/qr/status")
async def tuya_qr_status(token: str):
    res = tuya_extractor.check_qr_login(token)
    if res.get("status") == "confirmed" and "devices" in res:
        for d in res["devices"]:
            _merge_cloud_device(d)
        Storage.save_devices(devices)
        tuya_local.update_device_list(devices)
    return res

@app.post("/api/tuya/refresh_cloud")
async def tuya_refresh_cloud():
    dev_list = tuya_extractor.refresh_cloud_devices()
    if dev_list:
        for d in dev_list:
            _merge_cloud_device(d)
        Storage.save_devices(devices)
        tuya_local.update_device_list(devices)
        return {"success": True, "count": len(dev_list)}
    return {"success": False, "error": "Brak aktywnej sesji chmurowej Tuya. Zaloguj sie ponownie kodem QR."}

@app.post("/api/devices/import_json")
async def import_devices_json(req: Request):
    try:
        body = await req.json()
        dev_list = body if isinstance(body, list) else body.get("devices", [])
        count = 0
        for item in dev_list:
            dev_id = item.get("id")
            if not dev_id:
                continue
            devices[dev_id] = {
                "id": dev_id,
                "name": item.get("name", f"Tuya {dev_id}"),
                "ip": item.get("ip", ""),
                "mac": item.get("mac", ""),
                "local_key": item.get("local_key", ""),
                "node_id": item.get("node_id", "") or item.get("cid", ""),
                "gateway_id": item.get("gateway_id", "") or item.get("gw_id", ""),
                "version": item.get("version", "3.3"),
                "dps": item.get("dps", {}) or {}
            }
            count += 1
        Storage.save_devices(devices)
        tuya_local.update_device_list(devices)
        return {"success": True, "count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8099, proxy_headers=True, forwarded_allow_ips="*")
