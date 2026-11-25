#!/usr/bin/with-contenv bashio
set -e

bashio::log.info "Uruchamianie Tuya UniFi Hub v2.0.11..."

mkdir -p /data/tuya_bridge
export DATA_DIR="/data/tuya_bridge"

# Pobierz ingress path z konfiguracji HA (dostÄ™pne jako zmienna Ĺ›rodowiskowa)
INGRESS_PATH=$(bashio::addon.ingress_url 2>/dev/null || echo "")
export INGRESS_PATH

bashio::log.info "Ingress URL: ${INGRESS_PATH}"

cd /app
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8099 --proxy-headers --forwarded-allow-ips "*" --log-level info
