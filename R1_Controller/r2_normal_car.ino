// ================================================================
//  R2 NORMAL WHEEL CAR  —  v1.0
//  Hardware  : Arduino Mega 2560 + Rhino MDD20Amp ×2 + 4 DC Motors
//  Interface : PS4 via Python (pygame + pyserial) over USB cable
//
//  Serial packet received from Python:
//    <LX,LY>\n
//    LX  : left  stick X   -255…+255   (+ve = turn right)
//    LY  : left  stick Y   -255…+255   (+ve = forward)
//
//  Controls (4-directional, no diagonal mixing):
//    Left  Stick ↑ → Forward   (all 4 wheels forward)
//    Left  Stick ↓ → Backward  (all 4 wheels reverse)
//    Left  Stick → → Rotate CW (left wheels fwd, right wheels rev)
//    Left  Stick ← → Rotate CCW(left wheels rev, right wheels fwd)
//
//  Features:
//    • Smooth ramp-up / ramp-down
//    • Detailed serial monitor output
//    • Safety timeout: motors stop if no packet for 500 ms
//    • Heartbeat LED on pin 13
//    • Serial command  "PING\n"  replies  "PONG"  for comms check
//    • Low-latency 5 ms loop (200 Hz)
// ================================================================

// ================================================================
//  WIRING  —  Rhino MDD20Amp  (DIR pin + PWM pin per channel)
//
//  LEFT  MDD20Amp
//    CH1  DIR=22  PWM=2   →  Left  Front  (LF)
//    CH2  DIR=24  PWM=3   →  Left  Back   (LB)
//
//  RIGHT MDD20Amp
//    CH1  DIR=26  PWM=4   →  Right Front  (RF)
//    CH2  DIR=36  PWM=6   →  Right Back   (RB)
//
//  DIR HIGH  =  forward spin
//  DIR LOW   =  reverse spin
//
// ================================================================

// ================================================================
//  PIN DEFINITIONS
// ================================================================
#define LF_DIR 22
#define LF_PWM 2

#define LB_DIR 24
#define LB_PWM 3

#define RF_DIR 26
#define RF_PWM 4

#define RB_DIR 36
#define RB_PWM 6

#define LED_PIN 13 // Onboard LED used as heartbeat

// ================================================================
//  MOTOR INVERT FLAGS
//  Set to 1 if a motor spins the wrong way for its position on
//  the chassis (e.g. mounted mirrored / gearbox on opposite side).
//  This is a SOFTWARE fix — no rewiring needed.
// ================================================================
#define LF_INVERT 0
#define LB_INVERT 0
#define RF_INVERT 0
#define RB_INVERT 0 // ← change to 1 if RB still wrong direction

// ================================================================
//  TUNING
// ================================================================
#define MAX_SPEED                                                              \
  180 // ← INCREASED to 180. A PWM of 60 is often too weak to spin motors when
      //   the car is on the ground (stall torque), causing wheels to remain
      //   still!

#define DEADZONE 20 // ignore stick drift below this value

#define RAMP_UP_STEP 14   // acceleration step per 5 ms tick
#define RAMP_DOWN_STEP 16 // deceleration step per 5 ms tick

#define LOOP_MS 5          // 200 Hz loop
#define SERIAL_TIMEOUT 500 // ms — stop motors if comms lost

// ================================================================
//  RAMP STATE
// ================================================================
int targetLF = 0, targetLB = 0, targetRF = 0, targetRB = 0;
int currentLF = 0, currentLB = 0, currentRF = 0, currentRB = 0;

unsigned long lastPacketTime = 0;
unsigned long lastLEDTime = 0;
bool ledState = false;
bool motorsEnabled = true;

// ================================================================
//  applyInvert()
// ================================================================
int applyInvert(int speed, int invertFlag) {
  return invertFlag ? -speed : speed;
}

// ================================================================
//  setMotor()
//  Drives one motor channel on the Rhino MDD20Amp.
//
//  speed:  +1 … +255  → DIR HIGH, PWM = speed   (forward)
//          -1 … -255  → DIR LOW,  PWM = |speed|  (reverse)
//          0          → DIR LOW,  PWM = 0         (stop / coast)
// ================================================================
void setMotor(uint8_t dirPin, uint8_t pwmPin, int speed) {
  speed = constrain(speed, -255, 255);

  if (speed > 0) {
    digitalWrite(dirPin, HIGH);
    analogWrite(pwmPin, speed);
  } else if (speed < 0) {
    digitalWrite(dirPin, LOW);
    analogWrite(pwmPin, -speed);
  } else {
    digitalWrite(dirPin, LOW);
    analogWrite(pwmPin, 0);
  }
}

