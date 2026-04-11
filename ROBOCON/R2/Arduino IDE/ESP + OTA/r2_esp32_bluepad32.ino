// ================================================================
//  R2 NORMAL WHEEL CAR  —  ESP32 + Bluepad32 Edition  v1.0
//  Hardware  : DOIT ESP32 DEVKIT V1 + Rhino MDD20Amp ×2 + 4 DC Motors
//  Interface : PS4 controller via Bluetooth (Bluepad32 library)
//
//  Controls (left joystick only, 4-directional, no diagonal mixing):
//    Left  Stick ↑ → Forward    (all 4 wheels forward)
//    Left  Stick ↓ → Backward   (all 4 wheels reverse)
//    Left  Stick → → Rotate CW  (left wheels fwd, right wheels rev)
//    Left  Stick ← → Rotate CCW (left wheels rev, right wheels fwd)
//
//  Features:
//    • Direct Bluetooth connection — no Python script needed
//    • Smooth ramp-up / ramp-down
//    • Detailed serial monitor output
//    • Safety timeout: motors stop if controller disconnects
//    • Motor invert flags for mounting correction
//    • 5 ms loop (200 Hz) for low latency
// ================================================================

#include <Bluepad32.h>

// ================================================================
//  WIRING  —  ESP32 GPIO →  Rhino MDD20Amp  (DIR + PWM per channel)
//
//  LEFT  MDD20Amp
//    CH1  DIR=16  PWM=17   →  Left  Front  (LF)
//    CH2  DIR=18  PWM=19   →  Left  Back   (LB)
//
//  RIGHT MDD20Amp
//    CH1  DIR=22  PWM=23   →  Right Front  (RF)
//    CH2  DIR=25  PWM=26   →  Right Back   (RB)
//
//  All pins chosen to:
//    ✓ Support digital OUTPUT (DIR)
//    ✓ Support LEDC PWM       (PWM)
//    ✗ Avoid flash pins (6-11), input-only pins (34-39),
//      boot-critical pins (0, 12), serial pins (1, 3)
//
//  DIR HIGH  =  forward spin
//  DIR LOW   =  reverse spin
// ================================================================

// ================================================================
//  PIN DEFINITIONS
// ================================================================
#define LF_DIR 16
#define LF_PWM 17

#define LB_DIR 18
#define LB_PWM 19

#define RF_DIR 22
#define RF_PWM 23

#define RB_DIR 25
#define RB_PWM 26

// ================================================================
//  MOTOR INVERT FLAGS
//  Set to 1 if a motor spins the wrong way for its position on
//  the chassis (e.g. mounted mirrored / gearbox on opposite side).
//  This is a SOFTWARE fix — no rewiring needed.
// ================================================================
#define LF_INVERT 0
#define LB_INVERT 0
#define RF_INVERT 0
#define RB_INVERT 0

// ================================================================
//  TUNING
// ================================================================
#define MAX_SPEED                                                              \
  70 // PWM duty 0–255
      //   bench test   →  60
      //   first floor  →  100
      //   normal use   →  180
      //   full speed   →  255

#define DEADZONE                                                               \
  10/ Bluepad32 axes are -511…+512, so deadzone ~40
     // (higher than the Mega version because the range is larger)

#define RAMP_UP_STEP 14   // acceleration step per 5 ms tick
#define RAMP_DOWN_STEP 16 // deceleration step per 5 ms tick

#define LOOP_MS 5        // 200 Hz loop
#define CTRL_TIMEOUT 500 // ms — stop motors if controller data stops

// ================================================================
//  LEDC PWM CONFIGURATION
//  ESP32 does not have native analogWrite(). We use LEDC channels.
// ================================================================
#define PWM_FREQ 5000    // 5 kHz — good for DC motors
#define PWM_RESOLUTION 8 // 8-bit → 0–255 duty range

// LEDC channels (0–15 available on ESP32)
#define LEDC_CH_LF 0
#define LEDC_CH_LB 1
#define LEDC_CH_RF 2
#define LEDC_CH_RB 3

// ================================================================
//  RAMP STATE
// ================================================================
int targetLF = 0, targetLB = 0, targetRF = 0, targetRB = 0;
int currentLF = 0, currentLB = 0, currentRF = 0, currentRB = 0;

unsigned long lastInputTime = 0;
bool controllerConnected = false;

// ================================================================
//  BLUEPAD32 — Controller storage
// ================================================================
ControllerPtr myControllers[BP32_MAX_GAMEPADS];

