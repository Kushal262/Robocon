// ================================================================
//  R2 NORMAL WHEEL CAR  —  ESP32 + Bluepad32 + OTA  v3.0
//  Hardware  : DOIT ESP32 DEVKIT V1 + Rhino MDD20Amp ×2 (drive)
//              + 1× MDD20Amp driving 2 pneumatic solenoid valves
//
//  ★ DUAL-MODE BOOT ★
//    DRIVE MODE  (default)     : Bluetooth ON,  WiFi OFF → PS4 controller
//    OTA MODE    (press BOOT)  : WiFi ON,  Bluetooth OFF → upload code
//
//  Controls (DRIVE mode):
//    Left Stick  → Arcade-drive mixing (forward + turning blended)
//                  Y axis = forward/backward,  X axis = turn direction
//    D-pad       → Fixed-speed digital control + haptic vibration
//    Triangle (△) → Toggle BOTH pneumatics  (expand / close)
//    R1           → Toggle pneumatic 1 only
//    L1           → Toggle pneumatic 2 only
//
//  Features:
//    • S-Curve motor ramping (cubic ease-in-out, no jerks)
//    • D-pad haptic feedback (3 quick vibration bursts)
//    • Arcade-drive joystick mixing (differential steering)    
// ================================================================


#include <ArduinoOTA.h>
#include <Bluepad32.h>
#include <WiFi.h>

// ================================================================
//  ★★★  CHANGE THESE TO YOUR MOBILE HOTSPOT CREDENTIALS  ★★★
// ================================================================
const char *WIFI_SSID = "GALAXY-BOOK5";
const char *WIFI_PASSWORD = "123456123";

// ================================================================
//  MODE SELECTION
// ================================================================
#define BOOT_BUTTON_PIN 0 // GPIO 0 = BOOT button on DEVKIT V1
#define BLUE_LED_PIN 2    // GPIO 2 = built-in blue LED

enum RunMode { MODE_DRIVE, MODE_OTA };
RunMode currentMode = MODE_DRIVE;

// ================================================================
//  PIN DEFINITIONS  —  Motor drivers
// ================================================================
#define LF_DIR 19
#define LF_PWM 18

#define LB_DIR 16
#define LB_PWM 17

#define RF_DIR 27
#define RF_PWM 14

#define RB_DIR 13
#define RB_PWM 12

// Pneumatic solenoid valves (connected via 3rd Rhino MDD20Amp motor driver)
// Each channel uses DIR + PWM just like a motor (PWM at full = solenoid ON)22,23,,,,25,26,,,,27,14,,,,12,13
#define PNEU1_DIR 23 // Pneumatic 1 direction pin (driver 3, channel A)
#define PNEU1_PWM 22 // Pneumatic 1 PWM pin

#define PNEU2_DIR 25 // Pneumatic 2 direction pin (driver 3, channel B)
#define PNEU2_PWM 26 // Pneumatic 2 PWM pin

// ================================================================
//  MOTOR INVERT FLAGS
// ================================================================
#define LF_INVERT 0
#define LB_INVERT 0
#define RF_INVERT 0
#define RB_INVERT 0

// ================================================================
//  TUNING
// ================================================================
#define JOYSTICK_MAX_SPEED 60 // Max speed for left joystick (proportional)
#define DPAD_SPEED         20// Fixed speed for D-pad controls (lower)
#define STICK_DEADZONE     10     // Raw deadzone (out of 512). ~2% travel. Filters drift only
#define EXPO_FACTOR        0.5f   // 0.0 = linear, 1.0 = full cubic. 0.5 = balanced feel
#define RAMP_DURATION_MS   250    // S-curve transition time (ms). Increase = smoother
#define LOOP_MS 5
#define CTRL_TIMEOUT 500

// ── HAPTIC FEEDBACK TUNING ─────────────────────────────────
#define HAPTIC_BURST_ON_MS   80   // Duration of each vibration burst (ms)
#define HAPTIC_BURST_OFF_MS  60   // Gap between bursts (ms)
#define HAPTIC_FORCE         0xC0 // Vibration intensity (0-255)
#define HAPTIC_DURATION      0xC0 // Vibration duration scalar (0-255)
#define HAPTIC_COOLDOWN_MS   200  // Min time between haptic triggers

