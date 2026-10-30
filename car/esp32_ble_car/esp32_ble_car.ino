#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <string>

// ==========================================
// GPIO PINS
// ==========================================

#define STEER_PIN 4
#define PITCH_PIN 5
#define YAW_PIN   6
#define ESC_PIN   7

// Independent PWM channels
#define STEER_CH 0
#define PITCH_CH 1
#define YAW_CH   2
#define ESC_CH   3

#define PWM_FREQ 50
#define PWM_BITS 14

// ==========================================
// SERVO TRIMMING
// ==========================================
// Adjust these values to correct centre.

const int STEER_TRIM = 1150;
const int PITCH_TRIM = 1700;
const int YAW_TRIM   = 1600;

// ==========================================
// SERVO RANGE
// ==========================================
// Wider travel. Check mechanical clearance.

const int STEER_RANGE = 550;   // full lock each way; lower it if the servo buzzes at the ends
const int CAMERA_RANGE = 600;

const int YAW_RANGE = 900;     // camera pan: about ±80–90°
const float YAW_SPEED = 18.0;  // pan twice as fast as tilt

// Target movement per 20ms
const float STEER_SPEED = 20.0;  // reaches full lock in ~0.55 s
const float CAMERA_SPEED = 9.0;

// Smooth movement filter
const float SMOOTHING = 0.18;

// ==========================================
// ESC SETTINGS
// ==========================================

const int ESC_NEUTRAL = 1500;

// Forward values confirmed or interpolated
const int FORWARD_LOW = 1250;
const int FORWARD_MED = 1200;
const int FORWARD_HIGH = 1150;

// Reverse confirmed
const int REVERSE_SPEED = 1650;

// Direction change requires a neutral period
const unsigned long GEAR_DELAY = 700;

// Bluetooth packet timeout
const unsigned long FAILSAFE_MS = 350;

// ==========================================
// BLE SETTINGS
// ==========================================

#define SERVICE_UUID \
"6E400001-B5A3-F393-E0A9-E50E24DCCA9E"

#define RX_UUID \
"6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

// Movement bits
#define KEY_W     1
#define KEY_S     2
#define KEY_A     4
#define KEY_D     8
#define KEY_UP    16
#define KEY_DOWN  32
#define KEY_LEFT  64
#define KEY_RIGHT 128

// Second byte command flags
#define CMD_CAMERA_CENTER  1
#define CMD_STEER_CENTER   2
#define CMD_ESTOP          4
#define CMD_RESET_ESTOP    8


// Rear ultrasonic sensor (HC-SR04). Without a sensor fitted it reads 999 = clear.
#define TRIG_PIN 15
#define ECHO_PIN 16
const int REAR_STOP_CM = 20;
int rearCm = 999;
unsigned long lastPing = 0;

// ==========================================
// SHARED BLUETOOTH STATE
// ==========================================

volatile bool connected = false;
volatile uint8_t keyState = 0;
volatile uint8_t commandFlags = 0;
volatile uint8_t speedLevel = 1;
volatile unsigned long lastPacket = 0;

portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

BLEServer* bleServer;

// ==========================================
// SERVO STATE
// ==========================================

float steerTarget = STEER_TRIM;
float pitchTarget = PITCH_TRIM;
float yawTarget = YAW_TRIM;

float steerCurrent = STEER_TRIM;
float pitchCurrent = PITCH_TRIM;
float yawCurrent = YAW_TRIM;

// ==========================================
// MOTOR STATE
// ==========================================

enum MotorDirection {
  MOTOR_STOP,
  MOTOR_FORWARD,
  MOTOR_REVERSE
};

MotorDirection lastDirection = MOTOR_STOP;

bool emergencyStop = true;
bool gearWaiting = false;
bool requireFreshPress = true;

unsigned long gearStart = 0;
unsigned long lastServoUpdate = 0;

// ==========================================
// PWM OUTPUT
// ==========================================

void writePWM(int channel, int us) {
  if (channel == STEER_CH) {
    us = constrain(us, 500, 2000);   // steering: allow full lock both ways
  } else if (channel == YAW_CH) {
    us = constrain(us, 500, 2500);   // camera pan: allow a wider turn
  } else {
    us = constrain(us, 900, 2100);   // motor and camera tilt: unchanged
  }

  uint32_t duty =
    (uint32_t)((uint64_t)us * 16384 / 20000);

  ledcWrite(channel, duty);
}

