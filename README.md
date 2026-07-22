# 🚜 Pragun Smart Rover 2026

An IoT-enabled, solar-assisted smart rover built with an **Arduino Nano**, **Python Base Station**, and a live **Web Dashboard** hosted on GitHub Pages. 

The system features real-time **MQTT teleoperation**, dynamic **GPS tracking**, **environmental sensor monitoring**, automatic **ThingSpeak data logging**, and ultra-low-latency **WebRTC video streaming** via VDO.Ninja—completely bypassing campus firewalls and dynamic IP restrictions.

---

## 🌟 Key Features

* 🎮 **Real-Time Teleoperation:** Responsive WASD and UI button control via MQTT WebSockets over `broker.emqx.io`.
* 📹 **Cloud WebRTC Video Streaming:** Embedded live camera feed with permanent session mapping (`VDO.Ninja`), bypassing IP blocks and VPN changes.
* 🗺️ **GPS Navigation & Mapping:** Dynamic route tracking and location plotting powered by LeafletJS and OpenStreetMap.
* 📊 **Live Telemetry & Analytics:** Real-time sensor charts (Temperature & Humidity) using Chart.js alongside live readings for soil moisture, rain detection, and distance metrics.
* ☁️ **Cloud Data Logging:** Automatic sensor data uploads to ThingSpeak every 15 seconds.
* ⚡ **Dual Power System:** Independent battery isolation (3A BMS for logic, 10A BMS for motors) with solar-assisted charging via a TP5100 module.

---

## 🛠️ System Architecture

```text
 [ Web Dashboard ] ──(WebSockets / MQTT)──► [ Python Base Station ] ──(USB Serial)──► [ Arduino Nano ]
 (GitHub Pages)                                  (thinging.py)                             │
       ▲                                               │                                   ├──► L298N ──► BO Motors
       │                                               ▼                                   ├──► Sensors (GPS, DHT, Soil)
 [ Phone Camera ] ───(WebRTC / VDO.Ninja)──────────────┴─────────────────────────────────► └──► Servos