// ================================================================
//  LEDC PWM
// ================================================================
#define PWM_FREQ 5000
#define PWM_RESOLUTION 8

#define LEDC_CH_LF   0
#define LEDC_CH_LB   1
#define LEDC_CH_RF   2
#define LEDC_CH_RB   3
#define LEDC_CH_PN1  4  // Pneumatic 1 LEDC channel
#define LEDC_CH_PN2  5  // Pneumatic 2 LEDC channel

// ================================================================
//  STATE
// ================================================================
int targetLF = 0, targetLB = 0, targetRF = 0, targetRB = 0;

// ── S-CURVE RAMP STATE (per motor) ─────────────────────────
struct MotorRamp {
  int   startSpeed;
  int   targetSpeed;
  int   currentSpeed;
  unsigned long transitionStart;
  bool  transitioning;
};

MotorRamp rampLF = {0, 0, 0, 0, false};
MotorRamp rampLB = {0, 0, 0, 0, false};
MotorRamp rampRF = {0, 0, 0, 0, false};
MotorRamp rampRB = {0, 0, 0, 0, false};

unsigned long lastInputTime = 0;
bool controllerConnected = false;

// ── PNEUMATIC STATE ─────────────────────────────────────────
bool pneu1State = false;  // false=closed, true=expanded
bool pneu2State = false;

// Edge detection — previous button states for toggle logic
bool prevTriangle = false;
bool prevR1 = false;
bool prevL1 = false;

// ── HAPTIC FEEDBACK STATE ──────────────────────────────────
unsigned long hapticStartTime = 0;
int  hapticBurstIndex = 0;     // 0-5: ON/OFF/ON/OFF/ON/OFF phases
bool hapticActive = false;
bool prevDpadActive = false;   // Edge detection for D-pad
ControllerPtr hapticController = nullptr;  // Which controller to rumble

// ================================================================
//  BLUEPAD32
// ================================================================
ControllerPtr myControllers[BP32_MAX_GAMEPADS];

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
  controllerConnected = false;
  for (int i = 0; i < BP32_MAX_GAMEPADS; i++) {
    if (myControllers[i] != nullptr) {
      controllerConnected = true;
      break;
    }
  }
  if (!controllerConnected)
    Serial.println("[BP32] All controllers disconnected");
}

// ================================================================
//  MOTOR FUNCTIONS
// ================================================================
int applyInvert(int speed, int invertFlag) {
  return invertFlag ? -speed : speed;
}

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

void setPneumatic(uint8_t dirPin, uint8_t ledcChannel, bool state) {
  if (state) {
    digitalWrite(dirPin, HIGH);
    ledcWrite(ledcChannel, 255);  // Full power to energize solenoid
  } else {
    digitalWrite(dirPin, LOW);
    ledcWrite(ledcChannel, 0);    // Off
  }
}

void stopAll() {
  setMotor(LF_DIR, LEDC_CH_LF, 0);
  setMotor(LB_DIR, LEDC_CH_LB, 0);
  setMotor(RF_DIR, LEDC_CH_RF, 0);
  setMotor(RB_DIR, LEDC_CH_RB, 0);
  targetLF = targetLB = targetRF = targetRB = 0;
  rampLF = rampLB = rampRF = rampRB = {0, 0, 0, 0, false};
  // Close both pneumatics
  pneu1State = false;
  pneu2State = false;
  setPneumatic(PNEU1_DIR, LEDC_CH_PN1, false);
  setPneumatic(PNEU2_DIR, LEDC_CH_PN2, false);
}

// ================================================================
//  S-CURVE RAMP  (cubic ease-in-out)
// ================================================================
float sCurve(float t) {
  t = constrain(t, 0.0f, 1.0f);
  if (t < 0.5f)
    return 4.0f * t * t * t;
  else {
    float f = -2.0f * t + 2.0f;
    return 1.0f - (f * f * f) / 2.0f;
  }
}