// ================================================================
//  BLUEPAD32 CALLBACKS
// ================================================================
void onConnectedController(ControllerPtr ctl) {
  bool foundEmptySlot = false;
  for (int i = 0; i < BP32_MAX_GAMEPADS; i++) {
    if (myControllers[i] == nullptr) {
      Serial.printf("[BP32] Controller connected, index=%d\n", i);
      ControllerProperties properties = ctl->getProperties();
      Serial.printf("[BP32] Model: %s, VID=0x%04x, PID=0x%04x\n",
                    ctl->getModelName().c_str(), properties.vendor_id,
                    properties.product_id);
      myControllers[i] = ctl;
      foundEmptySlot = true;
      controllerConnected = true;
      lastInputTime = millis();
      break;
    }
  }
  if (!foundEmptySlot) {
    Serial.println("[BP32] Controller connected, but no empty slot!");
  }
}

void onDisconnectedController(ControllerPtr ctl) {
  for (int i = 0; i < BP32_MAX_GAMEPADS; i++) {
    if (myControllers[i] == ctl) {
      Serial.printf("[BP32] Controller disconnected from index=%d\n", i);
      myControllers[i] = nullptr;
      break;
    }
  }
  // Check if any controller is still connected
  controllerConnected = false;
  for (int i = 0; i < BP32_MAX_GAMEPADS; i++) {
    if (myControllers[i] != nullptr) {
      controllerConnected = true;
      break;
    }
  }
  if (!controllerConnected) {
    Serial.println("[BP32] All controllers disconnected — stopping motors");
  }
}

// ================================================================
//  applyInvert()
// ================================================================
int applyInvert(int speed, int invertFlag) {
  return invertFlag ? -speed : speed;
}

// ================================================================
//  setMotor()
//  Drives one motor channel on the Rhino MDD20Amp via LEDC PWM.
//
//  speed:  +1 … +255  → DIR HIGH, PWM = speed   (forward)
//          -1 … -255  → DIR LOW,  PWM = |speed|  (reverse)
//          0          → DIR LOW,  PWM = 0         (stop / coast)
// ================================================================
void setMotor(uint8_t dirPin, uint8_t ledcChannel, int speed) {
  speed = constrain(speed, -255, 255);

  if (speed > 0) {
    digitalWrite(dirPin, HIGH);
    ledcWrite(ledcChannel, speed);
  } else if (speed < 0) {
    digitalWrite(dirPin, LOW);
    ledcWrite(ledcChannel, -speed);
  } else {
    digitalWrite(dirPin, LOW);
    ledcWrite(ledcChannel, 0);
  }
}

// ================================================================
//  stopAll()  —  immediate hard stop, resets ramp state
// ================================================================
void stopAll() {
  setMotor(LF_DIR, LEDC_CH_LF, 0);
  setMotor(LB_DIR, LEDC_CH_LB, 0);
  setMotor(RF_DIR, LEDC_CH_RF, 0);
  setMotor(RB_DIR, LEDC_CH_RB, 0);
  targetLF = targetLB = targetRF = targetRB = 0;
  currentLF = currentLB = currentRF = currentRB = 0;
}

// ================================================================
//  rampStep()
//  Moves 'current' one step toward 'target'.
// ================================================================
int rampStep(int current, int target) {
  if (current == target)
    return current;

  // Determine if accelerating (away from 0) or decelerating (toward 0)
  bool speedingUp;
  if (target > 0 && current >= 0) {
    speedingUp = (target > current);
  } else if (target < 0 && current <= 0) {
    speedingUp = (target < current);
  } else {
    // Crossing zero
    speedingUp = false;
  }

  int step = speedingUp ? RAMP_UP_STEP : RAMP_DOWN_STEP;

  if (target > current) {
    current += step;
    if (current > target)
      current = target;
  } else {
    current -= step;
    if (current < target)
      current = target;
  }

  return current;
}

// ================================================================
//  applyRamp()
//  Called EVERY loop tick (5 ms).
// ================================================================
void applyRamp() {
  currentLF = rampStep(currentLF, targetLF);
  currentLB = rampStep(currentLB, targetLB);
  currentRF = rampStep(currentRF, targetRF);
  currentRB = rampStep(currentRB, targetRB);

  setMotor(LF_DIR, LEDC_CH_LF, applyInvert(currentLF, LF_INVERT));
  setMotor(LB_DIR, LEDC_CH_LB, applyInvert(currentLB, LB_INVERT));
  setMotor(RF_DIR, LEDC_CH_RF, applyInvert(currentRF, RF_INVERT));
  setMotor(RB_DIR, LEDC_CH_RB, applyInvert(currentRB, RB_INVERT));
}

