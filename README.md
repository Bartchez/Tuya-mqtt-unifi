# Tuya UniFi Hub – Home Assistant Add-on Repository

Oficjalne repozytorium dodatku **Tuya UniFi Hub** dla Home Assistanta.

## 🚀 Instalacja w Home Assistancie (1 kliknięcie)

[![Dodaj repozytorium do mojego Home Assistanta](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBartchez%2FTuya-mqtt-unifi)

### Lub ręcznie:
1. W Home Assistancie przejdź do **Ustawienia → Dodatki → Sklep z dodatkami**.
2. W prawym górnym rogu kliknij **⋮ (trzy kropki) → Repozytoria**.
3. Wklej adres repozytorium:
   ```
   https://github.com/Bartchez/Tuya-mqtt-unifi
   ```
4. Kliknij **Dodaj**, odśwież stronę sklepu i zainstaluj **Tuya UniFi Hub**.

## ✨ Główne funkcje
- **Dopasowanie Tuya ↔ UniFi & Wymuszanie IP**: automatyczne i ręczne parowanie urządzeń Tuya z klientami routera UniFi OS (API Key lub login/hasło) + skanowanie ARP.
- **Stała rezerwacja DHCP w UniFi (Fixed IP)** bezpośrednio z panelu dodatku.
- **Lokalna kontrola Tuya LAN (TinyTuya)** z automatycznym wykrywaniem wersji protokołu (`3.1`, `3.3`, `3.4`, `3.5`) oraz obsługą urządzeń podbramkowych Zigbee/BLE.
- **Mostek MQTT + Home Assistant MQTT Discovery** (`sensor`, `switch`, `light`, `climate`) z wbudowanym przyciskiem **Test** dla każdego mapowania.
- **Logowanie kodem QR** z aplikacji Smart Life / Tuya Smart bez konta deweloperskiego.
- **Pełna integracja z panelem bocznym HA (Ingress)**.
