// ============================================================
//  R2 - Full Manual Control  v2
//  Date: June 2026
//
//  Changes from v1:
//    - Servo ramp reduced to 1 deg/loop (smoother, less vibration)
//    - Servo ramp uses non-blocking timer (every 20ms = 50 deg/sec)
//      instead of every loop() -- prevents jitter from loop speed variation
//    - Arm stepper has full accel + DECEL ramp (trapezoidal)
//      decel triggers when key is released, not instant stop
//    - Servo2 pulse range: MIN=800us MAX=2200us (calibrated 14 June 2026)
//
//  PACKET FORMAT (10 fields, CSV, newline terminated):
//  "LF,RF,LB,RB,LIFT,S1,S2,ARM,DCV_KFS,DCV_SH\n"
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
#define LIFT_MIN_US   150UL
#define LIFT_ACCEL_US 4UL

// --- ARM STEPPER ---
#define ARM_PUL_PIN   7
#define ARM_DIR_PIN   53
#define ARM_EXTEND    true
#define ARM_RETRACT   false
#define ARM_START_US  1000UL   // slow start
#define ARM_MIN_US    500UL   // max speed
#define ARM_ACCEL_US  6UL     // ramp rate (accel)
#define ARM_DECEL_US  8UL     // ramp rate (decel -- slightly faster decel)

// --- SERVO1 (spearhead gripper arm, pin 6, 180deg) ---
#define SERVO1_PIN      6
#define SERVO1_MIN_US   500
#define SERVO1_MAX_US   2500
#define SERVO1_DEG_MIN  0
#define SERVO1_DEG_MAX  180

// --- SERVO2 (KFS gripper arm, pin 12, 270deg) ---
#define SERVO2_PIN      12
#define SERVO2_MIN_US   500    // calibrated 14 June 2026
#define SERVO2_MAX_US   2500   // calibrated 14 June 2026
#define SERVO2_DEG_MIN  0
#define SERVO2_DEG_MAX  270
#define SERVO2_HOME     180
#define SERVO2_FWD      90
#define SERVO2_BACK     260

// --- SERVO RAMP ---
// Servos update every SERVO_RAMP_INTERVAL_MS milliseconds by 1 degree.
// 20ms interval = 50 deg/sec (smooth, no vibration from loop speed jitter)
#define SERVO_RAMP_INTERVAL_MS  20UL   // ms between each 1-degree step

// --- DCV PINS (active low) ---
#define DCV_KFS_PIN   46
#define DCV_SH_PIN    44

// --- PROXIMITY SENSOR (gripper toggle) ---
#define PROX_SENSOR_PIN  51   // signal pin of proximity sensor
#define PROX_ACTIVE      HIGH // HIGH = object detected

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
  bool     decelerating;   // true = ramping down toward stop
};

Stepper lift1, lift2, armStep;

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
int      lastArmCmd = 0;  // 0=stop, 1=extend, 2=retract
bool     proxDetected = false;   // current proximity sensor reading
bool     proxOverride = false;   // true = manual ungrip suppresses auto-grip
int      manualDcvSH  = 0;       // last manual DCV_SH command (0=open, 1=close)

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

// Initiate decel ramp instead of instant stop
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
        // Ramp interval UP (slow down)
        s.currentIntervalUs += decelUs;
        if (s.currentIntervalUs >= 800UL) {
          // Reached slow enough to stop cleanly
          stopStepper(s);
          return;
        }
      } else {
        // Normal accel ramp DOWN (speed up)
        if (s.currentIntervalUs > minUs) {
          s.currentIntervalUs = (s.currentIntervalUs - accelUs > minUs)
                                ? s.currentIntervalUs - accelUs : minUs;
        }
      }
    }
  }
}

