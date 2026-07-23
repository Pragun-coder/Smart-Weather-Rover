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
BAUD = 9600

# ThingSpeak Settings
WRITE_KEY = "05NUNO16U85E3BWS"
UPLOAD_INTERVAL = 15  # Seconds

# MQTT Settings
BROKER = "broker.emqx.io"
PORT = 1883
CMD_TOPIC = "pragun_rover_2026/cmd"
SENSOR_TOPIC = "pragun_rover_2026/sensors"

# Local Flask Camera Server Config
CAM_PORT = 5000
PHONE_CAM_URL = "http://192.168.1.50:8080/video"

# Default Coordinates if GPS has no fix yet (Vidyavihar / Jaipur, Rajasthan)
DEFAULT_LAT = 26.9124
DEFAULT_LNG = 75.7873

# ================= SERIAL CONNECTION =================
try:
    ser = serial.Serial(COM_PORT, BAUD, timeout=0.5)
    print(f"[SERIAL] Connected successfully to {COM_PORT} at {BAUD} baud.")
except Exception as e:
    print(f"[SERIAL ERROR] Could not open {COM_PORT}: {e}")
    ser = None

# ================= TELEMETRY STATE =================
latest = {
    # Local Rover Sensors
    "temp": 0.0,
    "hum": 0.0,
    "rain": 0,
    "soil": 0,
    "lat": DEFAULT_LAT,
    "lng": DEFAULT_LNG,
    "press": 1013.25,
    "bat": 100,
    
    # Regional API Insights
    "api_clouds": 0,          # % Cloud cover
    "api_rain": 0.0,          # mm of rain nearby
    "api_wind_speed": 0.0,    # km/h
    "api_wind_dir": "N/A",    # Cardinal Direction (e.g. NW)
    "api_condition": "Unknown" # Text description
}

lastUpload = 0
last_api_fetch = 0

# ================= WMO WEATHER CODE TRANSLATOR =================
def decode_wmo_code(code):
    codes = {
        0: "Clear Sky ☀️",
        1: "Mainly Clear 🌤️", 2: "Partly Cloudy ⛅", 3: "Overcast ☁️",
        45: "Fog 🌫️", 48: "Depositing Rime Fog 🌫️",
        51: "Light Drizzle 🌧️", 53: "Moderate Drizzle 🌧️", 55: "Dense Drizzle 🌧️",
        61: "Slight Rain 🌧️", 63: "Moderate Rain 🌧️", 65: "Heavy Rain 🌧️",
        80: "Slight Rain Showers 🌦️", 81: "Moderate Rain Showers 🌦️", 82: "Violent Rain Showers ⛈️",
        95: "Thunderstorm 🌩️", 96: "Thunderstorm with Hail ⛈️"
    }
    return codes.get(code, "Cloudy ☁️")

def degrees_to_cardinal(deg):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ix = int((deg + 22.5) / 45) % 8
    return dirs[ix]

# ================= OPEN-METEO WEATHER API THREAD =================
def fetch_api_weather():
    global latest, last_api_fetch

    while True:
        try:
            lat = latest["lat"] if latest["lat"] != 0.0 else DEFAULT_LAT
            lng = latest["lng"] if latest["lng"] != 0.0 else DEFAULT_LNG

            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lng}&current="
                f"precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m"
            )

            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json().get("current", {})
                
                latest["api_clouds"] = data.get("cloud_cover", 0)
                latest["api_rain"] = data.get("precipitation", 0.0)
                latest["api_wind_speed"] = data.get("wind_speed_10m", 0.0)
                
                wind_deg = data.get("wind_direction_10m", 0)
                latest["api_wind_dir"] = degrees_to_cardinal(wind_deg)
                
                wcode = data.get("weather_code", 0)
                latest["api_condition"] = decode_wmo_code(wcode)

                print(f"[WEATHER API] Sky: {latest['api_condition']} | Clouds: {latest['api_clouds']}% | Wind: {latest['api_wind_speed']} km/h {latest['api_wind_dir']}")

        except Exception as e:
            print(f"[WEATHER API ERROR] {e}")

        # Refresh weather API data every 5 minutes
        time.sleep(300)

threading.Thread(target=fetch_api_weather, daemon=True).start()

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

# ================= LOCAL CAMERA STREAM =================
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

                # CSV Format: temp,hum,rain,soil,lat,lng,pressure,battery
                if len(data) == 8:
                    latest["temp"] = float(data[0])
                    latest["hum"] = float(data[1])
                    latest["rain"] = int(data[2])
                    latest["soil"] = int(data[3])
                    
                    parsed_lat = float(data[4])
                    parsed_lng = float(data[5])
                    if parsed_lat != 0.0: latest["lat"] = parsed_lat
                    if parsed_lng != 0.0: latest["lng"] = parsed_lng
                    
                    latest["press"] = float(data[6])
                    latest["bat"] = int(data[7])

                    # 1. Publish Combined Telemetry via MQTT to Dashboard
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
                            "field6": latest["lng"],
                            "field7": latest["press"],
                            "field8": latest["bat"]
                        }
                        
                        try:
                            r = requests.get("https://api.thingspeak.com/update", params=payload, timeout=5)
                            print(f"[THINGSPEAK] Upload status: {r.text}")
                        except Exception as req_err:
                            print(f"[THINGSPEAK ERROR] Upload failed: {req_err}")

                        lastUpload = time.time()

        except Exception as e:
            print(f"[SERIAL THREAD ERROR] {e}")
            time.sleep(1)

threading.Thread(target=serialThread, daemon=True).start()

# ================= MAIN BASE STATION LOOP =================
print("====================================")
print("🚜 PRAGUN SMART ROVER BASE STATION")
print("====================================")
print(f"COM PORT       : {COM_PORT}")
print(f"MQTT BROKER    : {BROKER}")
print(f"COMMAND TOPIC  : {CMD_TOPIC}")
print(f"SENSOR TOPIC   : {SENSOR_TOPIC}")
print(f"WEATHER API    : Open-Meteo Integrated")
print(f"ThingSpeak     : ENABLED (Fields 1-8)")
print("====================================")
print("SYSTEM READY. WAITING FOR DATA & COMMANDS...\n")

while True:
    time.sleep(1)