void stopMotor() {
  writePWM(ESC_CH, ESC_NEUTRAL);
}

// ==========================================
// BLE CALLBACKS
// ==========================================

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* server) override {
    portENTER_CRITICAL(&mux);
    connected = true;
    keyState = 0;
    commandFlags = 0;
    lastPacket = millis();
    portEXIT_CRITICAL(&mux);

    Serial.println("Bluetooth connected");
  }

  void onDisconnect(BLEServer* server) override {
    portENTER_CRITICAL(&mux);
    connected = false;
    keyState = 0;
    commandFlags = 0;
    portEXIT_CRITICAL(&mux);

    Serial.println("Bluetooth disconnected");
  }
};

class RXCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* characteristic) override {
    std::string data = characteristic->getValue();

    if (data.size() < 3) return;

    portENTER_CRITICAL(&mux);

    keyState = (uint8_t)data[0];
    commandFlags |= (uint8_t)data[1];

    uint8_t requestedSpeed = (uint8_t)data[2];
    if (requestedSpeed >= 1 && requestedSpeed <= 3) {
      speedLevel = requestedSpeed;
    }

    lastPacket = millis();

    portEXIT_CRITICAL(&mux);
  }
};

// ==========================================
// SETUP
// ==========================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  ledcSetup(STEER_CH, PWM_FREQ, PWM_BITS);
  ledcSetup(PITCH_CH, PWM_FREQ, PWM_BITS);
  ledcSetup(YAW_CH, PWM_FREQ, PWM_BITS);
  ledcSetup(ESC_CH, PWM_FREQ, PWM_BITS);

  ledcAttachPin(STEER_PIN, STEER_CH);
  ledcAttachPin(PITCH_PIN, PITCH_CH);
  ledcAttachPin(YAW_PIN, YAW_CH);
  ledcAttachPin(ESC_PIN, ESC_CH);

  writePWM(STEER_CH, STEER_TRIM);
  writePWM(PITCH_CH, PITCH_TRIM);
  writePWM(YAW_CH, YAW_TRIM);

  stopMotor();

  // Allow ESC to arm at neutral
  delay(5000);

  BLEDevice::init("ESP32_RC_CAR");

  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new ServerCallbacks());

  BLEService* service =
    bleServer->createService(SERVICE_UUID);

  BLECharacteristic* rx =
    service->createCharacteristic(
      RX_UUID,
      BLECharacteristic::PROPERTY_WRITE |
      BLECharacteristic::PROPERTY_WRITE_NR
    );

  rx->setCallbacks(new RXCallbacks());

  service->start();

  BLEAdvertising* advertising =
    BLEDevice::getAdvertising();

  advertising->addServiceUUID(SERVICE_UUID);
  advertising->start();

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);


  Serial.println("ESP32 RC CAR READY");
}

// ==========================================
// MAIN LOOP
// ==========================================

