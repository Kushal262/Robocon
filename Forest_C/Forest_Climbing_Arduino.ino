// ============================================================
//  R2 - Forest Climbing Controller (Arduino)
//  Date: June 2026
//
//  Based on R2_Full_Manual_v2.ino
//  Additions:
//    - Limit switch homing for lift steppers (NC fail-safe)
//    - Homing state machine (UP → DOWN → ZERO → SAFE_UP → READY)
//    - Software position limit: pulseCount cannot go below 0
//    - New lift command 'C' = start calibration/homing
//
//  PACKET FORMAT (10 fields, CSV, newline terminated):
//  "LF,RF,LB,RB,LIFT,S1,S2,ARM,DCV_KFS,DCV_SH\n"
//
//  LIFT field values:
//    N = Both UP,  M = Both DOWN
//    H = Back UP,  J = Back DOWN
//    K = Front UP, L = Front DOWN
//    S = Stop,     C = Calibrate (start homing)
// ============================================================

#include <Servo.h>

// ============================================================
//  CONFIG BLOCK
// ============================================================

// --- DRIVE (MDDS30) ---
#define LF_PWM_PIN    8
#define LF_DIR_PIN    39
#define RF_PWM_PIN    9
#define RF_DIR_PIN    38
#define LB_PWM_PIN    4
#define LB_DIR_PIN    41
#define RB_PWM_PIN    5
#define RB_DIR_PIN    40
#define DRIVE_FWD     HIGH
#define DRIVE_REV     LOW
#define DRIVE_RAMP    4

// --- LIFT STEPPERS ---
#define LIFT1_PUL     11
#define LIFT1_DIR_PIN 10
#define LIFT2_PUL     37
#define LIFT2_DIR_PIN 36
#define DIR_UP        HIGH
#define DIR_DOWN      LOW
#define LIFT_START_US 800UL
#define LIFT_MIN_US   120UL
#define LIFT_ACCEL_US 3UL
#define LIFT_DECEL_US 5UL

// --- LIFT LIMIT SWITCHES (NC - Normally Closed, fail-safe) ---
// Wiring: Pin → NC switch → GND.  Using INPUT_PULLUP.
//   LOW  = switch closed (normal, wire intact)
//   HIGH = switch triggered (opened) OR wire disconnected (fail-safe)
#define LIFT1_LIMIT_PIN  45   // <-- SET YOUR PIN for lift1 (back) limit switch
#define LIFT2_LIMIT_PIN  47   // <-- SET YOUR PIN for lift2 (front) limit switch
#define LIMIT_TRIGGERED  HIGH // NC switch: HIGH = triggered or wire broken

// --- HOMING CONFIG ---
#define PULSES_PER_REV     800UL    // 800 pulses = 1 full revolution = 1cm lift
#define HOMING_UP_PULSES   1200UL   // 1.5 revolutions to clear the switch area
#define HOMING_SAFE_PULSES 800UL    // 1 revolution up after zeroing (safe height)
#define HOMING_START_US    3500UL   // Very slow start for smooth homing
#define HOMING_SLOW_US     2500UL   // 2500us * 800 pulses = 2,000,000us (2 seconds per revolution)
#define HOMING_ACCEL_US    4UL      // Gentle accel during homing
#define HOMING_DECEL_US    8UL      // Gentle decel during homing

// --- ARM STEPPER ---
#define ARM_PUL_PIN   7
#define ARM_DIR_PIN   53
#define ARM_EXTEND    true
#define ARM_RETRACT   false
#define ARM_START_US  1000UL
#define ARM_MIN_US    500UL
#define ARM_ACCEL_US  6UL
#define ARM_DECEL_US  8UL

// --- SERVO1 (spearhead gripper arm, pin 6, 180deg) ---
#define SERVO1_PIN      6
#define SERVO1_MIN_US   500
#define SERVO1_MAX_US   2500
#define SERVO1_DEG_MIN  0
#define SERVO1_DEG_MAX  180