// ================================================================
//  stopAll()  —  immediate hard stop, resets ramp state
// ================================================================
void stopAll() {
  setMotor(LF_DIR, LF_PWM, 0);
  setMotor(LB_DIR, LB_PWM, 0);
  setMotor(RF_DIR, RF_PWM, 0);
  setMotor(RB_DIR, RB_PWM, 0);
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

  // Determine if we are accelerating (moving away from 0) or decelerating
  // (moving toward 0)
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
  if (!motorsEnabled)
    return;

  currentLF = rampStep(currentLF, targetLF);
  currentLB = rampStep(currentLB, targetLB);
  currentRF = rampStep(currentRF, targetRF);
  currentRB = rampStep(currentRB, targetRB);

  setMotor(LF_DIR, LF_PWM, applyInvert(currentLF, LF_INVERT));
  setMotor(LB_DIR, LB_PWM, applyInvert(currentLB, LB_INVERT));
  setMotor(RF_DIR, RF_PWM, applyInvert(currentRF, RF_INVERT));
  setMotor(RB_DIR, RB_PWM, applyInvert(currentRB, RB_INVERT));
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
//  processGamepad()
//  Takes left joystick values, sets targetXX for all 4 motors.
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
//    RIGHT    : left fwd, right rev    (speed = |LX|)
//    LEFT     : left rev, right fwd    (speed = |LX|)
// ================================================================
void processGamepad(int joyX, int joyY) {

  // ----------------------------------------------------------
  //  Deadzone
  // ----------------------------------------------------------
  if (abs(joyX) < DEADZONE)
    joyX = 0;
  if (abs(joyY) < DEADZONE)
    joyY = 0;

  // ----------------------------------------------------------
  //  Cap to MAX_SPEED
  // ----------------------------------------------------------
  joyX = constrain(joyX, -MAX_SPEED, MAX_SPEED);
  joyY = constrain(joyY, -MAX_SPEED, MAX_SPEED);

  // ----------------------------------------------------------
  //  4-directional: dominant axis wins, no mixing
  // ----------------------------------------------------------
  int leftSpeed = 0;
  int rightSpeed = 0;
  const char *mode;

  if (joyX == 0 && joyY == 0) {
    // STOP
    mode = "STOP";
  } else if (abs(joyY) >= abs(joyX)) {
    // Forward / Backward — all wheels same direction
    leftSpeed = joyY;
    rightSpeed = joyY;
    mode = (joyY > 0) ? "FORWARD" : "BACKWARD";
  } else {
    // Rotate CW / CCW — pivot (left vs right opposite)
    if (joyX > 0) {
      // CW: left wheels forward, right wheels backward
      leftSpeed = abs(joyX);
      rightSpeed = -abs(joyX);
      mode = "ROTATE CW";
    } else {
      // CCW: left wheels backward, right wheels forward
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

  // ----------------------------------------------------------
  //  Serial output
  // ----------------------------------------------------------
  Serial.println(F("================================================"));
  Serial.print(F("  MODE  : "));
  Serial.println(mode);
  Serial.println(F("------------------------------------------------"));

  // Input row
  Serial.print(F("  INPUT   LX="));
  if (joyX >= 0)
    Serial.print('+');
  Serial.print(joyX);
  Serial.print(F("  LY="));
  if (joyY >= 0)
    Serial.print('+');
  Serial.println(joyY);

  // Target row
  Serial.print(F("  TARGET  LEFT ="));
  if (leftSpeed >= 0)
    Serial.print('+');
  printBar(leftSpeed, MAX_SPEED, 10);
  Serial.print(F("  RIGHT="));
  if (rightSpeed >= 0)
    Serial.print('+');
  printBar(rightSpeed, MAX_SPEED, 10);
  Serial.println();

  // Actual (ramped) row
  Serial.print(F("  ACTUAL  LF="));
  printBar(currentLF, MAX_SPEED, 10);
  Serial.print(F(" ["));
  Serial.print(dirChar(currentLF));
  Serial.print(F("]  RF="));
  printBar(currentRF, MAX_SPEED, 10);
  Serial.print(F(" ["));
  Serial.print(dirChar(currentRF));
  Serial.println(']');

  Serial.print(F("           LB="));
  printBar(currentLB, MAX_SPEED, 10);
  Serial.print(F(" ["));
  Serial.print(dirChar(currentLB));
  Serial.print(F("]  RB="));
  printBar(currentRB, MAX_SPEED, 10);
  Serial.print(F(" ["));
  Serial.print(dirChar(currentRB));
  Serial.println(']');

  // RB invert flag reminder
  if (RB_INVERT) {
    Serial.println(F("  [NOTE] RB_INVERT=1 — RB direction is flipped in SW"));
  }

  // Timeout warning
  if (millis() - lastPacketTime > SERIAL_TIMEOUT / 2) {
    Serial.println(F("  [WARN] No packet recently — check PC connection"));
  }

  Serial.println(F("================================================"));
}

// ================================================================
//  SERIAL PARSER
//  Reads bytes until a complete <...> packet is received.
//  Also intercepts plain-text command  PING.
// ================================================================
const int BUF_SIZE = 32;
char rxBuf[BUF_SIZE];
int rxIdx = 0;
bool inPacket = false;

char cmdBuf[BUF_SIZE];
int cmdIdx = 0;

bool readPacket() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '<') {
      inPacket = true;
      rxIdx = 0;
      cmdIdx = 0;
    } else if (c == '>' && inPacket) {
      rxBuf[rxIdx] = '\0';
      inPacket = false;
      rxIdx = 0;
      return true;
    } else if (inPacket && rxIdx < BUF_SIZE - 1) {
      rxBuf[rxIdx++] = c;
    }

    else if (!inPacket) {
      if (c == '\n' || c == '\r') {
        if (cmdIdx > 0) {
          cmdBuf[cmdIdx] = '\0';
          cmdIdx = 0;

          if (strcmp(cmdBuf, "PING") == 0) {
            Serial.println(F("PONG"));
          }
        }
      } else if (cmdIdx < BUF_SIZE - 1) {
        cmdBuf[cmdIdx++] = c;
      }
    }
  }
  return false;
}

