#include <Wire.h>
#include <Servo.h>
#include <DHT.h>
#include <Adafruit_BMP085.h>
#include <ThreeWire.h>
#include <RtcDS1302.h>
#include <SoftwareSerial.h>
#include <TinyGPS++.h>

// ================= 1. PIN & SYSTEM CONFIGURATION =================
#define PCF8574_ADDR 0x27  // I2C Address for PCF8574
#define DHTPIN 2           // DHT11 Data Pin
#define DHTTYPE DHT11

// Temperature Threshold for Automatic Cooling Fan Trigger (°C)
const float FAN_TEMP_THRESHOLD = 32.0;

// Arduino Nano Digital Pins
const int SOIL_SERVO_PIN = 3;
const int GPS_RX_PIN = 4;  // Connects to GPS TX
const int GPS_TX_PIN = 5;  // Connects to GPS RX
const int LED_STATUS = 8;
const int LED_ALERT = 9;

const int RTC_RST_PIN = 10;  // DS1302 Reset Pin
const int RTC_DAT_PIN = 11;  // DS1302 Data Pin
const int RTC_CLK_PIN = 12;  // DS1302 Clock Pin

// Arduino Nano Analog Pins
const int RAIN_PIN = A0;
const int SOIL_PIN = A1;
const int MOTOR_BAT_PIN = A2;  // 25V Voltage Sensor #1 Signal (Motor Battery)
const int LOGIC_BAT_PIN = A3;  // 25V Voltage Sensor #2 Signal (Logic Battery)

// Servo Probe Angles
const int PROBE_STOW_ANGLE = 10;     // Stowed Position (Up)
const int PROBE_DEPLOY_ANGLE = 120;  // Deployed Position (Down / Sampling)
int currentSoilServoAngle = PROBE_STOW_ANGLE;

// Hardware Objects
SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);
TinyGPSPlus gps;
ThreeWire rtcWire(RTC_DAT_PIN, RTC_CLK_PIN, RTC_RST_PIN);
RtcDS1302<ThreeWire> rtc(rtcWire);
DHT dht(DHTPIN, DHTTYPE);
Adafruit_BMP085 bmp;
Servo soilServo;

byte pcfState = 0x00;
bool bmpOnline = false;
bool rtcOnline = false;

// Complete Telemetry Structure
struct Telemetry {
  String timestamp = "2026-08-12 12:00:00";
  float temp = 0.0;
  float hum = 0.0;
  float pressure = 0.0;
  int rain = 0;
  int soil = 0;
  float motorVolts = 0.0;
  int motorPct = 0;
  float logicVolts = 0.0;
  int logicPct = 0;
  double latitude = 0.0;
  double longitude = 0.0;
  int satellites = 0;
  float speedKmh = 0.0;
  bool fanState = false;
  bool lightState = false;
} telemetry;

unsigned long lastTelemetryUpload = 0;
unsigned long lastHeartbeat = 0;

// ================= 2. MOTOR & EXPANDER CONTROL =================
void writePCF8574(byte data) {
  pcfState = data;
  Wire.beginTransmission(PCF8574_ADDR);
  Wire.write(pcfState);
  Wire.endTransmission();
}

void setMotors(char cmd) {
  // Preserve P5 (Headlights on Bit 5) AND P6 (Fan on Bit 6) while steering motors
  byte auxBits = pcfState & 0b01100000;

  switch (cmd) {
    case 'F': writePCF8574(0b00000101 | auxBits); break;  // Forward  (P0 + P2)
    case 'B': writePCF8574(0b00010010 | auxBits); break;  // Reverse  (P1 + P4)
    case 'L': writePCF8574(0b00000110 | auxBits); break;  // Left Turn (P1 + P2)
    case 'R': writePCF8574(0b00010001 | auxBits); break;  // Right Turn(P0 + P4)
    default: writePCF8574(0b00000000 | auxBits); break;   // Stop Motors
  }
}

void setHeadlight(bool turnOn) {
  if (turnOn) {
    pcfState |= 0b00100000;  // Set Pin P5 HIGH (Bit 5)
  } else {
    pcfState &= ~0b00100000;  // Set Pin P5 LOW
  }
  telemetry.lightState = turnOn;
  writePCF8574(pcfState);
}