// --- SERVO2 (KFS gripper arm, pin 12, 270deg) ---
#define SERVO2_PIN      12
#define SERVO2_MIN_US   500
#define SERVO2_MAX_US   2500
#define SERVO2_DEG_MIN  0
#define SERVO2_DEG_MAX  270
#define SERVO2_HOME     180
#define SERVO2_FWD      90
#define SERVO2_BACK     260

// --- SERVO RAMP ---
#define SERVO_RAMP_INTERVAL_MS  20UL

// --- DCV PINS (active low) ---
#define DCV_KFS_PIN   46
#define DCV_SH_PIN    44

// --- PROXIMITY SENSOR (gripper toggle) ---
#define PROX_SENSOR_PIN  51
#define PROX_ACTIVE      HIGH

// --- SERIAL ---
#define SERIAL_BAUD         115200
#define SERIAL_TIMEOUT_MS   500

// ============================================================
//  STEPPER STRUCT (with decel support)
// ============================================================
struct Stepper {
  uint8_t  pulPin;
  uint8_t  dirPin;
  bool     running;
  bool     direction;
  uint32_t currentIntervalUs;
  uint32_t lastPulseUs;
  bool     pulseHigh;
  long     pulseCount;
  bool     decelerating;
};

Stepper lift1, lift2, armStep;

// ============================================================
//  HOMING STATE MACHINE
// ============================================================
enum HomingState {
  HOMING_IDLE,      // Not calibrated, waiting for command
  HOMING_UP,        // Moving both steppers UP by 1.5 rev
  HOMING_DOWN,      // Moving both steppers DOWN slowly until limit switches
  HOMING_ZERO,      // Both switches triggered, setting position to 0
  HOMING_SAFE_UP,   // Moving UP 1 rev to safe operating height
  HOMING_READY      // Calibrated and ready for normal operation
};

HomingState homingState = HOMING_IDLE;

// Homing pulse counters (separate from main pulseCount)
long homingPulseTarget1 = 0;
long homingPulseTarget2 = 0;
long homingPulseCount1  = 0;  // counts during homing phases
long homingPulseCount2  = 0;

bool lift1HomingDone = false;  // lift1 reached limit switch
bool lift2HomingDone = false;  // lift2 reached limit switch
bool lift1SafeDone   = false;  // lift1 finished safe-up move
bool lift2SafeDone   = false;  // lift2 finished safe-up move

// ============================================================
//  DRIVE MOTOR STRUCT
// ============================================================
struct DriveMotor {
  uint8_t pwmPin;
  uint8_t dirPin;
  int     targetSpeed;
  int     currentSpeed;
};

DriveMotor mLF, mRF, mLB, mRB;

// ============================================================
//  SERVO STATE
// ============================================================
Servo  servo1, servo2;
float  s1Current = 180.0f;
float  s2Current = (float)SERVO2_HOME;
int    s1Target  = 180;
int    s2Target  = SERVO2_HOME;
uint32_t lastServoRampMs = 0;

// ============================================================
//  PACKET STATE
// ============================================================
char     cmdBuffer[64];
uint8_t  cmdIndex  = 0;
uint32_t lastCmdMs = 0;
int      lastArmCmd = 0;
bool     proxDetected = false;
bool     proxOverride = false;
int      manualDcvSH  = 0;

// ============================================================
//  STEPPER: START / STOP / UPDATE
// ============================================================
void startStepper(Stepper &s, bool dir, uint32_t startUs) {
  if (s.running && s.direction == dir && !s.decelerating) return;
  s.running           = true;
  s.direction         = dir;
  s.decelerating      = false;
  s.currentIntervalUs = startUs;
  s.pulseHigh         = false;
  s.lastPulseUs       = micros();
  digitalWrite(s.dirPin, dir ? HIGH : LOW);
}

void stopStepper(Stepper &s) {
  s.running      = false;
  s.decelerating = false;
  digitalWrite(s.pulPin, LOW);
}

