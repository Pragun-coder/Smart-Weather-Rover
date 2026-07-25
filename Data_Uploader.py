import serial
import time
import json
import threading
import requests
import cv2
from flask import Flask, Response
import paho.mqtt.client as mqtt

# ================= CONFIGURATION =================
COM_PORT = "COM6"
BAUD = 9600  # Matches Arduino Serial.begin() rate

# ThingSpeak Settings
WRITE_KEY = "your thingspeak write key"  # Your ThingSpeak Write API Key
UPLOAD_INTERVAL = 15  # Seconds between ThingSpeak uploads

# Google Gemini API Settings
# ------------------------------------------------------------------
# 🔑 PASTE YOUR GOOGLE GEMINI API KEY INSIDE THE QUOTES BELOW:
GEMINI_API_KEY = "your api key"
GEMINI_INTERVAL = 30  # Seconds between Gemini AI forecasts
# ------------------------------------------------------------------

# MQTT Settings
BROKER = "broker.emqx.io"
PORT = 1883
CMD_TOPIC = "pragun_rover_2026/cmd"
SENSOR_TOPIC = "pragun_rover_2026/sensors"

# Camera Config (Local Backup Server)
CAM_PORT = 5000
PHONE_CAM_URL = "http://yourip:8080/video"  # Update with your IP webcam URL

# ================= SERIAL CONNECTION =================
try:
    ser = serial.Serial(COM_PORT, BAUD, timeout=0.5)
    print(f"[SERIAL] Connected successfully to {COM_PORT} at {BAUD} baud.")
except Exception as e:
    print(f"[SERIAL ERROR] Could not open {COM_PORT}: {e}")
    ser = None

# ================= TELEMETRY DATA STATE =================
latest = {
    "temp": 0.0,
    "hum": 0.0,
    "rain": 0,
    "soil": 0,
    "lat": 0.0,
    "lng": 0.0,
    "prediction": "INITIALIZING GEMINI AI..."
}
lastUpload = 0

# ================= GOOGLE GEMINI AI ENGINE =================
def fetch_gemini_forecast():
    """
    Sends live rover sensor telemetry to Google Gemini AI
    to generate real-time smart forecasts & recommendations.
    """
    global latest

    if GEMINI_API_KEY == "PASTE_YOUR_GEMINI_API_KEY_HERE" or not GEMINI_API_KEY:
        latest["prediction"] = "⚠️ GEMINI_API_KEY NOT SET IN CODE"
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}

    prompt = (
        f"You are an agricultural AI engine for a smart rover. "
        f"Analyze these live sensor readings:\n"
        f"- Temperature: {latest['temp']}°C\n"
        f"- Humidity: {latest['hum']}%\n"
        f"- Rain Sensor: {latest['rain']} (Analog reading: <300 means heavy rain, >800 means dry)\n"
        f"- Soil Moisture: {latest['soil']} (Analog reading: <300 means wet/irrigated, >700 means dry soil)\n"
        f"- GPS Location: ({latest['lat']}, {latest['lng']})\n\n"
        f"Provide a short, 1-sentence micro-climate forecast and action advice with emojis. "
        f"Keep your entire answer under 20 words."
    )

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            data = res.json()
            forecast_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            latest["prediction"] = forecast_text
            print(f"[GEMINI AI] Forecast Updated: {forecast_text}")
        else:
            print(f"[GEMINI ERROR] Status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[GEMINI ERROR] Request failed: {e}")

def gemini_thread():
    """
    Background worker thread to request Gemini forecasts periodically
    without blocking the Serial hardware loop.
    """
    while True:
        # Only query Gemini when valid telemetry data is received
        if latest["temp"] != 0.0 or latest["hum"] != 0.0 or latest["soil"] != 0:
            fetch_gemini_forecast()
        time.sleep(GEMINI_INTERVAL)

# Start Gemini AI Thread
threading.Thread(target=gemini_thread, daemon=True).start()

# ================= MQTT HANDLERS =================
client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("\n====================================")
        print(" [MQTT] CONNECTED TO BROKER")
        print(" BROKER :", BROKER)
        print(" TOPIC  :", CMD_TOPIC)
        print("====================================\n")
        client.subscribe(CMD_TOPIC)
    else:
        print(f"[MQTT ERROR] Connection failed with code {rc}")