void updateMotorRamp(MotorRamp &m, int newTarget) {
  if (newTarget != m.targetSpeed) {
    // Target changed — start new S-curve transition from current position
    m.startSpeed = m.currentSpeed;
    m.targetSpeed = newTarget;
    m.transitionStart = millis();
    m.transitioning = true;
  }
  if (m.transitioning) {
    float elapsed = (float)(millis() - m.transitionStart);
    float t = elapsed / (float)RAMP_DURATION_MS;
    if (t >= 1.0f) {
      m.currentSpeed = m.targetSpeed;
      m.transitioning = false;
    } else {
      float progress = sCurve(t);
      m.currentSpeed = m.startSpeed +
                       (int)((float)(m.targetSpeed - m.startSpeed) * progress);
    }
  }
}

void applyRamp() {
  updateMotorRamp(rampLF, targetLF);
  updateMotorRamp(rampLB, targetLB);
  updateMotorRamp(rampRF, targetRF);
  updateMotorRamp(rampRB, targetRB);

  setMotor(LF_DIR, LEDC_CH_LF, applyInvert(rampLF.currentSpeed, LF_INVERT));
  setMotor(LB_DIR, LEDC_CH_LB, applyInvert(rampLB.currentSpeed, LB_INVERT));
  setMotor(RF_DIR, LEDC_CH_RF, applyInvert(rampRF.currentSpeed, RF_INVERT));
  setMotor(RB_DIR, LEDC_CH_RB, applyInvert(rampRB.currentSpeed, RB_INVERT));
}

// ================================================================
//  SERIAL HELPERS
// ================================================================
char dirChar(int s) { return s > 0 ? 'F' : (s < 0 ? 'R' : 'S'); }

void printBar(int speed, int maxSpeed, int width) {
  int filled = (int)((float)abs(speed) / maxSpeed * width + 0.5f);
  filled = constrain(filled, 0, width);
  Serial.print('[');
  for (int i = 0; i < width; i++)
    Serial.print(i < filled ? '#' : ' ');
  Serial.print(']');
  if (speed >= 0)
    Serial.print(' ');
  Serial.print(speed);
}

int mapAxis(int raw) {
  // 1. Tiny raw deadzone — just enough to stop drift, NOT noticeable to human
  if (abs(raw) < STICK_DEADZONE) return 0;

  // 2. Rescale [deadzone..512] → [0.0..1.0], preserving sign (no jump at edge)
  float sign    = (raw > 0) ? 1.0f : -1.0f;
  float absNorm = ((float)abs(raw) - STICK_DEADZONE) / (512.0f - STICK_DEADZONE);
  absNorm       = constrain(absNorm, 0.0f, 1.0f);

  // 3. RC-style expo curve: blend linear + cubic
  //    Low expo → more linear (responsive).  High expo → more cubic (gentle center)
  float curved  = (1.0f - EXPO_FACTOR) * absNorm
                + EXPO_FACTOR * absNorm * absNorm * absNorm;

  // 4. Scale to max speed
  return (int)(sign * curved * JOYSTICK_MAX_SPEED);
}