void decelerateStepper(Stepper &s) {
  if (s.running && !s.decelerating) {
    s.decelerating = true;
  }
}

void updateStepper(Stepper &s, uint32_t minUs, uint32_t accelUs, uint32_t decelUs) {
  if (!s.running) return;
  uint32_t now = micros();
  if ((now - s.lastPulseUs) >= (s.currentIntervalUs / 2)) {
    s.pulseHigh = !s.pulseHigh;
    digitalWrite(s.pulPin, s.pulseHigh ? HIGH : LOW);
    s.lastPulseUs = now;

    if (!s.pulseHigh) {
      s.pulseCount += s.direction ? 1L : -1L;

      if (s.decelerating) {
        s.currentIntervalUs += decelUs;
        if (s.currentIntervalUs >= 800UL) {
          stopStepper(s);
          return;
        }
      } else {
        if (s.currentIntervalUs > minUs) {
          s.currentIntervalUs = (s.currentIntervalUs - accelUs > minUs)
                                ? s.currentIntervalUs - accelUs : minUs;
        }
      }
    }
  }
}

// Lift helper: with position limit enforcement
void setLiftState(Stepper &s, bool shouldRun, bool dir) {
  if (shouldRun) {
    // SAFETY: Block downward movement if at or below home position (after calibration)
    if (homingState == HOMING_READY && !dir && s.pulseCount <= 0) {
      if (s.running) decelerateStepper(s);
      return;  // Do NOT allow downward movement past home
    }
    if (!s.running || s.direction != dir) startStepper(s, dir, LIFT_START_US);
    else s.decelerating = false;
  } else {
    if (s.running) decelerateStepper(s);
  }
}

// ============================================================
//  DRIVE: UPDATE
// ============================================================
void updateDriveMotor(DriveMotor &m) {
  if (m.currentSpeed < m.targetSpeed) {
    m.currentSpeed += DRIVE_RAMP;
    if (m.currentSpeed > m.targetSpeed) m.currentSpeed = m.targetSpeed;
  } else if (m.currentSpeed > m.targetSpeed) {
    m.currentSpeed -= DRIVE_RAMP;
    if (m.currentSpeed < m.targetSpeed) m.currentSpeed = m.targetSpeed;
  }
  if (m.currentSpeed >= 0) { digitalWrite(m.dirPin, DRIVE_FWD); analogWrite(m.pwmPin,  m.currentSpeed); }
  else                     { digitalWrite(m.dirPin, DRIVE_REV); analogWrite(m.pwmPin, -m.currentSpeed); }
}

void stopAllDriveImmediate() {
  mLF.targetSpeed = mLF.currentSpeed = 0;
  mRF.targetSpeed = mRF.currentSpeed = 0;
  mLB.targetSpeed = mLB.currentSpeed = 0;
  mRB.targetSpeed = mRB.currentSpeed = 0;
  analogWrite(mLF.pwmPin,0); analogWrite(mRF.pwmPin,0);
  analogWrite(mLB.pwmPin,0); analogWrite(mRB.pwmPin,0);
}

// ============================================================
//  SERVO RAMP
// ============================================================
void updateServoRamp() {
  uint32_t now = millis();
  if (now - lastServoRampMs < SERVO_RAMP_INTERVAL_MS) return;
  lastServoRampMs = now;

  if ((int)s1Current != s1Target) {
    s1Current += (s1Current < s1Target) ? 1.0f : -1.0f;
    s1Current  = constrain(s1Current, SERVO1_DEG_MIN, SERVO1_DEG_MAX);
    int pulse1 = map((int)s1Current, SERVO1_DEG_MIN, SERVO1_DEG_MAX, SERVO1_MIN_US, SERVO1_MAX_US);
    servo1.writeMicroseconds(pulse1);
  }

  if ((int)s2Current != s2Target) {
    s2Current += (s2Current < s2Target) ? 1.0f : -1.0f;
    s2Current  = constrain(s2Current, SERVO2_DEG_MIN, SERVO2_DEG_MAX);
    int pulse2 = map((int)s2Current, SERVO2_DEG_MIN, SERVO2_DEG_MAX, SERVO2_MIN_US, SERVO2_MAX_US);
    servo2.writeMicroseconds(pulse2);
  }
}