// ================================================================
//  dirChar()  —  returns 'F', 'R', or 'S'
// ================================================================
char dirChar(int speed) {
  if (speed > 0)
    return 'F';
  if (speed < 0)
    return 'R';
  return 'S';
}

// ================================================================
//  printBar()  —  ASCII speed bar  e.g.  [####      ] +80
// ================================================================
void printBar(int speed, int maxSpeed, int width) {
  int filled = (int)((float)abs(speed) / maxSpeed * width + 0.5f);
  filled = constrain(filled, 0, width);

  Serial.print('[');
  for (int i = 0; i < width; i++) {
    Serial.print(i < filled ? '#' : ' ');
  }
  Serial.print(']');
  if (speed >= 0)
    Serial.print(' ');
  Serial.print(speed);
}

// ================================================================
//  mapAxis()
//  Bluepad32 joystick axes are -511…+512.
//  Map to -255…+255 for our motor control.
// ================================================================
int mapAxis(int raw) {
  return constrain(map(raw, -511, 512, -255, 255), -255, 255);
}

// ================================================================
//  processMotion()
//  Takes left joystick values (already mapped to -255…+255),
//  sets targetXX for all 4 motors.
//
//  4-DIRECTIONAL CONTROL (no diagonal mixing):
//
//          FRONT
//    [LF] ──── [RF]
//     |            |
//    [LB] ──── [RB]
//          BACK
//
//  Dominant axis wins (|LY| vs |LX|):
//    FORWARD  : all 4 wheels forward   (speed = LY)
//    BACKWARD : all 4 wheels reverse   (speed = LY)
//    CW       : left fwd, right rev    (speed = |LX|)
//    CCW      : left rev, right fwd    (speed = |LX|)
// ================================================================
void processMotion(int joyX, int joyY) {

  // Deadzone
  if (abs(joyX) < DEADZONE)
    joyX = 0;
  if (abs(joyY) < DEADZONE)
    joyY = 0;

  // Cap to MAX_SPEED
  joyX = constrain(joyX, -MAX_SPEED, MAX_SPEED);
  joyY = constrain(joyY, -MAX_SPEED, MAX_SPEED);

  // 4-directional: dominant axis wins, no mixing
  int leftSpeed = 0;
  int rightSpeed = 0;
  const char *mode;

  if (joyX == 0 && joyY == 0) {
    mode = "STOP";
  } else if (abs(joyY) >= abs(joyX)) {
    // Forward / Backward — all wheels same direction
    leftSpeed = joyY;
    rightSpeed = joyY;
    mode = (joyY > 0) ? "FORWARD" : "BACKWARD";
  } else {
    // Rotate CW / CCW — pivot (left vs right opposite)
    if (joyX > 0) {
      leftSpeed = abs(joyX);
      rightSpeed = -abs(joyX);
      mode = "ROTATE CW";
    } else {
      leftSpeed = -abs(joyX);
      rightSpeed = abs(joyX);
      mode = "ROTATE CCW";
    }
  }

  // Both left motors get same value, both right motors get same value
  targetLF = leftSpeed;
  targetLB = leftSpeed;
  targetRF = rightSpeed;
  targetRB = rightSpeed;

  // Serial output
  Serial.println("================================================");
  Serial.printf("  MODE  : %s\n", mode);
  

  Serial.printf("  INPUT   LX=%+4d  LY=%+4d\n", joyX, joyY);

  Serial.print("  TARGET  LEFT =");
  if (leftSpeed >= 0)
    Serial.print('+');
  printBar(leftSpeed, MAX_SPEED, 10);
  Serial.print("  RIGHT=");
  if (rightSpeed >= 0)
    Serial.print('+');
  printBar(rightSpeed, MAX_SPEED, 10);
  Serial.println();

  Serial.print("  ACTUAL  LF=");
  printBar(currentLF, MAX_SPEED, 10);
  Serial.printf(" [%c]  RF=", dirChar(currentLF));
  printBar(currentRF, MAX_SPEED, 10);
  Serial.printf(" [%c]\n", dirChar(currentRF));

  Serial.print("           LB=");
  printBar(currentLB, MAX_SPEED, 10);
  Serial.printf(" [%c]  RB=", dirChar(currentLB));
  printBar(currentRB, MAX_SPEED, 10);
  Serial.printf(" [%c]\n", dirChar(currentRB));

  
}