// ================================================================
//  processMotion() — Arcade-drive mixing (differential steering)
//  maxSpeed: speed cap (JOYSTICK_MAX_SPEED or DPAD_SPEED)
//  source : label for serial output ("JOYSTICK" or "DPAD")
// ================================================================
void processMotion(int joyX, int joyY, int maxSpeed, const char *source) {
  // Deadzone is now handled properly inside mapAxis() with rescaling

  joyX = constrain(joyX, -maxSpeed, maxSpeed);
  joyY = constrain(joyY, -maxSpeed, maxSpeed);

  // ── Arcade-drive mixing ──────────────────────────────────
  //   leftSpeed  = forward + turn
  //   rightSpeed = forward - turn
  int leftSpeed  = constrain(joyY + joyX, -maxSpeed, maxSpeed);
  int rightSpeed = constrain(joyY - joyX, -maxSpeed, maxSpeed);

  // ── Determine mode label for serial output ───────────────
  const char *mode;
  if (joyX == 0 && joyY == 0) {
    mode = "STOP";
  } else if (joyX == 0) {
    mode = (joyY > 0) ? "FORWARD" : "BACKWARD";
  } else if (joyY == 0) {
    mode = (joyX > 0) ? "ROTATE CW" : "ROTATE CCW";
  } else if (joyY > 0) {
    mode = (joyX > 0) ? "FWD+RIGHT" : "FWD+LEFT";
  } else {
    mode = (joyX > 0) ? "BWD+RIGHT" : "BWD+LEFT";
  }

  targetLF = leftSpeed;
  targetLB = leftSpeed;
  targetRF = rightSpeed;
  targetRB = rightSpeed;

  // Serial output
  Serial.println("================================================");
  Serial.printf("  SOURCE: %s  |  MODE: %s\n", source, mode);
  Serial.println("------------------------------------------------");
  Serial.printf("  INPUT   X=%+4d  Y=%+4d  MAX=%d\n", joyX, joyY, maxSpeed);

  Serial.print("  TARGET  LEFT =");
  if (leftSpeed >= 0)
    Serial.print('+');
  printBar(leftSpeed, maxSpeed, 10);
  Serial.print("  RIGHT=");
  if (rightSpeed >= 0)
    Serial.print('+');
  printBar(rightSpeed, maxSpeed, 10);
  Serial.println();

  Serial.print("  ACTUAL  LF=");
  printBar(rampLF.currentSpeed, maxSpeed, 10);
  Serial.printf(" [%c]  RF=", dirChar(rampLF.currentSpeed));
  printBar(rampRF.currentSpeed, maxSpeed, 10);
  Serial.printf(" [%c]\n", dirChar(rampRF.currentSpeed));

  Serial.print("           LB=");
  printBar(rampLB.currentSpeed, maxSpeed, 10);
  Serial.printf(" [%c]  RB=", dirChar(rampLB.currentSpeed));
  printBar(rampRB.currentSpeed, maxSpeed, 10);
  Serial.printf(" [%c]\n", dirChar(rampRB.currentSpeed));

  Serial.println("================================================");
}

// ================================================================
//  processPneumatics() — Toggle solenoids with edge detection
// ================================================================
void processPneumatics(ControllerPtr ctl) {
  uint16_t buttons = ctl->buttons();

  // ── Triangle → toggle BOTH pneumatics ───────────────────
  bool triNow = (buttons & (1 << 3));  // button3 = Triangle
  if (triNow && !prevTriangle) {
    // Rising edge — toggle both
    pneu1State = !pneu1State;
    pneu2State = pneu1State;  // sync both to same state
    setPneumatic(PNEU1_DIR, LEDC_CH_PN1, pneu1State);
    setPneumatic(PNEU2_DIR, LEDC_CH_PN2, pneu2State);
    Serial.printf("[PNEU] △ Triangle → BOTH %s\n",
                  pneu1State ? "EXPANDED" : "CLOSED");
  }
  prevTriangle = triNow;

  // ── R1 → toggle pneumatic 1 only ───────────────────────
  bool r1Now = (buttons & (1 << 5));  // button5 = R1 (shoulder right)
  if (r1Now && !prevR1) {
    pneu1State = !pneu1State;
    setPneumatic(PNEU1_DIR, LEDC_CH_PN1, pneu1State);
    Serial.printf("[PNEU] R1 → Pneumatic 1 %s\n",
                  pneu1State ? "EXPANDED" : "CLOSED");
  }
  prevR1 = r1Now;

  // ── L1 → toggle pneumatic 2 only ───────────────────────
  bool l1Now = (buttons & (1 << 4));  // button4 = L1 (shoulder left)
  if (l1Now && !prevL1) {
    pneu2State = !pneu2State;
    setPneumatic(PNEU2_DIR, LEDC_CH_PN2, pneu2State);
    Serial.printf("[PNEU] L1 → Pneumatic 2 %s\n",
                  pneu2State ? "EXPANDED" : "CLOSED");
  }
  prevL1 = l1Now;
}

// ================================================================
//  HAPTIC FEEDBACK  — non-blocking 3-burst pulsating vibration
// ================================================================
void triggerHaptic() {
  hapticActive = true;
  hapticBurstIndex = 0;
  hapticStartTime = millis();
}