// ============================================================
//  HOMING STATE MACHINE
// ============================================================
void startHoming() {
  // Reset homing tracking
  lift1HomingDone = false;
  lift2HomingDone = false;
  lift1SafeDone   = false;
  lift2SafeDone   = false;
  homingPulseCount1 = 0;
  homingPulseCount2 = 0;

  // Phase 1: Move UP by 1.5 revolutions
  homingState = HOMING_UP;
  startStepper(lift1, true, HOMING_START_US);  // true = DIR_UP
  startStepper(lift2, true, HOMING_START_US);
}

void updateHoming() {
  switch (homingState) {

    case HOMING_UP: {
      // Count pulses for each stepper during upward homing
      // We track using pulseCount changes
      bool l1Done = (lift1.pulseCount >= (long)HOMING_UP_PULSES) || !lift1.running;
      bool l2Done = (lift2.pulseCount >= (long)HOMING_UP_PULSES) || !lift2.running;

      if (lift1.pulseCount >= (long)HOMING_UP_PULSES && lift1.running) {
        stopStepper(lift1);
      }
      if (lift2.pulseCount >= (long)HOMING_UP_PULSES && lift2.running) {
        stopStepper(lift2);
      }

      if (!lift1.running && !lift2.running) {
        // Both done moving up, now move down slowly
        homingState = HOMING_DOWN;
        lift1.pulseCount = 0;  // Reset for tracking
        lift2.pulseCount = 0;
        lift1HomingDone = false;
        lift2HomingDone = false;

        // Start moving DOWN slowly
        startStepper(lift1, false, HOMING_START_US);  // false = DIR_DOWN
        startStepper(lift2, false, HOMING_START_US);
      }
      break;
    }

    case HOMING_DOWN: {
      // Poll limit switches — each stepper stops independently
      bool ls1 = (digitalRead(LIFT1_LIMIT_PIN) == LIMIT_TRIGGERED);
      bool ls2 = (digitalRead(LIFT2_LIMIT_PIN) == LIMIT_TRIGGERED);

      if (ls1 && !lift1HomingDone) {
        stopStepper(lift1);
        lift1HomingDone = true;
      }
      if (ls2 && !lift2HomingDone) {
        stopStepper(lift2);
        lift2HomingDone = true;
      }

      // Both switches triggered → transition to ZERO
      if (lift1HomingDone && lift2HomingDone) {
        homingState = HOMING_ZERO;
      }
      break;
    }

    case HOMING_ZERO: {
      // Set absolute home position
      lift1.pulseCount = 0;
      lift2.pulseCount = 0;

      // Now move UP 1 revolution to safe operating height
      homingState = HOMING_SAFE_UP;
      lift1SafeDone = false;
      lift2SafeDone = false;

      startStepper(lift1, true, HOMING_START_US);  // true = DIR_UP
      startStepper(lift2, true, HOMING_START_US);
      break;
    }

    case HOMING_SAFE_UP: {
      // Move up exactly 1 revolution (800 pulses)
      if (lift1.pulseCount >= (long)HOMING_SAFE_PULSES && lift1.running) {
        stopStepper(lift1);
        lift1SafeDone = true;
      }
      if (lift2.pulseCount >= (long)HOMING_SAFE_PULSES && lift2.running) {
        stopStepper(lift2);
        lift2SafeDone = true;
      }

      if (!lift1.running && !lift2.running) {
        // Homing complete — system is calibrated
        homingState = HOMING_READY;
      }
      break;
    }

    case HOMING_READY:
    case HOMING_IDLE:
    default:
      // Nothing to do
      break;
  }
}