// ================================================================
//  processControllers()
//  Reads the first connected gamepad's left joystick.
// ================================================================
void processControllers() {
  for (auto myController : myControllers) {
    if (myController && myController->isConnected() &&
        myController->hasData()) {
      if (myController->isGamepad()) {

        // Read left joystick axes
        // Bluepad32:  axisX() = left stick horizontal (-511…+512)
        //             axisY() = left stick vertical   (-511…+512)
        //             axisY: +ve = stick DOWN (need to flip for forward)
        int rawLX = myController->axisX();
        int rawLY = myController->axisY();

        // Map from -511…+512 to -255…+255
        int lx = mapAxis(rawLX);
        int ly = mapAxis(-rawLY); // Flip so stick UP = positive (forward)

        lastInputTime = millis();
        processMotion(lx, ly);

        break; // Only process the first connected gamepad
      }
    }
  }
}

// ================================================================
//  setupLEDC()
//  Configures LEDC channels for PWM output to motor drivers.
// ================================================================
void setupLEDC() {
  ledcSetup(LEDC_CH_LF, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(LF_PWM, LEDC_CH_LF);

  ledcSetup(LEDC_CH_LB, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(LB_PWM, LEDC_CH_LB);

  ledcSetup(LEDC_CH_RF, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(RF_PWM, LEDC_CH_RF);

  ledcSetup(LEDC_CH_RB, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(RB_PWM, LEDC_CH_RB);
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
  Serial.begin(115200);

  Serial.println("================================================");
  Serial.println("  R2 NORMAL WHEEL CAR  v1.0  —  ESP32 + Bluepad32");
  Serial.println("================================================");
  Serial.printf("  MAX_SPEED   = %d\n", MAX_SPEED);
  Serial.printf("  DEADZONE    = %d\n", DEADZONE);
  Serial.printf("  RAMP UP     = %d\n", RAMP_UP_STEP);
  Serial.printf("  RAMP DOWN   = %d\n", RAMP_DOWN_STEP);
  Serial.printf("  TIMEOUT     = %d ms\n", CTRL_TIMEOUT);
  Serial.printf("  INVERT FLAGS: LF=%d LB=%d RF=%d RB=%d\n", LF_INVERT,
                LB_INVERT, RF_INVERT, RB_INVERT);
  Serial.println("------------------------------------------------");
  Serial.println("  GPIO Mapping:");
  Serial.printf("    LF: DIR=%d  PWM=%d\n", LF_DIR, LF_PWM);
  Serial.printf("    LB: DIR=%d  PWM=%d\n", LB_DIR, LB_PWM);
  Serial.printf("    RF: DIR=%d  PWM=%d\n", RF_DIR, RF_PWM);
  Serial.printf("    RB: DIR=%d  PWM=%d\n", RB_DIR, RB_PWM);
  Serial.println("================================================");

  // DIR pins — digital output
  pinMode(LF_DIR, OUTPUT);
  pinMode(LB_DIR, OUTPUT);
  pinMode(RF_DIR, OUTPUT);
  pinMode(RB_DIR, OUTPUT);

  // PWM pins — via LEDC
  setupLEDC();

  stopAll();

  // Bluepad32
  Serial.printf("[BP32] Firmware: %s\n", BP32.firmwareVersion());
  const uint8_t *addr = BP32.localBdAddress();
  Serial.printf("[BP32] BD Addr: %2X:%2X:%2X:%2X:%2X:%2X\n", addr[0], addr[1],
                addr[2], addr[3], addr[4], addr[5]);

  BP32.setup(&onConnectedController, &onDisconnectedController);
  BP32.forgetBluetoothKeys();
  BP32.enableVirtualDevice(false);

  lastInputTime = millis();
  Serial.println("[BP32] Waiting for PS4 controller...");
  Serial.println("       Put controller in pairing mode (hold SHARE + PS).");
  Serial.println("================================================");
}

// ================================================================
//  LOOP  (runs every ~5 ms = 200 Hz)
// ================================================================
void loop() {

  // Step 1 — Fetch Bluepad32 controller data
  bool dataUpdated = BP32.update();
  if (dataUpdated) {
    processControllers();
  }

  // Step 2 — Safety timeout (controller disconnect or no data)
  bool activeComms = (millis() - lastInputTime < CTRL_TIMEOUT);
  if (!activeComms) {
    if (targetLF != 0 || targetLB != 0 || targetRF != 0 || targetRB != 0) {
      Serial.println("[TIMEOUT] No controller data — zeroing targets");
    }
    targetLF = targetLB = targetRF = targetRB = 0;
  }

  // Step 3 — Ramp runs every tick for smooth motion
  applyRamp();

  // Step 4 — Yield to prevent watchdog trigger
  delay(LOOP_MS);
}
