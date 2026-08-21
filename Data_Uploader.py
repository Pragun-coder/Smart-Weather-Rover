import socket
import time
import json
import random
import threading
import requests
import paho.mqtt.client as mqtt

# ================= CONFIGURATION =================
# IP & Port of your TCP Serial App running on Android
SERIAL_IP = "127.0.0.1"   # Use '127.0.0.1' or your local phone IP
SERIAL_PORT = 2233       # Replace with the exact port shown in your Serial Server App

WRITE_KEY = "Your_API_Key".strip()        # ThingSpeak API Key
GEMINI_API_KEY = "Your_API_Key"  # Replace with your actual key

BROKER = "Broker_name"
PORT = 1883
CMD_TOPIC = "Topic_name"
SENSOR_TOPIC = "Topic_name"
CLIENT_ID = f"termux_rover_{random.randint(1000, 9999)}"

# ================= SHARED TELEMETRY STATE =================
latest = {
    "temp": 0.0, "hum": 0.0, "press": 1013.25, "rain": 0, "soil": 0,
    "lat": 0.0, "lng": 0.0, "motor_v": 0.0, "motor_pct": 0,
    "logic_v": 0.0, "logic_pct": 0, "prediction": "Initializing AI..."
}
last_thingspeak_upload = 0
sock = None
sock_lock = threading.Lock()

# Helper for Safe Numeric Parsing
def safe_float(val, default=0.0):
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    try:
        return int(float(val.strip()))
    except (ValueError, TypeError):
        return default

# ================= TCP SERIAL SERVER CONNECTION =================
def connect_tcp_serial():
    global sock
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((SERIAL_IP, SERIAL_PORT))
            s.settimeout(None)  # Reset to blocking mode for recv
            print(f"✅ [IP SERIAL] Connected to Serial Server at {SERIAL_IP}:{SERIAL_PORT}")
            with sock_lock:
                sock = s
            return
        except Exception as e:
            print(f"⚠️ [IP SERIAL] Connection to {SERIAL_IP}:{SERIAL_PORT} failed ({e}). Retrying in 3s...")
            time.sleep(3)

# ================= GEMINI AI THREAD =================
def gemini_worker():
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}

    while True:
        if latest["temp"] != 0.0 and GEMINI_API_KEY and "YOUR_" not in GEMINI_API_KEY:
            prompt = (
                f"Analyze rover telemetry: Temp={latest['temp']}C, Hum={latest['hum']}%, "
                f"Rain={latest['rain']}, Soil={latest['soil']}. Provide a 1-sentence micro-climate prediction."
            )
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    pred = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    latest["prediction"] = pred
                    print(f"🤖 [GEMINI AI] {pred}")
            except Exception as e:
                print(f"⚠️ [GEMINI ERROR] {e}")
        time.sleep(30)

threading.Thread(target=gemini_worker, daemon=True).start()

# ================= MQTT CLIENT SETUP =================
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ [MQTT] Connected to Broker (broker.emqx.io)")
        client.subscribe(CMD_TOPIC)
    else:
        print(f"⚠️ [MQTT] Connection failed with code {rc}")

def on_message(client, userdata, msg):
    global sock
    try:
        cmd = msg.payload.decode().strip()
        print(f"📩 [MQTT RX -> ARDUINO] Command: '{cmd}'")
        with sock_lock:
            if sock:
                # Send command with newline termination for Arduino Serial reading
                sock.sendall((cmd + "\n").encode('utf-8'))
    except Exception as e:
        print(f"⚠️ [TCP WRITE ERROR] {e}")

# Handle paho-mqtt v1.x and v2.x compatibility
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)
except AttributeError:
    client = mqtt.Client(client_id=CLIENT_ID)

client.on_connect = on_connect
client.on_message = on_message

def mqtt_loop_manager():
    while True:
        try:
            client.connect(BROKER, PORT, keepalive=30)
            client.loop_forever()
        except Exception as e:
            print(f"⚠️ [MQTT DISCONNECTED] Reconnecting in 5s... ({e})")
            time.sleep(5)

threading.Thread(target=mqtt_loop_manager, daemon=True).start()