// Lift helper: only restart if direction changes, preserves ramp position
void setLiftState(Stepper &s, bool shouldRun, bool dir) {
  if (shouldRun) {
    if (!s.running || s.direction != dir) startStepper(s, dir, LIFT_START_US);
    else s.decelerating = false; // cancel any pending decel
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
//  SERVO RAMP -- non-blocking, timer-based 1 deg per 20ms
// ============================================================
void updateServoRamp() {
  uint32_t now = millis();
  if (now - lastServoRampMs < SERVO_RAMP_INTERVAL_MS) return;
  lastServoRampMs = now;

  // Servo1
  if ((int)s1Current != s1Target) {
    s1Current += (s1Current < s1Target) ? 1.0f : -1.0f;
    s1Current  = constrain(s1Current, SERVO1_DEG_MIN, SERVO1_DEG_MAX);
    int pulse1 = map((int)s1Current, SERVO1_DEG_MIN, SERVO1_DEG_MAX, SERVO1_MIN_US, SERVO1_MAX_US);
    servo1.writeMicroseconds(pulse1);
  }

  // Servo2
  if ((int)s2Current != s2Target) {
    s2Current += (s2Current < s2Target) ? 1.0f : -1.0f;
    s2Current  = constrain(s2Current, SERVO2_DEG_MIN, SERVO2_DEG_MAX);
    int pulse2 = map((int)s2Current, SERVO2_DEG_MIN, SERVO2_DEG_MAX, SERVO2_MIN_US, SERVO2_MAX_US);
    servo2.writeMicroseconds(pulse2);
  }
}

// ============================================================
//  LIFT COMMAND PARSER
// ============================================================
void parseLiftCmd(char cmd) {
  switch (cmd) {
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
    // Key released -- decelerate instead of instant stop
    if (armStep.running) decelerateStepper(armStep);
  }

  // DCVs (active low)
  digitalWrite(DCV_KFS_PIN, atoi(tok[8]) == 1 ? LOW : HIGH);

  // DCV_SH: only track the manual command here; actual pin write is in loop()
  manualDcvSH = atoi(tok[9]);

  // If user manually opens gripper while sensor still sees object, latch override
  if (manualDcvSH == 0 && proxDetected) {
    proxOverride = true;
  }
  // If user manually closes gripper, clear override (they want it gripped)
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

  // Updates
  updateStepper(lift1,  LIFT_MIN_US, LIFT_ACCEL_US, LIFT_ACCEL_US);
  updateStepper(lift2,  LIFT_MIN_US, LIFT_ACCEL_US, LIFT_ACCEL_US);
  updateStepper(armStep,ARM_MIN_US,  ARM_ACCEL_US,  ARM_DECEL_US);
  updateDriveMotor(mLF);
  updateDriveMotor(mRF);
  updateDriveMotor(mLB);
  updateDriveMotor(mRB);
  updateServoRamp();
  checkFailsafe();

  // --- Proximity sensor: level-based auto-grip ---
  proxDetected = (digitalRead(PROX_SENSOR_PIN) == PROX_ACTIVE);

  // Clear override latch once object leaves the sensor
  if (!proxDetected) {
    proxOverride = false;
  }

  // Decide final gripper state:
  //   1) Manual grip command (manualDcvSH==1) → always grip
  //   2) Proximity detects AND no manual override latch → auto-grip
  //   3) Otherwise → open
  bool shouldGrip = false;
  if (manualDcvSH == 1) {
    shouldGrip = true;                        // manual says grip
  } else if (proxDetected && !proxOverride) {
    shouldGrip = true;                        // auto-grip from sensor
  }
  digitalWrite(DCV_SH_PIN, shouldGrip ? LOW : HIGH);

  // Feedback every 250ms (single buffer write to minimise TX interrupts)
  static uint32_t lastFbMs = 0;
  if (millis() - lastFbMs >= 250) {
    lastFbMs = millis();
    char fb[100];
    snprintf(fb, sizeof(fb),
      "L1:%s P1:%ld L2:%s P2:%ld ARM:%s PA:%ld S1:%d S2:%d KFS:%s SH:%s PX:%s",
      lift1.running  ? (lift1.direction   ? "UP"  : "DN") : "ST",
      lift1.pulseCount,
      lift2.running  ? (lift2.direction   ? "UP"  : "DN") : "ST",
      lift2.pulseCount,
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
