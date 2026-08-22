# 🚜 Pragun Smart Rover 2026

An IoT-enabled, solar-assisted smart rover built with an **Arduino Nano**, a **Python/Termux Base Station**, and a live **Web Dashboard**.

The system features real-time **MQTT teleoperation**, live **GPS tracking on the dashboard map**, **environmental sensor monitoring**, automatic **ThingSpeak data logging**, remote **I2C-driven accessory control** (motors, headlight, cooling fan, soil probe servo), and low-latency **WebRTC video streaming** via VDO.Ninja — including a genuine, working remote camera on/off toggle, independent of campus firewalls and dynamic IP restrictions.

---

## 🌟 Key Features

- 🎮 **Real-Time Teleoperation** — Responsive UI-button control via MQTT over WebSockets (`wss://broker.emqx.io:8084/mqtt`).
- 📹 **Cloud WebRTC Video Streaming** — Embedded live camera feed via VDO.Ninja, routed through proxy mode to bypass network-level WebSocket blocks.
- 🔴 **Remote Camera On/Off** — Dashboard button that genuinely powers the phone's camera off and back on, via VDO.Ninja's HTTP remote-control API (`api.vdo.ninja`) — a real server-side relay, not a local video hide/show trick.
- 🗺️ **Live GPS Map** — Real-time position and route plotting on the dashboard (LeafletJS + OpenStreetMap). GPS is shown live on the dashboard only; it is intentionally **not** logged to ThingSpeak (see Cloud Data Logging below).
- 📊 **Live Telemetry & Analytics** — Real-time temperature/humidity charts (Chart.js), plus live pressure, soil moisture, rain, and dual-battery readings.
- ☁️ **Cloud Data Logging** — Automatic sensor uploads to ThingSpeak roughly every 16 seconds (see field mapping below).
- 🔌 **I2C Port-Expander Accessory Control** — Motors, headlight, and cooling fan all driven through a PCF8574 port expander, controlled by single-character serial commands.
- 🦾 **Buzz-Free Servo Control** — Soil probe servo attaches only while moving and detaches immediately after, eliminating idle jitter/buzz.
- ⚡ **Dual Power System** — Independent battery isolation (3A BMS for logic, 10A BMS for motors) with solar-assisted charging via a TP5100 module, both batteries tracked live and logged to ThingSpeak.

---

## 🛠️ System Architecture

```
[ Web Dashboard ] ──(MQTT over WebSockets, wss:8084)──► [ Python Bridge on Phone (Termux) ] ──(USB Serial)──► [ Arduino Nano ]
     (dashboard.html)                                        (Data_Uploader.py)                                     │
        ▲                                                          │                                                ├──► PCF8574 ──► Motors (F/B/L/R/S)
        │                                                          ▼                                                ├──► PCF8574 ──► Headlight / Cooling Fan
        │                                                   ThingSpeak (~every 16s)                                 ├──► Sensors (DHT11, BMP180, GPS, Soil, Rain)
        │                                                                                                           └──► Servo (Soil Probe, attach/detach)
        │
        └──(WebRTC via VDO.Ninja, proxy mode)──► [ Phone Camera (VDO.Ninja App) ]
```

**Telemetry path:** Arduino → USB Serial → Python bridge (accepts both CSV and JSON, auto-detected) → MQTT publish → Dashboard (live charts, GPS map, battery readouts) → periodic snapshot to ThingSpeak (excluding GPS).

**Command path:** Dashboard button/key → MQTT publish → Python bridge → USB Serial (single-character command) → Arduino → PCF8574 or servo.

**Video path:** Phone (VDO.Ninja app, room-based push) → VDO.Ninja relay (proxy mode) → Dashboard viewer iframe (clean, solo view). Camera on/off is sent from the dashboard directly to VDO.Ninja's HTTP API, which relays it to the phone — independent of the video/telemetry paths above.

---

## ☁️ ThingSpeak Field Mapping

Set these exact field names in **Channel Settings** on your ThingSpeak channel:

| Field | Name |
|---|---|
| Field 1 | Temperature (°C) |
| Field 2 | Humidity (%) |
| Field 3 | Rain |
| Field 4 | Soil Moisture |
| Field 5 | Air Pressure (hPa) |
| Field 6 | Motor Battery (%) |
| Field 7 | Logic Battery (%) |

> GPS latitude/longitude is deliberately **not** sent to ThingSpeak — it's shown live on the dashboard's own map instead. If you add it back, it needs its own two fields (e.g. Field 8/9) and a corresponding change in `Data_Uploader.py`.

---

## 📁 Repository Files

| File | Purpose |
|---|---|
| `dashboard.html` | The web dashboard — MQTT client, live telemetry, GPS map, VDO.Ninja video + camera control, AI microclimate summary. |
| `Data_Uploader.py` | Runs in Termux on the rover-mounted phone. Bridges Arduino USB serial ↔ MQTT, and uploads snapshots to ThingSpeak. |
| `weather_rover_base_station.ino` | Arduino Nano sketch — sensors, GPS, PCF8574-driven motors/accessories, soil probe servo, serial telemetry (CSV + JSON). |
| `Weather-Rover-Wiring.pdf` | Full wiring reference for sensors, PCF8574, battery isolation, and motor driver. |
| `requirements.txt` | Python dependencies for `Data_Uploader.py`. |
| `.env.example` | Template for local secrets (ThingSpeak key, MQTT topic names, etc.) — copy to `.env` and fill in your own values, never commit the real one. |

---

## ⚙️ Setup Overview

1. **Flash the Arduino** with `weather_rover_base_station.ino`.
2. **On the rover phone:** run a serial-server app (TCP bridge to the Arduino over USB OTG), and separately run the VDO.Ninja app to broadcast the camera into a private room.
3. **Run `Data_Uploader.py`** in Termux on the same phone — it connects to the local serial server, publishes telemetry over MQTT, relays incoming commands back to the Arduino, and uploads periodic snapshots to ThingSpeak. **Make sure only one copy of this script is running at a time** — a duplicate background instance will silently double up on ThingSpeak's rate limit.
4. **Open `dashboard.html`** (locally or hosted via GitHub Pages) — it connects to the same MQTT broker and VDO.Ninja room.
5. **Set matching credentials in all three places** — MQTT topics, VDO.Ninja room/password/stream ID, and the VDO.Ninja API key — must be identical across the dashboard, the phone's VDO.Ninja session, and `Data_Uploader.py`'s config section. Treat all of these as real credentials: don't reuse guessable values, and don't commit them to a public repo. **Rotate your ThingSpeak Write API Key if it's ever been shared or pasted anywhere public.**

---

## 🔧 Known Constraints

- The rover phone's VDO.Ninja session and the serial-server app must both stay active and awake in the foreground — backgrounding either can drop the stream or the serial bridge.
- Camera remote on/off relies on VDO.Ninja's HTTP API (`api.vdo.ninja`) and a persistent hidden director session on the dashboard; if VDO.Ninja's own service has an outage, this feature specifically may be affected even if video/telemetry keep working.
- If your network or ISP blocks direct WebSocket connections to VDO.Ninja, `&proxy` mode is already enabled on both the video viewer and the control session — no action needed unless you're hitting a *different* network's restrictions.
- ThingSpeak enforces a hard 15-second minimum between writes per channel/key; the uploader waits 16 seconds as a safety margin. If you see rate-limit errors even so, check for a duplicate running instance of `Data_Uploader.py` before assuming it's a code issue.

---

## 📜 License

MIT — see `LICENSE`.
