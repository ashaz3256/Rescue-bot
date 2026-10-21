/*
  Rescue Scout - ESP32 car controller (reference sketch)

  Flysky receiver --iBus--> ESP32 --> steering servo + motor (ESC or H-bridge)
  Laptop --UDP 4210--> ESP32        ESP32 --UDP 4211--> laptop (telemetry)

  Contract (must match brain/car_link.py):
    Laptop -> ESP32 : "S,<steer>,<throttle>\n"          floats -1.0..1.0, ~20 Hz
    ESP32 -> laptop : "T,<steer>,<throttle>,<mode>\n"   mode = MANUAL | AUTO, 20 Hz
    Channel 5 switch: MANUAL (sticks) / AUTO (laptop). MANUAL always wins.
    AUTO watchdog: no packet for 300 ms -> throttle 0.

  If you already have working iBus + servo code, just merge the UDP, mode switch and watchdog parts.

  Libraries (Arduino Library Manager): IBusBM, ESP32Servo
*/
#include <WiFi.h>
#include <WiFiUdp.h>
#include <IBusBM.h>
#include <ESP32Servo.h>

// ---------- Wi-Fi: join the same network as the laptop (laptop needs internet for the AI) ----------
const char* WIFI_SSID = "YOUR_WIFI_OR_PHONE_HOTSPOT";
const char* WIFI_PASS = "YOUR_PASSWORD";
// After it connects, the Serial Monitor prints the car's IP. Put it in the laptop's .env as CAR_IP.

// ---------- pins (change to match your wiring) ----------
const int IBUS_RX_PIN  = 16;   // Flysky receiver iBus signal -> this pin (Serial2 RX)
const int IBUS_TX_PIN  = 17;   // unused, but Serial2 needs one
const int STEER_PIN    = 18;   // steering servo signal
const int MOTOR_PIN    = 19;   // ESC signal (or H-bridge PWM, see below)

// Uncomment if the motor is driven by an H-bridge (L298N / TB6612) instead of an ESC.
// #define MOTOR_HBRIDGE
const int MOTOR_DIR_A  = 25;   // H-bridge only
const int MOTOR_DIR_B  = 26;   // H-bridge only

// ---------- pulse ranges (microseconds) - tune on the bench ----------
const int STEER_LEFT_US   = 1150;
const int STEER_CENTER_US = 1500;
const int STEER_RIGHT_US  = 1850;
const int ESC_REVERSE_US  = 1300;  // keep reverse/forward gentle indoors
const int ESC_NEUTRAL_US  = 1500;
const int ESC_FORWARD_US  = 1700;

// ---------- iBus channels (0-based in IBusBM) ----------
const int CH_STEER    = 0;  // channel 1
const int CH_THROTTLE = 2;  // channel 3
const int CH_MODE     = 4;  // channel 5 (SWA): low = MANUAL, high = AUTO

const unsigned int CMD_PORT = 4210;
const unsigned int TELEMETRY_PORT = 4211;
const unsigned long WATCHDOG_MS = 300;
const unsigned long TELEMETRY_MS = 50;  // 20 Hz

IBusBM ibus;
Servo steerServo;
#ifndef MOTOR_HBRIDGE
Servo esc;
#endif
WiFiUDP udp;

float autoSteer = 0, autoThrottle = 0;
unsigned long lastCmdMs = 0, lastTelemetryMs = 0;
IPAddress laptopIp;
bool haveLaptop = false;

float ibusToUnit(int raw) {                // 1000..2000 -> -1..1
  if (raw < 900 || raw > 2100) return 0;   // no signal
  return constrain((raw - 1500) / 500.0f, -1.0f, 1.0f);
}

int unitToUs(float v, int lo, int mid, int hi) {
  v = constrain(v, -1.0f, 1.0f);
  return v >= 0 ? mid + (int)(v * (hi - mid)) : mid + (int)(v * (mid - lo));
}

void writeOutputs(float steer, float throttle) {
  steerServo.writeMicroseconds(unitToUs(steer, STEER_LEFT_US, STEER_CENTER_US, STEER_RIGHT_US));
#ifdef MOTOR_HBRIDGE
  digitalWrite(MOTOR_DIR_A, throttle > 0.02);
  digitalWrite(MOTOR_DIR_B, throttle < -0.02);
  analogWrite(MOTOR_PIN, (int)(fabs(throttle) * 255));
#else
  esc.writeMicroseconds(unitToUs(throttle, ESC_REVERSE_US, ESC_NEUTRAL_US, ESC_FORWARD_US));
#endif
}

void readUdp() {
  int len = udp.parsePacket();
  if (len <= 0) return;
  char buf[64];
  int n = udp.read(buf, sizeof(buf) - 1);
  if (n <= 0) return;
  buf[n] = 0;
  float s, t;
  if (sscanf(buf, "S,%f,%f", &s, &t) == 2) {
    autoSteer = constrain(s, -1.0f, 1.0f);
    autoThrottle = constrain(t, -1.0f, 1.0f);
    lastCmdMs = millis();
    laptopIp = udp.remoteIP();
    haveLaptop = true;
  }
}

void setup() {
  Serial.begin(115200);
  ibus.begin(Serial2, IBUSBM_NOTIMER, IBUS_RX_PIN, IBUS_TX_PIN);

  steerServo.setPeriodHertz(50);
  steerServo.attach(STEER_PIN, 1000, 2000);
#ifdef MOTOR_HBRIDGE
  pinMode(MOTOR_DIR_A, OUTPUT);
  pinMode(MOTOR_DIR_B, OUTPUT);
  pinMode(MOTOR_PIN, OUTPUT);
#else
  esc.setPeriodHertz(50);
  esc.attach(MOTOR_PIN, 1000, 2000);
#endif
  writeOutputs(0, 0);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to Wi-Fi");
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) { delay(250); Serial.print("."); }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\nCar IP (put this in .env as CAR_IP): ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWi-Fi failed - manual driving still works.");
  }
  udp.begin(CMD_PORT);
}

void loop() {
  ibus.loop();
  readUdp();

  bool autoMode = ibusToUnit(ibus.readChannel(CH_MODE)) > 0.5;
  float steer, throttle;

  if (autoMode) {
    steer = autoSteer;
    throttle = (millis() - lastCmdMs > WATCHDOG_MS) ? 0 : autoThrottle;  // watchdog
  } else {
    steer = ibusToUnit(ibus.readChannel(CH_STEER));
    throttle = ibusToUnit(ibus.readChannel(CH_THROTTLE));
  }
  writeOutputs(steer, throttle);

  // Telemetry always sends the STICK values, so manual driving can be recorded as training data.
  if (haveLaptop && millis() - lastTelemetryMs > TELEMETRY_MS) {
    lastTelemetryMs = millis();
    char out[64];
    snprintf(out, sizeof(out), "T,%.3f,%.3f,%s\n",
             ibusToUnit(ibus.readChannel(CH_STEER)), ibusToUnit(ibus.readChannel(CH_THROTTLE)),
             autoMode ? "AUTO" : "MANUAL");
    udp.beginPacket(laptopIp, TELEMETRY_PORT);
    udp.print(out);
    udp.endPacket();
  }
}