void updateHaptic() {
  if (!hapticActive || hapticController == nullptr) return;

  unsigned long elapsed = millis() - hapticStartTime;

  // Each burst cycle = ON phase + OFF phase
  // Phase 0,2,4 = ON;  Phase 1,3,5 = OFF
  // After phase 5 = done (3 bursts complete)
  if (hapticBurstIndex >= 6) {
    // All 3 bursts done
    hapticActive = false;
    hapticController->setRumble(0, 0);  // Ensure rumble stops
    return;
  }

  bool isOnPhase = (hapticBurstIndex % 2 == 0);
  unsigned long phaseDuration = isOnPhase ? HAPTIC_BURST_ON_MS : HAPTIC_BURST_OFF_MS;

  if (elapsed >= phaseDuration) {
    // Move to next phase
    hapticBurstIndex++;
    hapticStartTime = millis();

    if (hapticBurstIndex < 6) {
      bool nextOn = (hapticBurstIndex % 2 == 0);
      if (nextOn) {
        hapticController->setRumble(HAPTIC_FORCE, HAPTIC_DURATION);
      } else {
        hapticController->setRumble(0, 0);
      }
    } else {
      hapticController->setRumble(0, 0);  // Final stop
      hapticActive = false;
    }
  } else if (hapticBurstIndex == 0 && elapsed == 0) {
    // First burst — start rumble
    hapticController->setRumble(HAPTIC_FORCE, HAPTIC_DURATION);
  }
}

// ================================================================
//  processControllers()
// ================================================================
void processControllers() {
  for (auto myController : myControllers) {
    if (myController && myController->isConnected() &&
        myController->hasData()) {
      if (myController->isGamepad()) {
        lastInputTime = millis();
        hapticController = myController;  // Track for haptic updates

        // ── D-PAD input (fixed DPAD_SPEED, takes priority) ──────
        uint8_t dpad = myController->dpad();
        int dpadX = 0, dpadY = 0;

        if (dpad & DPAD_UP)    dpadY =  DPAD_SPEED;
        if (dpad & DPAD_DOWN)  dpadY = -DPAD_SPEED;
        if (dpad & DPAD_RIGHT) dpadX =  DPAD_SPEED;
        if (dpad & DPAD_LEFT)  dpadX = -DPAD_SPEED;

        bool dpadActive = (dpadX != 0 || dpadY != 0);

        // ── Haptic: trigger on D-pad rising edge ──────────────
        if (dpadActive && !prevDpadActive && !hapticActive) {
          triggerHaptic();
        }
        prevDpadActive = dpadActive;

        if (dpadActive) {
          // D-pad is active → use fixed DPAD_SPEED
          processMotion(dpadX, dpadY, DPAD_SPEED, "DPAD");
        } else {
          // ── Left joystick (proportional, max JOYSTICK_MAX_SPEED) ──
          int lx = mapAxis(myController->axisX());
          int ly = mapAxis(-(myController->axisY())); // Flip: UP = positive
          processMotion(lx, ly, JOYSTICK_MAX_SPEED, "JOYSTICK");
        }

        processPneumatics(myController);
        break;
      }
    }
  }
}

