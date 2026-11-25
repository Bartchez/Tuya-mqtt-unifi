# Tuya UniFi Hub (Home Assistant Add-on v2.0)

Kompletne, połączone rozwiązanie integrujące możliwości projektów **Tuya ha** oraz **Wymuszenie tuya**:
1. **Dopasowanie Tuya <-> UniFi & Wymuszanie IP**:
   * Pobieranie urządzeń z Tuya Cloud (autoryzacja HA QR).
   * Pobieranie listy klientów z kontrolera **UniFi OS** (zarówno przez klucz `X-API-KEY`, jak i login/hasło) oraz ze skanera ARP lokalnej sieci LAN.
   * **Inteligentne automatyczne parowanie** urządzeń Tuya z klientami UniFi na podstawie nazwy urządzenia oraz IP.
   * **Ręczne powiązanie** (wyszukiwarka klientów UniFi/LAN, wybór urządzenia, podgląd MAC i stałego IP).
   * **Wymuszenie lokalnego adresu IP** (ręczne nadanie adresu IP dla urządzenia Tuya w konfiguracji).
   * **Zapis stałego IP w UniFi (DHCP Fixed IP Reservation)** bezpośrednio z poziomu panelu dodatku.
   * **Narzędzie Test LAN (Port 6668)** – testowanie otwarcia portu protokołu Tuya i odpytanie parametrów DPS przez sieć lokalną.

2. **Lokalna kontrola Tuya LAN (TinyTuya)**:
   * Bezpośrednia komunikacja bez opóźnień chmury dla wersji 3.1, 3.3, 3.4, 3.5.
   * Pełne wsparcie dla bramek i urządzeń podbramkowych Zigbee/BLE.

3. **Dwukierunkowy mostek MQTT z Home Assistant Discovery**:
   * Automatyczne tworzenie encji: `sensor`, `switch`, `light`, `climate`.
   * Natychmiastowe sterowanie i odczyt stanów na żywo.

4. **Wygodny interfejs w Home Assistant (Ingress)**:
   * Bezpośredni dostęp z lewego menu Home Assistanta.

---

## 🚀 Jak wgrać dodatek do Home Assistanta?

1. Skopiuj zawartość folderu `Tuya-mqtt-ip` na swój dysk Home Assistanta do katalogu `/addons/tuya_mqtt_ip` (np. przez Sambę lub SSH).
2. W Home Assistancie przejdź do: **Ustawienia -> Dodatki -> Sklep z dodatkami**.
3. W prawym górnym rogu kliknij ikonę trzech kropek `⋮` i wybierz **Sprawdź dostępność aktualizacji** (Odśwież).
4. W sekcji **Lokalne dodatki** pojawi się kafelek: **Tuya UniFi Hub**.
5. Kliknij **Zainstaluj**, włącz **Pokaż na pasku bocznym** i **Uruchom**.