void setCoolingFan(bool turnOn) {
  if (turnOn) {
    pcfState |= 0b01000000;  // Set Pin P6 HIGH (Bit 6)
  } else {
    pcfState &= ~0b01000000;  // Set Pin P6 LOW
  }
  telemetry.fanState = turnOn;
  writePCF8574(pcfState);
}

// ================= 3. RTC, VOLTAGE, & GPS PROCESSING =================
void updateTimestamp() {
  if (rtcOnline) {
    RtcDateTime now = rtc.GetDateTime();
    if (now.IsValid()) {
      char buf[20];
      snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d",
               now.Year(), now.Month(), now.Day(),
               now.Hour(), now.Minute(), now.Second());
      telemetry.timestamp = String(buf);
    }
  }
}

void calculateBattery25VSensor(int pin, float &volts, int &pct) {
  int raw = analogRead(pin);
  // 25V Module 5:1 divider math: V_in = (raw / 1023.0) * 25.0
  volts = (raw / 1023.0) * 25.0;

  // Percentage for 2S battery pack (6.0V empty to 8.4V full)
  pct = (int)(((volts - 6.0) / (8.4 - 6.0)) * 100.0);
  pct = constrain(pct, 0, 100);
}

void processGPS() {
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
  }

  if (gps.location.isUpdated()) {
    telemetry.latitude = gps.location.lat();
    telemetry.longitude = gps.location.lng();
    telemetry.satellites = gps.satellites.value();
    telemetry.speedKmh = gps.speed.kmph();
  }
}

// ================= 4. SERVO MOVEMENT (ATTACH/DETACH TO PREVENT BUZZ) =================
// Attaching the servo permanently keeps sending a PWM hold signal, which causes
// jitter/buzzing under load or vibration. We attach only while moving, then detach.
void moveServoTo(int angle) {
  soilServo.attach(SOIL_SERVO_PIN);
  soilServo.write(angle);
  delay(400);          // Give servo time to physically reach the target angle (tune if needed)
  soilServo.detach();  // Stop PWM signal -> no more idle buzz/jitter
}

// ================= 5. COMMAND PROCESSING & TELEMETRY OUTPUT =================
void processOTGCommand(char cmd) {
  digitalWrite(LED_STATUS, HIGH);
  switch (cmd) {
    case 'F': setMotors('F'); break;
    case 'B': setMotors('B'); break;
    case 'L': setMotors('L'); break;
    case 'R': setMotors('R'); break;
    case 'S': setMotors('S'); break;

    // Probe Servo Control (attach -> move -> detach, see moveServoTo above)
    case 'U':
      currentSoilServoAngle = PROBE_STOW_ANGLE;
      moveServoTo(currentSoilServoAngle);
      break;
    case 'D':
      currentSoilServoAngle = PROBE_DEPLOY_ANGLE;
      moveServoTo(currentSoilServoAngle);
      break;

    // Accessories
    case 'H': setHeadlight(true); break;
    case 'h': setHeadlight(false); break;
    case 'C': setCoolingFan(true); break;
    case 'c': setCoolingFan(false); break;
    default: break;
  }
  digitalWrite(LED_STATUS, LOW);
}

void sendSerialTelemetryCSV() {
  // CSV Format (11 fields for Python bridge compatibility):
  // temp, hum, rain, soil, lat, lng, press, motor_v, motor_pct, logic_v, logic_pct

  String csv = "";
  csv += String(telemetry.temp, 1) + ",";
  csv += String(telemetry.hum, 1) + ",";
  csv += String(telemetry.rain) + ",";
  csv += String(telemetry.soil) + ",";
  csv += String(telemetry.latitude, 6) + ",";
  csv += String(telemetry.longitude, 6) + ",";
  csv += String(telemetry.pressure, 1) + ",";
  csv += String(telemetry.motorVolts, 2) + ",";
  csv += String(telemetry.motorPct) + ",";
  csv += String(telemetry.logicVolts, 2) + ",";
  csv += String(telemetry.logicPct);

  Serial.println(csv);
}