// ============================================================
//  REAL-TIME LIMIT SWITCH SAFETY CHECK
// ============================================================
// Even during normal operation, if a limit switch triggers while
// a stepper is moving down, immediately stop that stepper.
void checkLimitSwitchSafety() {
  if (homingState == HOMING_DOWN || homingState == HOMING_UP ||
      homingState == HOMING_ZERO || homingState == HOMING_SAFE_UP) {
    return;  // Homing state machine handles this
  }

  // During normal operation: if moving DOWN and limit switch triggers, stop
  if (lift1.running && !lift1.direction) {  // direction false = DOWN
    if (digitalRead(LIFT1_LIMIT_PIN) == LIMIT_TRIGGERED) {
      stopStepper(lift1);
      lift1.pulseCount = 0;  // Re-zero at the switch
    }
  }
  if (lift2.running && !lift2.direction) {
    if (digitalRead(LIFT2_LIMIT_PIN) == LIMIT_TRIGGERED) {
      stopStepper(lift2);
      lift2.pulseCount = 0;
    }
  }
}

// ============================================================
//  LIFT COMMAND PARSER
// ============================================================
void parseLiftCmd(char cmd) {
  // If homing is in progress, ignore manual lift commands
  if (homingState == HOMING_UP || homingState == HOMING_DOWN ||
      homingState == HOMING_ZERO || homingState == HOMING_SAFE_UP) {
    return;
  }

  switch (cmd) {
    case 'C':  // Calibrate / Home
      startHoming();
      break;
    case 'N': setLiftState(lift1,true,true);  setLiftState(lift2,true,true);  break;
    case 'M': setLiftState(lift1,true,false); setLiftState(lift2,true,false); break;
    case 'H': setLiftState(lift1,true,true);  setLiftState(lift2,false,false);break;
    case 'J': setLiftState(lift1,true,false); setLiftState(lift2,false,false);break;
    case 'K': setLiftState(lift2,true,true);  setLiftState(lift1,false,false);break;
    case 'L': setLiftState(lift2,true,false); setLiftState(lift1,false,false);break;
    default:  setLiftState(lift1,false,false);setLiftState(lift2,false,false);break;
  }
}

// ============================================================
//  PARSE FULL PACKET
// ============================================================
void parsePacket(char *pkt) {
  char *tok[10];
  uint8_t n = 0;
  char *p = pkt;
  tok[n++] = p;
  while (*p && n < 10) { if (*p == ',') { *p='\0'; tok[n++]=p+1; } p++; }
  if (n < 10) return;

  // Drive
  auto clamp = [](long v) -> int { return (int)(v>255?255:(v<-255?-255:v)); };
  mLF.targetSpeed = clamp(atol(tok[0]));
  mRF.targetSpeed = clamp(atol(tok[1]));
  mLB.targetSpeed = clamp(atol(tok[2]));
  mRB.targetSpeed = clamp(atol(tok[3]));

  // Lift
  parseLiftCmd(tok[4][0]);

  // Servo targets
  s1Target = constrain(atoi(tok[5]), SERVO1_DEG_MIN, SERVO1_DEG_MAX);
  s2Target = constrain(atoi(tok[6]), SERVO2_DEG_MIN, SERVO2_DEG_MAX);

  // Arm stepper with decel on stop
  int arm = atoi(tok[7]);
  lastArmCmd = arm;
  if (arm == 1) {
    startStepper(armStep, ARM_EXTEND,  ARM_START_US);
  } else if (arm == 2) {
    startStepper(armStep, ARM_RETRACT, ARM_START_US);
  } else {
    if (armStep.running) decelerateStepper(armStep);
  }

  // DCVs (active low)
  digitalWrite(DCV_KFS_PIN, atoi(tok[8]) == 1 ? LOW : HIGH);

  // DCV_SH: track manual command; actual pin write in loop()
  manualDcvSH = atoi(tok[9]);

  if (manualDcvSH == 0 && proxDetected) {
    proxOverride = true;
  }
  if (manualDcvSH == 1) {
    proxOverride = false;
  }
}