# ================= SERIAL TELEMETRY & THINGSPEAK THREAD =================
def serial_ip_worker():
    global last_thingspeak_upload, sock
    connect_tcp_serial()
    buffer = ""

    while True:
        try:
            data = sock.recv(1024).decode('utf-8', errors='ignore')
            if not data:
                raise socket.error("IP Serial Server closed connection")

            buffer += data
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip().replace("\r", "")
                if not line:
                    continue

                # Try JSON first, fall back to CSV
                try:
                    # Attempt JSON parse (full telemetry format from laptop)
                    if line.startswith("{"):
                        d = json.loads(line)
                        latest["temp"] = safe_float(str(d.get("temp", latest["temp"])), latest["temp"])
                        latest["hum"] = safe_float(str(d.get("hum", latest["hum"])), latest["hum"])
                        latest["press"] = safe_float(str(d.get("press", latest["press"])), latest["press"])
                        latest["rain"] = safe_int(str(d.get("rain", latest["rain"])), latest["rain"])
                        latest["soil"] = safe_int(str(d.get("soil", latest["soil"])), latest["soil"])
                        latest["lat"] = safe_float(str(d.get("lat", latest["lat"])), latest["lat"])
                        latest["lng"] = safe_float(str(d.get("lng", latest["lng"])), latest["lng"])
                        latest["motor_v"] = safe_float(str(d.get("motor_v", latest["motor_v"])), latest["motor_v"])
                        latest["motor_pct"] = safe_int(str(d.get("motor_pct", latest["motor_pct"])), latest["motor_pct"])
                        latest["logic_v"] = safe_float(str(d.get("logic_v", latest["logic_v"])), latest["logic_v"])
                        latest["logic_pct"] = safe_int(str(d.get("logic_pct", latest["logic_pct"])), latest["logic_pct"])
                        print(f"✅ [JSON TELEMETRY] Temp={latest['temp']}C, Hum={latest['hum']}%")
                    else:
                        raise ValueError("Not JSON, trying CSV")
                except (json.JSONDecodeError, ValueError):
                    # Fall back to CSV format (from phone Termux)
                    d = line.split(",")
                    # CSV: temp, hum, rain, soil, lat, lng, press, motor_v, motor_pct, logic_v, logic_pct
                    if len(d) >= 6:
                        latest["temp"] = safe_float(d[0], latest["temp"])
                        latest["hum"] = safe_float(d[1], latest["hum"])
                        latest["rain"] = safe_int(d[2], latest["rain"])
                        latest["soil"] = safe_int(d[3], latest["soil"])
                        latest["lat"] = safe_float(d[4], latest["lat"])
                        latest["lng"] = safe_float(d[5], latest["lng"])

                        if len(d) >= 7:
                            latest["press"] = safe_float(d[6], latest["press"])
                        if len(d) >= 11:
                            latest["motor_v"] = safe_float(d[7], latest["motor_v"])
                            latest["motor_pct"] = safe_int(d[8], latest["motor_pct"])
                            latest["logic_v"] = safe_float(d[9], latest["logic_v"])
                            latest["logic_pct"] = safe_int(d[10], latest["logic_pct"])
                        
                        print(f"✅ [CSV TELEMETRY] Temp={latest['temp']}C, Hum={latest['hum']}%")

                    # 1. Publish Telemetry via MQTT to Web Dashboard
                    json_payload = json.dumps(latest)
                    client.publish(SENSOR_TOPIC, json_payload, qos=0)
                    print(f"📡 [MQTT TX] Sent: Temp={latest['temp']}C, Hum={latest['hum']}%, Rain={latest['rain']}")

                    # 2. Upload to ThingSpeak every 15s
                    if time.time() - last_thingspeak_upload >= 16:  # 1s buffer above ThingSpeak's 15s hard minimum
                        # Mark this slot as used BEFORE firing the request, not just on
                        # success. Previously, a single rejection/error left the timer
                        # untouched, so the very next telemetry line (as little as 10ms
                        # later, since CSV+JSON are sent back-to-back) would retry
                        # immediately -- a rapid-fire loop that kept re-triggering
                        # ThingSpeak's rate limit instead of backing off from it.
                        last_thingspeak_upload = time.time()

                        ts_url = "https://api.thingspeak.com/update"
                        ts_params = {
                            "api_key": WRITE_KEY,
                            "field1": f"{latest['temp']:.2f}",       # Temperature (C)
                            "field2": f"{latest['hum']:.2f}",        # Humidity (%)
                            "field3": latest["rain"],                # Rain
                            "field4": latest["soil"],                # Soil Moisture
                            "field5": f"{latest['press']:.2f}",      # Air Pressure (hPa)
                            "field6": f"{latest['motor_pct']}",      # Motor Battery (%)
                            "field7": f"{latest['logic_pct']}"       # Logic Battery (%)
                        }
                        try:
                            res = requests.get(ts_url, params=ts_params, timeout=10)
                            body = res.text.strip()

                            if res.status_code == 200 and body != '0':
                                print(f"📊 [THINGSPEAK SUCCESS] Entry ID: {body}")
                            elif res.status_code == 429 or "exceeded" in body.lower():
                                # THIS is the real rate-limit signature -- ThingSpeak
                                # actually says "exceeded" or returns HTTP 429 when it's
                                # genuinely a timing issue, not a key problem.
                                print(f"⚠️ [THINGSPEAK RATE LIMIT] HTTP {res.status_code}, body='{body}' -- another process/device may ALSO be writing to this same channel/key. Check for a second running copy of this script, or another app/browser tab still hitting ThingSpeak with the same key.")
                            elif body == '0':
                                # ThingSpeak returns bare "0" for: bad/expired API key,
                                # channel field mismatch, or (less often) rate limiting.
                                # A masked view of the key actually being sent, so a typo
                                # or stray whitespace is visible without printing it in full.
                                masked = (WRITE_KEY[:4] + "..." + WRITE_KEY[-4:]) if len(WRITE_KEY) > 8 else "(key too short?)"
                                print(f"⚠️ [THINGSPEAK REJECTED] Body='0' (generic failure). Key being sent: {masked} (len={len(WRITE_KEY)}). Verify on ThingSpeak: this EXACT key is your channel's current WRITE key, and the channel has at least 6 fields defined (field1-field6).")
                            else:
                                print(f"⚠️ [THINGSPEAK UNKNOWN RESPONSE] HTTP {res.status_code}, body='{body}'")
                        except Exception as req_err:
                            print(f"⚠️ [THINGSPEAK HTTP ERROR] {req_err} -- will retry in 15s")

        except (socket.error, Exception) as e:
            print(f"⚠️ [IP SERIAL DROPPED] {e}. Reconnecting...")
            with sock_lock:
                if sock:
                    sock.close()
                    sock = None
            connect_tcp_serial()
            buffer = ""

threading.Thread(target=serial_ip_worker, daemon=True).start()

# ================= MAIN TERMUX LOOP =================
print("🚀 Termux Rover Bridge Active. Listening for telemetry...")
while True:
    time.sleep(1)