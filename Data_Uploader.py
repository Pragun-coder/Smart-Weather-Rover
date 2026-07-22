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
BAUD = 9600  # Make sure this matches your Arduino Serial.begin() rate

# ThingSpeak Settings
WRITE_KEY = "05NUNO16U85E3BWS"
UPLOAD_INTERVAL = 15  # Seconds between ThingSpeak uploads

# MQTT Settings
BROKER = "broker.emqx.io"
PORT = 1883
CMD_TOPIC = "pragun_rover_2026/cmd"
SENSOR_TOPIC = "pragun_rover_2026/sensors"

# Camera Config (Local Backup Server)
CAM_PORT = 5000
PHONE_CAM_URL = "http://192.168.1.50:8080/video"  # Update with local phone IP if using IP Webcam

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
    "lng": 0.0
}
lastUpload = 0

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
                    latest["temp"] = float(data[0])
                    latest["hum"] = float(data[1])
                    latest["rain"] = int(data[2])
                    latest["soil"] = int(data[3])
                    latest["lat"] = float(data[4])
                    latest["lng"] = float(data[5])

                    # 1. Publish Telemetry via MQTT to Dashboard
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
                            print(f"[THINGSPEAK] Upload status: {r.text}")
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
print(f"COM PORT       : {COM_PORT}")
print(f"MQTT BROKER    : {BROKER}")
print(f"COMMAND TOPIC  : {CMD_TOPIC}")
print(f"SENSOR TOPIC   : {SENSOR_TOPIC}")
print(f"ThingSpeak     : ENABLED (Interval: {UPLOAD_INTERVAL}s)")
print(f"LOCAL CAM URL  : http://localhost:{CAM_PORT}/video")
print("====================================")
print("SYSTEM READY. WAITING FOR DATA & COMMANDS...\n")

while True:
    time.sleep(1)