// ============================================================
//  FAILSAFE
// ============================================================
void checkFailsafe() {
  if ((millis() - lastCmdMs) > SERIAL_TIMEOUT_MS) {
    decelerateStepper(lift1);
    decelerateStepper(lift2);
    decelerateStepper(armStep);
    mLF.targetSpeed = mRF.targetSpeed = mLB.targetSpeed = mRB.targetSpeed = 0;
  }
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
  // Drive
  mLF.pwmPin=LF_PWM_PIN; mLF.dirPin=LF_DIR_PIN;
  mRF.pwmPin=RF_PWM_PIN; mRF.dirPin=RF_DIR_PIN;
  mLB.pwmPin=LB_PWM_PIN; mLB.dirPin=LB_DIR_PIN;
  mRB.pwmPin=RB_PWM_PIN; mRB.dirPin=RB_DIR_PIN;
  pinMode(LF_PWM_PIN,OUTPUT); pinMode(LF_DIR_PIN,OUTPUT);
  pinMode(RF_PWM_PIN,OUTPUT); pinMode(RF_DIR_PIN,OUTPUT);
  pinMode(LB_PWM_PIN,OUTPUT); pinMode(LB_DIR_PIN,OUTPUT);
  pinMode(RB_PWM_PIN,OUTPUT); pinMode(RB_DIR_PIN,OUTPUT);
  stopAllDriveImmediate();

  // Lift1
  lift1={LIFT1_PUL,LIFT1_DIR_PIN,false,true,LIFT_START_US,0,false,0L,false};
  stopStepper(lift1);
  pinMode(LIFT1_PUL,OUTPUT); pinMode(LIFT1_DIR_PIN,OUTPUT);

  // Lift2
  lift2={LIFT2_PUL,LIFT2_DIR_PIN,false,true,LIFT_START_US,0,false,0L,false};
  stopStepper(lift2);
  pinMode(LIFT2_PUL,OUTPUT); pinMode(LIFT2_DIR_PIN,OUTPUT);

  // Limit switches (NC, INPUT_PULLUP)
  pinMode(LIFT1_LIMIT_PIN, INPUT_PULLUP);
  pinMode(LIFT2_LIMIT_PIN, INPUT_PULLUP);

  // Arm stepper
  armStep={ARM_PUL_PIN,ARM_DIR_PIN,false,true,ARM_START_US,0,false,0L,false};
  stopStepper(armStep);
  pinMode(ARM_PUL_PIN,OUTPUT); pinMode(ARM_DIR_PIN,OUTPUT);

  // Servos
  servo1.writeMicroseconds(map((int)s1Current, SERVO1_DEG_MIN, SERVO1_DEG_MAX, SERVO1_MIN_US, SERVO1_MAX_US));
  servo1.attach(SERVO1_PIN, SERVO1_MIN_US, SERVO1_MAX_US);
  servo2.writeMicroseconds(map((int)s2Current, SERVO2_DEG_MIN, SERVO2_DEG_MAX, SERVO2_MIN_US, SERVO2_MAX_US));
  servo2.attach(SERVO2_PIN, SERVO2_MIN_US, SERVO2_MAX_US);

  // DCVs
  pinMode(DCV_KFS_PIN,OUTPUT); digitalWrite(DCV_KFS_PIN, HIGH);
  pinMode(DCV_SH_PIN, OUTPUT); digitalWrite(DCV_SH_PIN,  HIGH);

  // Proximity sensor
  pinMode(PROX_SENSOR_PIN, INPUT);

  Serial.begin(SERIAL_BAUD);
  lastCmdMs = millis();
  lastServoRampMs = millis();

  // Start in IDLE — user must press 'H' in Python to begin homing
  homingState = HOMING_IDLE;
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
  // Serial
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdIndex > 0) {
        cmdBuffer[cmdIndex] = '\0';
        lastCmdMs = millis();
        parsePacket(cmdBuffer);
        cmdIndex = 0;
      }
    } else {
      if (cmdIndex < 63) cmdBuffer[cmdIndex++] = c;
    }
  }

  // Homing state machine update
  updateHoming();

  // Real-time limit switch safety (even outside homing)
  checkLimitSwitchSafety();

  // Determine correct accel/decel profiles depending on if we are homing
  bool isHoming = (homingState != HOMING_IDLE && homingState != HOMING_READY);
  uint32_t minUs   = isHoming ? HOMING_SLOW_US  : LIFT_MIN_US;
  uint32_t accelUs = isHoming ? HOMING_ACCEL_US : LIFT_ACCEL_US;
  uint32_t decelUs = isHoming ? HOMING_DECEL_US : LIFT_DECEL_US;

  // Stepper updates
  updateStepper(lift1, minUs, accelUs, decelUs);
  updateStepper(lift2, minUs, accelUs, decelUs);
  updateStepper(armStep,ARM_MIN_US,  ARM_ACCEL_US,  ARM_DECEL_US);

  // Drive
  updateDriveMotor(mLF);
  updateDriveMotor(mRF);
  updateDriveMotor(mLB);
  updateDriveMotor(mRB);

  // Servos
  updateServoRamp();

  // Failsafe
  checkFailsafe();

  // Proximity sensor: level-based auto-grip
  proxDetected = (digitalRead(PROX_SENSOR_PIN) == PROX_ACTIVE);
  if (!proxDetected) {
    proxOverride = false;
  }

  bool shouldGrip = false;
  if (manualDcvSH == 1) {
    shouldGrip = true;
  } else if (proxDetected && !proxOverride) {
    shouldGrip = true;
  }
  digitalWrite(DCV_SH_PIN, shouldGrip ? LOW : HIGH);

  // Feedback every 250ms
  static uint32_t lastFbMs = 0;
  if (millis() - lastFbMs >= 250) {
    lastFbMs = millis();

    // Homing state string
    const char* homStr;
    switch (homingState) {
      case HOMING_IDLE:    homStr = "IDLE";    break;
      case HOMING_UP:      homStr = "H_UP";    break;
      case HOMING_DOWN:    homStr = "H_DN";    break;
      case HOMING_ZERO:    homStr = "H_ZRO";   break;
      case HOMING_SAFE_UP: homStr = "H_SAFE";  break;
      case HOMING_READY:   homStr = "READY";   break;
      default:             homStr = "???";      break;
    }

    // Limit switch states
    bool ls1 = (digitalRead(LIFT1_LIMIT_PIN) == LIMIT_TRIGGERED);
    bool ls2 = (digitalRead(LIFT2_LIMIT_PIN) == LIMIT_TRIGGERED);

    char fb[120];
    snprintf(fb, sizeof(fb),
      "HOM:%s L1:%s P1:%ld L2:%s P2:%ld LS1:%s LS2:%s ARM:%s PA:%ld S1:%d S2:%d KFS:%s SH:%s PX:%s",
      homStr,
      lift1.running  ? (lift1.direction   ? "UP"  : "DN") : "ST",
      lift1.pulseCount,
      lift2.running  ? (lift2.direction   ? "UP"  : "DN") : "ST",
      lift2.pulseCount,
      ls1 ? "TRG" : "OK",
      ls2 ? "TRG" : "OK",
      armStep.running? (armStep.decelerating? "DCL": (armStep.direction? "EXT":"RET")) : "ST",
      armStep.pulseCount,
      (int)s1Current,
      (int)s2Current,
      digitalRead(DCV_KFS_PIN) == LOW ? "CLS" : "OPN",
      digitalRead(DCV_SH_PIN)  == LOW ? "CLS" : "OPN",
      proxDetected ? "DET" : "CLR"
    );
    Serial.println(fb);
  }
}