void sendSerialTelemetryJSON() {
  // JSON Format (for USB debugging / laptop serial monitor)
  String json = "{";
  json += "\"time\":\"" + telemetry.timestamp + "\",";
  json += "\"temp\":" + String(telemetry.temp, 1) + ",";
  json += "\"hum\":" + String(telemetry.hum, 1) + ",";
  json += "\"press\":" + String(telemetry.pressure, 1) + ",";
  json += "\"rain\":" + String(telemetry.rain) + ",";
  json += "\"soil\":" + String(telemetry.soil) + ",";
  json += "\"motor_v\":" + String(telemetry.motorVolts, 2) + ",";
  json += "\"motor_pct\":" + String(telemetry.motorPct) + ",";
  json += "\"logic_v\":" + String(telemetry.logicVolts, 2) + ",";
  json += "\"logic_pct\":" + String(telemetry.logicPct) + ",";
  json += "\"lat\":" + String(telemetry.latitude, 6) + ",";
  json += "\"lng\":" + String(telemetry.longitude, 6) + ",";
  json += "\"sats\":" + String(telemetry.satellites) + ",";
  json += "\"fan\":" + String(telemetry.fanState ? "true" : "false") + ",";
  json += "\"light\":" + String(telemetry.lightState ? "true" : "false");
  json += "}";

  Serial.println(json);
}

// ================= 6. SETUP & MAIN LOOP =================
void setup() {
  Serial.begin(9600);     // Hardware Serial for USB OTG to Android
  gpsSerial.begin(9600);  // SoftwareSerial for GPS module
  Wire.begin();
  dht.begin();

  // Pin Configuration
  pinMode(LED_STATUS, OUTPUT);
  pinMode(LED_ALERT, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);

  // Servo Setup — move to stowed position once, then detach to prevent idle buzz
  moveServoTo(currentSoilServoAngle);

  // Clear PCF8574 (All outputs LOW)
  writePCF8574(0x00);

  // Initialize DS1302 RTC
  rtc.Begin();
  RtcDateTime compiled = RtcDateTime(__DATE__, __TIME__);
  if (!rtc.IsDateTimeValid()) {
    rtc.SetDateTime(compiled);
  }
  if (rtc.GetIsWriteProtected()) rtc.SetIsWriteProtected(false);
  if (!rtc.GetIsRunning()) rtc.SetIsRunning(true);

  RtcDateTime now = rtc.GetDateTime();
  if (now < compiled) rtc.SetDateTime(compiled);
  rtcOnline = true;

  // Initialize BMP180 Pressure Sensor
  if (bmp.begin()) {
    bmpOnline = true;
  }
}

void loop() {
  // 1. Check for incoming USB OTG commands from Android Phone
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd != '\n' && cmd != '\r') {  // Ignore the newline that follows every command
      processOTGCommand(cmd);
    }
  }

  // 2. Process GPS Stream
  processGPS();

  // 3. Heartbeat LED Pulse (D13)
  if (millis() - lastHeartbeat > 1000) {
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    lastHeartbeat = millis();
  }

  // 4. Read Sensors & Batteries
  updateTimestamp();

  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (!isnan(t)) telemetry.temp = t;
  if (!isnan(h)) telemetry.hum = h;

  if (bmpOnline) {
    telemetry.pressure = bmp.readPressure() / 100.0F;  // Pa to hPa
  }

  telemetry.rain = analogRead(RAIN_PIN);
  telemetry.soil = analogRead(SOIL_PIN);

  calculateBattery25VSensor(MOTOR_BAT_PIN, telemetry.motorVolts, telemetry.motorPct);
  calculateBattery25VSensor(LOGIC_BAT_PIN, telemetry.logicVolts, telemetry.logicPct);

  // 5. Automatic Temperature Thermal Management (Cooling Fan Trigger)
  if (telemetry.temp >= FAN_TEMP_THRESHOLD && !telemetry.fanState) {
    setCoolingFan(true);
  } else if (telemetry.temp < (FAN_TEMP_THRESHOLD - 2.0) && telemetry.fanState) {
    setCoolingFan(false);
  }

  // 6. Broadcast Telemetry over USB OTG Serial every 2 seconds
  // Format depends on connection context:
  // - Phone (Termux): CSV format for Python bridge
  // - Laptop (Serial Monitor): JSON format for human readability
  if (millis() - lastTelemetryUpload >= 2000) {
    // Send BOTH CSV and JSON - Python ignores JSON, serial monitor shows JSON
    sendSerialTelemetryCSV();  // For Termux Python bridge
    delay(10);
    sendSerialTelemetryJSON();  // For USB serial monitor debugging
    lastTelemetryUpload = millis();
  }

  delay(20);
}