// ================================================================
//  setupLEDC()
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
  // Pneumatic channels (same motor driver, need PWM)
  ledcSetup(LEDC_CH_PN1, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(PNEU1_PWM, LEDC_CH_PN1);
  ledcSetup(LEDC_CH_PN2, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(PNEU2_PWM, LEDC_CH_PN2);
}

// ================================================================
//  setupOTA() — WiFi + ArduinoOTA for OTA mode
// ================================================================
void setupOTA() {
  // Blue LED blinks while connecting
  Serial.printf("[WiFi] Connecting to \"%s\"...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startAttempt = millis();
  bool ledOn = false;
  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 15000) {
    ledOn = !ledOn;
    digitalWrite(BLUE_LED_PIN, ledOn);
    delay(200);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(BLUE_LED_PIN, LOW);
    Serial.println("[WiFi] FAILED to connect!");
    Serial.println("       Check hotspot name/password.");
    Serial.println("       Reset ESP32 to try again.");
    // Stay in a loop blinking slowly to indicate failure
    while (true) {
      digitalWrite(BLUE_LED_PIN, HIGH);
      delay(1000);
      digitalWrite(BLUE_LED_PIN, LOW);
      delay(1000);
      Serial.println("[WiFi] Waiting... reset ESP32 to retry.");
    }
  }

  // WiFi connected — solid LED
  digitalWrite(BLUE_LED_PIN, HIGH);
  Serial.printf("[WiFi] Connected!  IP: %s\n",
                WiFi.localIP().toString().c_str());

  // Setup ArduinoOTA
  ArduinoOTA.setHostname("R2-Car");

  ArduinoOTA.onStart([]() {
    String type =
        (ArduinoOTA.getCommand() == U_FLASH) ? "sketch" : "filesystem";
    Serial.printf("[OTA] Update started (%s)\n", type.c_str());
  });

  ArduinoOTA.onEnd(
      []() { Serial.println("\n[OTA] Update complete! Rebooting..."); });

  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("\r[OTA] Progress: %u%%", (progress * 100) / total);
  });

  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("\n[OTA] Error[%u]: ", error);
    if (error == OTA_AUTH_ERROR)
      Serial.println("Auth Failed");
    else if (error == OTA_BEGIN_ERROR)
      Serial.println("Begin Failed");
    else if (error == OTA_CONNECT_ERROR)
      Serial.println("Connect Failed");
    else if (error == OTA_RECEIVE_ERROR)
      Serial.println("Receive Failed");
    else if (error == OTA_END_ERROR)
      Serial.println("End Failed");
  });

  ArduinoOTA.begin();
  Serial.println("[OTA] Ready!");
  Serial.println("================================================");
  Serial.printf("  In Arduino IDE: Tools → Port → \"R2-Car at %s\"\n",
                WiFi.localIP().toString().c_str());
  Serial.println("  Then click Upload!");
  Serial.println("================================================");
}