void loop() {
  static bool wasConnected = false;

  bool isConnected;
  uint8_t keys;
  uint8_t commands;
  uint8_t speed;
  unsigned long packetTime;

  portENTER_CRITICAL(&mux);

  isConnected = connected;
  keys = keyState;
  commands = commandFlags;
  commandFlags = 0;
  speed = speedLevel;
  packetTime = lastPacket;

  portEXIT_CRITICAL(&mux);

  unsigned long now = millis();

  bool timedOut =
    (now - packetTime > FAILSAFE_MS);

  if (!isConnected || timedOut) {
    keys = 0;
    emergencyStop = true;
    requireFreshPress = true;
    gearWaiting = false;
    lastDirection = MOTOR_STOP;
  }

  if (!isConnected) {
    if (wasConnected) {
      bleServer->startAdvertising();
      wasConnected = false;
    }
  } else {
    wasConnected = true;
  }

  // Rear ultrasonic: measure every 60 ms
  if (now - lastPing >= 60) {
    lastPing = now;
    digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    long us = pulseIn(ECHO_PIN, HIGH, 6000);   // give up after ~1 m
    rearCm = (us == 0) ? 999 : us / 58;
  }

  // ========================================
  // EMERGENCY STOP
  // ========================================

  if (commands & CMD_ESTOP) {
    emergencyStop = true;
    requireFreshPress = true;
    gearWaiting = false;
    lastDirection = MOTOR_STOP;
  }

  if (commands & CMD_RESET_ESTOP) {
    if (!(keys & (KEY_W | KEY_S))) {
      emergencyStop = false;
      requireFreshPress = true;
    }
  }

  // ========================================
  // MOTOR CONTROL
  // ========================================

  MotorDirection requested = MOTOR_STOP;

  if ((keys & KEY_W) && !(keys & KEY_S)) {
    requested = MOTOR_FORWARD;
  }
  else if ((keys & KEY_S) && !(keys & KEY_W)) {
    requested = MOTOR_REVERSE;
  }

  if (requested == MOTOR_STOP) {
    requireFreshPress = false;
  }

  int motorPulse = ESC_NEUTRAL;

  if (!emergencyStop && !requireFreshPress) {

    if (requested == MOTOR_STOP) {
      gearWaiting = false;
      // Keep lastDirection to detect a reversal
    }
    else if (lastDirection != MOTOR_STOP &&
             requested != lastDirection) {

      // Opposite direction requested:
      // brake and require release before engaging.
      gearWaiting = true;
      gearStart = now;
      lastDirection = MOTOR_STOP;
      requireFreshPress = true;
    }
    else if (gearWaiting) {
      motorPulse = ESC_NEUTRAL;
    }
    else {
      if (requested == MOTOR_FORWARD) {
        if (speed == 1)
          motorPulse = FORWARD_LOW;
        else if (speed == 2)
          motorPulse = FORWARD_MED;
        else
          motorPulse = FORWARD_HIGH;
      }
      else if (requested == MOTOR_REVERSE) {
        motorPulse = REVERSE_SPEED;
      }

      lastDirection = requested;
    }
  }

  // Neutral interval after gear change
  if (gearWaiting) {
    motorPulse = ESC_NEUTRAL;

    if (now - gearStart >= GEAR_DELAY &&
        requested == MOTOR_STOP) {
      gearWaiting = false;
    }
  }

  if (emergencyStop || timedOut || !isConnected) {
    motorPulse = ESC_NEUTRAL;
  }

  // Reflex: never reverse into something close behind
  if (requested == MOTOR_REVERSE && rearCm < REAR_STOP_CM) {
    motorPulse = ESC_NEUTRAL;
  }

  // ========================================
  // CENTRE CONTROLS
  // ========================================

  if (commands & CMD_STEER_CENTER) {
    steerTarget = STEER_TRIM;
  }

  if (commands & CMD_CAMERA_CENTER) {
    pitchTarget = PITCH_TRIM;
    yawTarget = YAW_TRIM;
  }

  // ========================================
  // SMOOTH SERVO CONTROL
  // ========================================

  if (now - lastServoUpdate >= 20) {
    lastServoUpdate = now;

    if ((keys & KEY_A) && !(keys & KEY_D))
      steerTarget -= STEER_SPEED;

    if ((keys & KEY_D) && !(keys & KEY_A))
      steerTarget += STEER_SPEED;

    // Pitch - corrected direction
    if ((keys & KEY_UP) && !(keys & KEY_DOWN))
      pitchTarget -= CAMERA_SPEED;

    if ((keys & KEY_DOWN) && !(keys & KEY_UP))
      pitchTarget += CAMERA_SPEED;

    // Yaw - corrected direction
    if ((keys & KEY_LEFT) && !(keys & KEY_RIGHT))
      yawTarget += YAW_SPEED;

    if ((keys & KEY_RIGHT) && !(keys & KEY_LEFT))
      yawTarget -= YAW_SPEED;

    steerTarget = constrain(
      steerTarget,
      STEER_TRIM - STEER_RANGE,
      STEER_TRIM + STEER_RANGE
    );

    pitchTarget = constrain(
      pitchTarget,
      PITCH_TRIM - CAMERA_RANGE,
      PITCH_TRIM + CAMERA_RANGE
    );

    yawTarget = constrain(
      yawTarget,
      YAW_TRIM - YAW_RANGE,
      YAW_TRIM + YAW_RANGE
    );

    steerCurrent +=
      (steerTarget - steerCurrent) * SMOOTHING;

    pitchCurrent +=
      (pitchTarget - pitchCurrent) * SMOOTHING;

    yawCurrent +=
      (yawTarget - yawCurrent) * SMOOTHING;

    writePWM(STEER_CH, round(steerCurrent));
    writePWM(PITCH_CH, round(pitchCurrent));
    writePWM(YAW_CH, round(yawCurrent));
  }

  delay(5);
}