// ================================================================
//  heartbeat()
// ================================================================
void heartbeat(bool activeComms) {
  unsigned long interval = activeComms ? 200UL : 800UL;
  if (millis() - lastLEDTime >= interval) {
    lastLEDTime = millis();
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
  Serial.begin(115200);

  Serial.println(F("================================================"));
  Serial.println(F("  R2 NORMAL WHEEL CAR  v1.0  —  Arduino Mega"));
  Serial.println(F("================================================"));
  Serial.print(F("  MAX_SPEED   = "));
  Serial.println(MAX_SPEED);
  Serial.print(F("  DEADZONE    = "));
  Serial.println(DEADZONE);
  Serial.print(F("  RAMP UP     = "));
  Serial.println(RAMP_UP_STEP);
  Serial.print(F("  RAMP DOWN   = "));
  Serial.println(RAMP_DOWN_STEP);
  Serial.print(F("  TIMEOUT     = "));
  Serial.print(SERIAL_TIMEOUT);
  Serial.println(F(" ms"));
  Serial.print(F("  INVERT FLAGS: LF="));
  Serial.print(LF_INVERT);
  Serial.print(F(" LB="));
  Serial.print(LB_INVERT);
  Serial.print(F(" RF="));
  Serial.print(RF_INVERT);
  Serial.print(F(" RB="));
  Serial.println(RB_INVERT);
  Serial.println(F("------------------------------------------------"));
  Serial.println(F("  Serial commands (send as plain text + Enter):"));
  Serial.println(F("    PING  — connectivity check (replies PONG)"));
  Serial.println(F("================================================"));

  // Motor pins
  pinMode(LF_DIR, OUTPUT);
  pinMode(LF_PWM, OUTPUT);
  pinMode(LB_DIR, OUTPUT);
  pinMode(LB_PWM, OUTPUT);
  pinMode(RF_DIR, OUTPUT);
  pinMode(RF_PWM, OUTPUT);
  pinMode(RB_DIR, OUTPUT);
  pinMode(RB_PWM, OUTPUT);

  pinMode(LED_PIN, OUTPUT);

  stopAll();

  lastPacketTime = millis();
  Serial.println(F("Ready. Run ps4_to_arduino_R2.py on your PC."));
  Serial.println(F("================================================"));
}

// ================================================================
//  LOOP  (runs every ~5 ms = 200 Hz)
// ================================================================
void loop() {

  bool activeComms = (millis() - lastPacketTime < SERIAL_TIMEOUT);

  // Step 1 — parse incoming serial packet or command
  if (readPacket()) {
    int lx, ly;
    if (sscanf(rxBuf, "%d,%d", &lx, &ly) == 2) {
      lastPacketTime = millis();
      processGamepad(lx, ly);
    } else {
      Serial.print(F("[ERR] Bad packet: <"));
      Serial.print(rxBuf);
      Serial.println('>');
    }
  }

  // Step 2 — safety timeout
  if (!activeComms) {
    if (targetLF != 0 || targetLB != 0 || targetRF != 0 || targetRB != 0) {
      Serial.println(F("[TIMEOUT] Comms lost — zeroing targets"));
    }
    targetLF = targetLB = targetRF = targetRB = 0;
  }

  // Step 3 — ramp runs every tick for smooth motion
  applyRamp();

  // Step 4 — heartbeat LED
  heartbeat(activeComms);

  delay(LOOP_MS);
}