// ================================================================
//  setupDrive() — Bluepad32 for DRIVE mode
// ================================================================
void setupDrive() {
  Serial.printf("[BP32] Firmware: %s\n", BP32.firmwareVersion());
  const uint8_t *addr = BP32.localBdAddress();
  Serial.printf("[BP32] BD Addr: %2X:%2X:%2X:%2X:%2X:%2X\n", addr[0], addr[1],
                addr[2], addr[3], addr[4], addr[5]);

  BP32.setup(&onConnectedController, &onDisconnectedController);
  BP32.forgetBluetoothKeys();
  BP32.enableVirtualDevice(false);

  lastInputTime = millis();
  Serial.println("================================================");
  Serial.println("[READY] DRIVE MODE — Waiting for PS4 controller...");
  Serial.println("        Put PS4 controller in pairing mode:");
  Serial.println("        Hold  SHARE + PS  buttons together");
  Serial.println("        until the light bar blinks rapidly.");
  Serial.println("================================================");
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
  Serial.begin(115200);
  delay(500); // Let serial stabilize

  // LED + BOOT button
  pinMode(BLUE_LED_PIN, OUTPUT);
  digitalWrite(BLUE_LED_PIN, LOW);
  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);

  // ── Banner ───────────────────────────────────────────────
  Serial.println();
  Serial.println("================================================");
  Serial.println("  R2 NORMAL WHEEL CAR  v3.0  —  ESP32");
  Serial.println("  S-Curve Ramp | Arcade-Drive | D-Pad Haptic");
  Serial.println("================================================");
  Serial.printf("  JOYSTICK=%d  DPAD=%d  DZ=%d  EXPO=%.1f  RAMP=%dms\n",
                JOYSTICK_MAX_SPEED, DPAD_SPEED, STICK_DEADZONE, EXPO_FACTOR, RAMP_DURATION_MS);
  Serial.printf("  GPIO: LF=%d/%d  LB=%d/%d  RF=%d/%d  RB=%d/%d\n", LF_DIR,
                LF_PWM, LB_DIR, LB_PWM, RF_DIR, RF_PWM, RB_DIR, RB_PWM);
  Serial.printf("  GPIO: PNEU1=%d/%d  PNEU2=%d/%d\n", PNEU1_DIR, PNEU1_PWM, PNEU2_DIR, PNEU2_PWM);
  Serial.println("------------------------------------------------");

  // ── 3-second mode selection countdown ────────────────────
  // LED blinks during countdown. Press BOOT to enter OTA mode.
  Serial.println("  Press BOOT button within 3 seconds for OTA mode...");
  Serial.println("  (or wait for DRIVE mode)");
  Serial.println("------------------------------------------------");

  bool bootDetected = false;
  unsigned long countdownStart = millis();
  bool ledOn = false;
  int lastSecond = -1;

  while (millis() - countdownStart < 3000) {
    // Blink LED every 250ms during countdown
    if ((millis() / 250) % 2 != ledOn) {
      ledOn = !ledOn;
      digitalWrite(BLUE_LED_PIN, ledOn);
    }

    // Print countdown seconds
    int secondsLeft = 3 - (int)((millis() - countdownStart) / 1000);
    if (secondsLeft != lastSecond) {
      lastSecond = secondsLeft;
      Serial.printf("  %d...\n", secondsLeft);
    }

    // Check BOOT button (active LOW)
    if (digitalRead(BOOT_BUTTON_PIN) == LOW) {
      bootDetected = true;
      Serial.println("  ★ BOOT pressed! Entering OTA mode...");
      break;
    }

    delay(10);
  }

  if (bootDetected) {
    currentMode = MODE_OTA;
  } else {
    currentMode = MODE_DRIVE;
  }

  Serial.println("================================================");
  if (currentMode == MODE_OTA) {
    Serial.println("  ★ OTA MODE ★  (BOOT button was pressed)");
    Serial.println("  WiFi ON  |  Bluetooth OFF  |  Blue LED ON");
  } else {
    Serial.println("  ★ DRIVE MODE ★  (no button pressed)");
    Serial.println("  WiFi OFF  |  Bluetooth ON  |  Blue LED OFF");
  }
  Serial.println("------------------------------------------------");

  // Motor pins
  pinMode(LF_DIR, OUTPUT);
  pinMode(LB_DIR, OUTPUT);
  pinMode(RF_DIR, OUTPUT);
  pinMode(RB_DIR, OUTPUT);
  // Pneumatic solenoid pins (via motor driver — DIR + PWM)
  pinMode(PNEU1_DIR, OUTPUT);
  pinMode(PNEU2_DIR, OUTPUT);
  digitalWrite(PNEU1_DIR, LOW);
  digitalWrite(PNEU2_DIR, LOW);
  setupLEDC();
  stopAll();

  // ── Start the selected mode ──────────────────────────────
  if (currentMode == MODE_OTA) {
    setupOTA();
  } else {
    digitalWrite(BLUE_LED_PIN, LOW); // LED off in drive mode
    setupDrive();
  }
}

// ================================================================
//  LOOP
// ================================================================
void loop() {

  if (currentMode == MODE_OTA) {
    // ── OTA MODE: just handle OTA, nothing else ──────────
    ArduinoOTA.handle();
    delay(10);
    return;
  }

  // ── DRIVE MODE ───────────────────────────────────────────

  // Step 1 — Fetch controller data
  bool dataUpdated = BP32.update();
  if (dataUpdated) {
    processControllers();
  }

  // Step 2 — Update haptic feedback state machine (non-blocking)
  updateHaptic();

  // Step 3 — Safety timeout (motors only; pneumatics hold state)
  bool activeComms = (millis() - lastInputTime < CTRL_TIMEOUT);
  if (!activeComms) {
    if (targetLF != 0 || targetLB != 0 || targetRF != 0 || targetRB != 0) {
      Serial.println("[TIMEOUT] No controller data — zeroing motor targets");
    }
    targetLF = targetLB = targetRF = targetRB = 0;
  }

  // Step 4 — S-Curve smooth ramp
  applyRamp();

  // Step 5 — Yield to prevent watchdog
  delay(LOOP_MS);
}
