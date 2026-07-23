#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <DS1302.h>
#include <SoftwareSerial.h>
#include <TinyGPS++.h>
#include <Servo.h>
#include <SPI.h>
#include <nRF24L01.h>
#include <RF24.h>
#include <Adafruit_BMP085.h> // Official library for BMP180 & BMP085

// ================= RF =================
RF24 radio(3, 10);
const byte address[6] = "00001";
char receivedText[32];

struct SensorData {
  float temp;
  float hum;
  int rain;
  int soil;
  float lat;
  float lng;
  float pressure;
  int battery;
};

SensorData data;

// ================= MOTOR =================
#define IN1 4
#define IN2 A0
#define IN3 A1
#define IN4 A2

// ================= LCD =================
LiquidCrystal_I2C lcd(0x27, 16, 2);

// ================= DHT =================
#define DHTPIN 2
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

// ================= BMP180 (I2C) =================
Adafruit_BMP085 bmp; // Uses A4 (SDA) and A5 (SCL)

// ================= RTC =================
DS1302 rtc(8, 7, 6);

// ================= GPS =================
// Pin 5 = RX (Connect to GPS TX). Pin -1 disables TX to free up Pin 9!
SoftwareSerial gpsSerial(5, -1);
TinyGPSPlus gps;

// ================= SERVO =================
Servo soilServo;
bool servoAttached = false;
#define SERVO_PIN 9 // Servo on D9

// ================= SENSORS =================
int rainPin = A6;
int soilPin = A7;
int voltagePin = A3; // Voltage Sensor Module on A3

// ================= TIMERS =================
unsigned long lastLCD = 0;
unsigned long lastRadio = 0;
unsigned long lastServo = 0;
unsigned long lastSerial = 0;

void attachServoIfNeeded() {
  if (!servoAttached) {
    soilServo.attach(SERVO_PIN);
    servoAttached = true;
  }
}

void detachServoIfNeeded() {
  if (servoAttached) {
    soilServo.detach();
    servoAttached = false;
  }
}

void setup() {
  Serial.begin(9600);

  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);

  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);

  attachServoIfNeeded();
  soilServo.write(90);
  delay(700);
  detachServoIfNeeded();

  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("BOOT OK");

  dht.begin();

  // Initialize BMP180 Sensor
  if (!bmp.begin()) {
    // Falls back gracefully if BMP180 isn't connected properly
    Serial.println(F("[WARNING] Could not find BMP180 sensor!"));
  }

  rtc.halt(false);
  rtc.writeProtect(false);

  gpsSerial.begin(9600);

  radio.begin();
  radio.openWritingPipe(address);
  radio.openReadingPipe(1, address);
  radio.setPALevel(RF24_PA_LOW);
  radio.setDataRate(RF24_250KBPS);
  radio.startListening();

  delay(1500);
  lcd.clear();
}

void loop() {
  // ================= RECEIVE COMMAND (RF OR SERIAL) =================
  String cmd = "";

  if (radio.available()) {
    memset(receivedText, 0, sizeof(receivedText));
    radio.read(&receivedText, sizeof(receivedText));
    cmd = String(receivedText);
    cmd.trim();
  } else if (Serial.available() > 0) {
    cmd = Serial.readStringUntil('\n');
    cmd.trim();
  }

  if (cmd.length() > 0) {
    if (cmd == "FORWARD") {
      digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
      digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
    } else if (cmd == "BACKWARD") {
      digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);
      digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH);
    } else if (cmd == "LEFT") {
      digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);
      digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
    } else if (cmd == "RIGHT") {
      digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
      digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH);
    } else if (cmd == "STOP") {
      digitalWrite(IN1, LOW); digitalWrite(IN2, LOW);
      digitalWrite(IN3, LOW); digitalWrite(IN4, LOW);
    } else if (cmd == "LOWER") {
      attachServoIfNeeded();
      soilServo.write(0);
      lastServo = millis();
    } else if (cmd == "RAISE") {
      attachServoIfNeeded();
      soilServo.write(90);
      lastServo = millis();
    }
  }

  // ================= DETACH SERVO =================
  if (servoAttached && (millis() - lastServo > 1000)) {
    detachServoIfNeeded();
  }

  // ================= GPS =================
  while (gpsSerial.available()) {
    gps.encode(gpsSerial.read());
  }

  // ================= SENSOR READINGS =================
  int rainValue = analogRead(rainPin);
  int soilValue = analogRead(soilPin);

  float temp = dht.readTemperature();
  float hum = dht.readHumidity();
  if (isnan(temp)) temp = 0;
  if (isnan(hum)) hum = 0;

  // BMP180 Pressure reading in hPa / mbar
  float pressure = bmp.readPressure() / 100.0F; 
  if (pressure <= 0 || isnan(pressure)) {
    pressure = 1013.25; // Standard sea-level pressure fallback
  }

  // Battery Percentage calculation (Voltage divider 5:1 on A3)
  int batRaw = analogRead(voltagePin);
  float batVoltage = (batRaw * 5.0 / 1023.0) * 5.0; // Scaled for 5:1 divider
  int batPct = map(constrain(batVoltage * 100, 600, 840), 600, 840, 0, 100); // 6.0V = 0%, 8.4V = 100%

  float lat = 0, lng = 0;
  if (gps.location.isValid()) {
    lat = gps.location.lat();
    lng = gps.location.lng();
  }

  Time t = rtc.time();

  // ================= LCD DISPLAY =================
  if (millis() - lastLCD > 1000) {
    lastLCD = millis();

    lcd.setCursor(0, 0); lcd.print("                ");
    lcd.setCursor(0, 1); lcd.print("                ");

    if (rainValue > 500) {
      lcd.setCursor(0, 0); lcd.print("RAIN DETECTED");
      lcd.setCursor(0, 1); lcd.print("Soil:");
      lcd.print(map(soilValue, 1023, 0, 0, 100)); lcd.print("%");
    } else {
      lcd.setCursor(0, 0);
      lcd.print("P:"); lcd.print((int)pressure);
      lcd.print(" B:"); lcd.print(batPct); lcd.print("%");

      lcd.setCursor(0, 1);
      if (t.hr < 10) lcd.print("0");
      lcd.print(t.hr); lcd.print(":");
      if (t.min < 10) lcd.print("0");
      lcd.print(t.min);
      lcd.print(" S:"); lcd.print(map(soilValue, 1023, 0, 0, 100));
    }
  }

  // ================= SEND RADIO TELEMETRY =================
  if (millis() - lastRadio > 1000) {
    lastRadio = millis();

    data.temp = temp;
    data.hum = hum;
    data.rain = rainValue;
    data.soil = soilValue;
    data.lat = lat;
    data.lng = lng;
    data.pressure = pressure;
    data.battery = batPct;

    radio.stopListening();
    radio.write(&data, sizeof(data));
    radio.startListening();
  }

  // ================= SERIAL CSV TO PYTHON BASE STATION =================
  if (millis() - lastSerial > 1000) {
    lastSerial = millis();

    // CSV Output Format: temp,hum,rain,soil,lat,lng,pressure,battery
    Serial.print(temp, 1); Serial.print(",");
    Serial.print(hum, 1); Serial.print(",");
    Serial.print(rainValue); Serial.print(",");
    Serial.print(soilValue); Serial.print(",");
    Serial.print(lat, 6); Serial.print(",");
    Serial.print(lng, 6); Serial.print(",");
    Serial.print(pressure, 1); Serial.print(",");
    Serial.println(batPct);
  }
}