def on_message(client, userdata, msg):
    try:
        cmd = msg.payload.decode().strip()
        print(f"[MQTT CMD] Received: '{cmd}'")
        if ser and ser.is_open:
            ser.write((cmd + "\n").encode())
            print(f"[SERIAL TX] Forwarded '{cmd}' to Arduino")
        else:
            print("[SERIAL WARNING] Serial port not connected. Command dropped.")
    except Exception as e:
        print(f"[MQTT ERROR] Failed to process message: {e}")

client.on_connect = on_connect
client.on_message = on_message

try:
    client.connect(BROKER, PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"[MQTT ERROR] Could not connect to broker {BROKER}: {e}")

# ================= OPTIONAL FLASK CAMERA STREAM =================
app = Flask(__name__)

def generate_frames():
    camera = cv2.VideoCapture(PHONE_CAM_URL)
    while True:
        success, frame = camera.read()
        if not success:
            camera.open(PHONE_CAM_URL)
            time.sleep(1)
            continue
        else:
            ret, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_camera_server():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=CAM_PORT, debug=False, use_reloader=False)

# Start local camera server thread in background
threading.Thread(target=run_camera_server, daemon=True).start()

# ================= SERIAL READER THREAD =================
def serialThread():
    global latest, lastUpload

    while True:
        try:
            if ser and ser.is_open and ser.in_waiting:
                raw = ser.readline()
                line = raw.decode("utf-8", errors="ignore").strip()

                if not line:
                    continue

                print(f"[SERIAL RX] {line}")
                data = line.split(",")

                # Expecting CSV format: temp,hum,rain,soil,lat,lng
                if len(data) == 6:
                    try:
                        latest["temp"] = float(data[0])
                        latest["hum"] = float(data[1])
                        latest["rain"] = int(float(data[2]))
                        latest["soil"] = int(float(data[3]))
                        latest["lat"] = float(data[4])
                        latest["lng"] = float(data[5])
                    except ValueError as ve:
                        print(f"[PARSING ERROR] Invalid data received: {ve}")
                        continue

                    # 1. Publish Telemetry + Gemini AI Prediction via MQTT to Dashboard
                    client.publish(SENSOR_TOPIC, json.dumps(latest))

                    # 2. Upload to ThingSpeak at scheduled interval
                    if time.time() - lastUpload > UPLOAD_INTERVAL:
                        payload = {
                            "api_key": WRITE_KEY,
                            "field1": latest["temp"],
                            "field2": latest["hum"],
                            "field3": latest["rain"],
                            "field4": latest["soil"],
                            "field5": latest["lat"],
                            "field6": latest["lng"]
                        }

                        try:
                            r = requests.get("https://api.thingspeak.com/update", params=payload, timeout=5)
                            print(f"[THINGSPEAK] Upload status entry ID: {r.text}")
                        except Exception as req_err:
                            print(f"[THINGSPEAK ERROR] Upload failed: {req_err}")

                        lastUpload = time.time()

        except Exception as e:
            print(f"[SERIAL THREAD ERROR] {e}")
            time.sleep(1)

# Start serial thread in background
threading.Thread(target=serialThread, daemon=True).start()

# ================= MAIN BASE STATION LOOP =================
print("====================================")
print("🚜 PRAGUN SMART ROVER BASE STATION")
print("====================================")
print(f"COM PORT        : {COM_PORT}")
print(f"MQTT BROKER     : {BROKER}")
print(f"COMMAND TOPIC   : {CMD_TOPIC}")
print(f"SENSOR TOPIC    : {SENSOR_TOPIC}")
print(f"GEMINI AI       : ENABLED (Interval: {GEMINI_INTERVAL}s)")
print(f"ThingSpeak Key  : {WRITE_KEY}")
print(f"ThingSpeak Rate : Every {UPLOAD_INTERVAL}s")
print(f"LOCAL CAM URL   : http://localhost:{CAM_PORT}/video")
print("====================================")
print("SYSTEM READY. WAITING FOR DATA & COMMANDS...\n")

while True:
    time.sleep(1)