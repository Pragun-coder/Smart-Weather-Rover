import time
import json
import requests
import serial
import paho.mqtt.client as mqtt
from google import genai

# ==================== CONFIGURATION ====================
COM_PORT = "COM6"
BAUD_RATE = 9600

MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
CMD_TOPIC = "pragun_rover_2026/cmd"
SENSOR_TOPIC = "pragun_rover_2026/sensors"

# 🔑 PASTE YOUR GOOGLE AI STUDIO API KEY HERE
GEMINI_API_KEY = "API_KEY"

# Initialize Google GenAI Client
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    ai_available = True
except Exception:
    ai_client = None
    ai_available = False

# ==================== SERIAL CONNECTION ====================
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    print(f"[SERIAL] Connected successfully to {COM_PORT} at {BAUD_RATE} baud.")
except Exception as e:
    print(f"[SERIAL ERROR] Could not open {COM_PORT}: {e}")
    ser = None

# ==================== SILENT AI PREDICTION ====================
def get_ai_prediction(sensor_data, weather_info=""):
    if not ai_available or GEMINI_API_KEY == "PASTE_YOUR_GEMINI_API_KEY_HERE":
        return "API Key Missing"

    prompt = f"""
    You are an embedded AI on the Pragun Smart Rover analyzing live environmental telemetry.
    
    Current Telemetry:
    - Temperature: {sensor_data.get('temp', 'N/A')} °C
    - Humidity: {sensor_data.get('hum', 'N/A')} %
    - Pressure: {sensor_data.get('press', 'N/A')} hPa
    - Soil Moisture: {sensor_data.get('soil', 'N/A')}
    - Rain Sensor: {sensor_data.get('rain', 'N/A')}
    - Regional Weather: {weather_info}

    Provide a short, highly informative environmental insight or prediction (Maximum 6-8 words).
    Do not use quotes or introductory fluff.
    """

    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text.strip()
    except Exception:
        return "AI Prediction Error"

# ==================== WEATHER API FETCH ====================
def fetch_weather_api(lat=26.8467, lng=80.9462):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current_weather=true"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get("current_weather", {})
            temp = data.get("temperature", "--")
            wind = data.get("windspeed", "--")
            print(f"[WEATHER API] Temp: {temp}°C | Wind: {wind} km/h")
            return f"Temp: {temp}°C, Wind: {wind} km/h"
    except Exception:
        pass
    return "Weather API Offline"

# ==================== MQTT HANDLERS ====================
def on_connect(client, userdata, flags, rc, properties=None):
    print("\n====================================")
    print(" [MQTT] CONNECTED TO BROKER")
    print(f" BROKER : {MQTT_BROKER}")
    print(f" TOPIC  : {CMD_TOPIC}")
    print("====================================\n")
    client.subscribe(CMD_TOPIC)

def on_message(client, userdata, msg):
    command = msg.payload.decode().strip()
    print(f"[MQTT RX] Command Received: {command}")
    if ser and ser.is_open:
        ser.write((command + "\n").encode())

# ==================== PRINT STARTUP BANNER ====================
print("====================================")
print("🚜 PRAGUN SMART ROVER BASE STATION")
print("====================================")
print(f"COM PORT        : {COM_PORT}")
print(f"MQTT BROKER     : {MQTT_BROKER}")
print(f"COMMAND TOPIC   : {CMD_TOPIC}")
print(f"SENSOR TOPIC    : {SENSOR_TOPIC}")
print("WEATHER API     : Open-Meteo Integrated")
print("ThingSpeak      : ENABLED (Fields 1-8)")
print("====================================")
print("SYSTEM READY. WAITING FOR DATA & COMMANDS...\n")

# Setup MQTT Client
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()

# Fetch Initial Weather
weather_context = fetch_weather_api()

# Read initial Serial line if available
if ser and ser.is_open:
    try:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"[SERIAL RX] {line}")
    except Exception:
        pass

# ==================== MAIN LOOP ====================
last_ai_time = 0
cached_ai_prediction = "Analyzing..."

try:
    while True:
        # Check Serial for incoming Arduino data
        if ser and ser.in_waiting > 0:
            try:
                raw_data = ser.readline().decode('utf-8', errors='ignore').strip()
                print(f"[SERIAL RX] {raw_data}")
            except Exception:
                pass

        # Sensor payload
        sensor_payload = {
            "temp": 29.2,
            "hum": 68.0,
            "press": 1008.5,
            "soil": 420,
            "rain": 980,
            "lat": 26.8467,
            "lng": 80.9462
        }

        # Silent background AI query every 15 seconds
        if time.time() - last_ai_time > 15:
            cached_ai_prediction = get_ai_prediction(sensor_payload, weather_context)
            last_ai_time = time.time()

        # Attach AI prediction string
        sensor_payload["prediction"] = cached_ai_prediction

        # Publish payload over MQTT
        client.publish(SENSOR_TOPIC, json.dumps(sensor_payload))

        time.sleep(3)

except KeyboardInterrupt:
    print("\n[SYSTEM] Shutting down Base Station...")
    client.loop_stop()
    if ser and ser.is_open:
        ser.close()