// ============================================================
// R2 Robot — Arduino Mega
// Drive: Mecanum (PWM+DIR)
// Steppers: Front (DIR=36, PUL=37), Rear (DIR=10, PUL=11)
//           Toggle (DIR=53, PUL=7)
// Servo:    Servo1 (pin 6)  — toggles 180°/90°
//           Servo2 (pin 12) — 3 states: i1=270°, i2=180°, i3=90°
// Pneumatic: DCV_SH (pin 46, active LOW) — toggles open/close
//
// Homing (command 'h'):
//   1. Both steppers move UP by HOMING_CLEAR_PULSES (clears switches)
//   2. Both steppers creep DOWN slowly; each stops independently
//      when its limit switch triggers, waits for the other
//   3. Both pulseCounts zeroed (home position)
//   4. Both steppers move UP by HOMING_BUMP_PULSES (releases switches)
//   Prints "HOMING_DONE" when complete.
//
// Commands:
//   f[mm]        → forward
//   b[mm]        → backward
//   l[mm]        → strafe left
//   r[mm]        → strafe right
//   e[deg]       → rotate CW
//   q[deg]       → rotate CCW
//   s            → stop drive
//   h            → start homing
//   fu/fd[pulses]→ front stepper up/down
//   ru/rd[pulses]→ rear stepper up/down
//   au/ad[pulses]→ both steppers up/down (ad stops each independently on limit switch)
//   g[pulses]    → toggle stepper FORWARD by pulses
//   j[pulses]    → toggle stepper BACKWARD by pulses
//   v            → toggle servo1 (100° ↔ 10°)
//   i1/i2/i3     → servo2: i1=95°, i2=185°, i3=270°
//   k            → toggle pneumatic 2 DCV pin 44 (open ↔ close)
//   pneumatic 1 (pin 46) controlled automatically by IR sensor pin 51
//   IR pin 15 reserved (unused)
// ============================================================

#include <Servo.h>

// ── Drive pins ───────────────────────────────────────────────
#define LF_PWM_PIN  8
#define LF_DIR_PIN  39
#define RF_PWM_PIN  9
#define RF_DIR_PIN  38
#define LB_PWM_PIN  4
#define LB_DIR_PIN  41
#define RB_PWM_PIN  5
#define RB_DIR_PIN  40
bool isPneumaticDetected = false;
// ── Stepper pins ─────────────────────────────────────────────
#define FRONT_DIR_PIN   36
#define FRONT_PUL_PIN   37
#define REAR_DIR_PIN    10
#define REAR_PUL_PIN    11
#define TOGGLE_DIR_PIN  53
#define TOGGLE_PUL_PIN  7

// ── Limit switch pins (NC, INPUT_PULLUP) ─────────────────────
// Wiring: Pin → NC switch → GND
//   LOW  = switch closed (normal)
//   HIGH = switch triggered OR wire broken (fail-safe)
#define FRONT_LIMIT_PIN   47
#define REAR_LIMIT_PIN    45
#define LIMIT_TRIGGERED   HIGH

// ── Servo pin ────────────────────────────────────────────────
#define SERVO1_PIN  6
#define SERVO2_PIN  12

// ── Servo2 270° pulse width range ────────────────────────────
#define SERVO2_MIN_US  500    // pulse width at 0°
#define SERVO2_MAX_US  2500   // pulse width at 270°

// ── Pneumatic DCV pins (active LOW) ──────────────────────────
#define DCV_SH_PIN   46   // pneumatic 1 — controlled by IR sensor pin 51
#define DCV_SH2_PIN  44   // pneumatic 2 — command: k

// ── IR sensor pins ───────────────────────────────────────────
#define IR_51_PIN  51     // controls pneumatic 1: LOW=close, HIGH=open
#define IR_15_PIN  50     // unused (reserved)

// ── Drive config ─────────────────────────────────────────────
#define SPEED           50
#define MS_PER_M        3125
#define MS_PER_M_STRAFE 3255
#define MS_PER_DEG      28

// ── Main stepper config (front, rear, tu/td) ─────────────────
#define START_PPS  200
#define MAX_PPS    10000
#define ACCEL      300
#define DECEL      300
#define PULSE_US   10

// ── Toggle stepper config (g/j commands) ─────────────────────
// Tune these independently from the main stepper profile
#define TOGGLE_START_PPS  200
#define TOGGLE_MAX_PPS    5000
#define TOGGLE_ACCEL      200
#define TOGGLE_DECEL      200
#define TOGGLE_PULSE_US   10

// ── Homing config ────────────────────────────────────────────
#define HOMING_CLEAR_PULSES  400UL
#define HOMING_BUMP_PULSES   150UL
#define HOMING_DOWN_US       2500UL
#define HOMING_MOVE_US       1200UL

// ── Servo state ──────────────────────────────────────────────
// Servo1: 2-state toggle — POS_A=100°, POS_B=10°, default=100°
#define SERVO1_POS_A  100
#define SERVO1_POS_B  13
Servo servo1;
bool servo1_at_A = true;   // true = POS_A (100°), false = POS_B (10°)

// Servo2: 3-state — i1=95°, i2=185°, i3=270°, default=185°
// 270° servo uses writeMicroseconds(); map 0–270° → SERVO2_MIN_US–SERVO2_MAX_US
#define SERVO2_POS_1  95
#define SERVO2_POS_2  185
#define SERVO2_POS_3  270
Servo servo2;
int servo2_pos = SERVO2_POS_2;   // default 185°

// Helper: convert 0–270° angle to pulse width in microseconds
inline int servo2AngleToUs(int angle) {
  return map(angle, 0, 270, SERVO2_MIN_US, SERVO2_MAX_US);
}

// ── Pneumatic state ──────────────────────────────────────────
bool dcv_sh2_state = false;   // pneumatic 2 (pin 44)

// ============================================================
// Drive functions
// ============================================================
void stopAll() {
  analogWrite(LF_PWM_PIN, 0);
  analogWrite(RF_PWM_PIN, 0);
  analogWrite(LB_PWM_PIN, 0);
  analogWrite(RB_PWM_PIN, 0);
}

void runFor(int lf, int rf, int lb, int rb, unsigned long ms) {
  digitalWrite(LF_DIR_PIN, lf >= 0 ? HIGH : LOW);
  digitalWrite(RF_DIR_PIN, rf >= 0 ? HIGH : LOW);
  digitalWrite(LB_DIR_PIN, lb >= 0 ? HIGH : LOW);
  digitalWrite(RB_DIR_PIN, rb >= 0 ? HIGH : LOW);
  delay(10);
  analogWrite(LF_PWM_PIN, abs(lf));
  analogWrite(RF_PWM_PIN, abs(rf));
  analogWrite(LB_PWM_PIN, abs(lb));
  analogWrite(RB_PWM_PIN, abs(rb));
  delay(ms);
  stopAll();
}

// ============================================================
// stepMotor — generic single stepper (main speed profile)
// Used by fu/fd, ru/rd, tu/td
// ============================================================
void stepMotor(int pulPin, int dirPin, bool dirUp, long pulses) {
  digitalWrite(dirPin, dirUp ? HIGH : LOW);
  delayMicroseconds(10);

  int accelSteps = (MAX_PPS - START_PPS) / ACCEL;
  int decelSteps = (MAX_PPS - START_PPS) / DECEL;

  if (accelSteps + decelSteps > pulses) {
    accelSteps = pulses / 2;
    decelSteps = pulses - accelSteps;
  }

  long cruisePulses = pulses - accelSteps - decelSteps;
  int pps = START_PPS;

  // Accel
  for (int i = 0; i < accelSteps; i++) {
    unsigned long period = 1000000UL / pps;
    digitalWrite(pulPin, HIGH); delayMicroseconds(PULSE_US);
    digitalWrite(pulPin, LOW);  delayMicroseconds(period - PULSE_US);
    pps += ACCEL;
    if (pps > MAX_PPS) pps = MAX_PPS;
  }

  // Cruise
  unsigned long cruisePeriod = 1000000UL / MAX_PPS;
  for (long i = 0; i < cruisePulses; i++) {
    digitalWrite(pulPin, HIGH); delayMicroseconds(PULSE_US);
    digitalWrite(pulPin, LOW);  delayMicroseconds(cruisePeriod - PULSE_US);
  }

  // Decel
  pps = MAX_PPS;
  for (int i = 0; i < decelSteps; i++) {
    pps -= DECEL;
    if (pps < START_PPS) pps = START_PPS;
    unsigned long period = 1000000UL / pps;
    digitalWrite(pulPin, HIGH); delayMicroseconds(PULSE_US);
    digitalWrite(pulPin, LOW);  delayMicroseconds(period - PULSE_US);
  }
}

// ============================================================
// stepToggle — toggle stepper only (g/j commands)
// Uses its own separate speed profile (TOGGLE_*)
// dirFwd: true = forward, false = backward
// ============================================================
void stepToggle(bool dirFwd, long pulses) {
  digitalWrite(TOGGLE_DIR_PIN, dirFwd ? HIGH : LOW);
  delayMicroseconds(10);

  int accelSteps = (TOGGLE_MAX_PPS - TOGGLE_START_PPS) / TOGGLE_ACCEL;
  int decelSteps = (TOGGLE_MAX_PPS - TOGGLE_START_PPS) / TOGGLE_DECEL;

  if (accelSteps + decelSteps > pulses) {
    accelSteps = pulses / 2;
    decelSteps = pulses - accelSteps;
  }

  long cruisePulses = pulses - accelSteps - decelSteps;
  int pps = TOGGLE_START_PPS;

  // Accel
  for (int i = 0; i < accelSteps; i++) {
    unsigned long period = 1000000UL / pps;
    digitalWrite(TOGGLE_PUL_PIN, HIGH); delayMicroseconds(TOGGLE_PULSE_US);
    digitalWrite(TOGGLE_PUL_PIN, LOW);  delayMicroseconds(period - TOGGLE_PULSE_US);
    pps += TOGGLE_ACCEL;
    if (pps > TOGGLE_MAX_PPS) pps = TOGGLE_MAX_PPS;
  }

  // Cruise
  unsigned long cruisePeriod = 1000000UL / TOGGLE_MAX_PPS;
  for (long i = 0; i < cruisePulses; i++) {
    digitalWrite(TOGGLE_PUL_PIN, HIGH); delayMicroseconds(TOGGLE_PULSE_US);
    digitalWrite(TOGGLE_PUL_PIN, LOW);  delayMicroseconds(cruisePeriod - TOGGLE_PULSE_US);
  }

  // Decel
  pps = TOGGLE_MAX_PPS;
  for (int i = 0; i < decelSteps; i++) {
    pps -= TOGGLE_DECEL;
    if (pps < TOGGLE_START_PPS) pps = TOGGLE_START_PPS;
    unsigned long period = 1000000UL / pps;
    digitalWrite(TOGGLE_PUL_PIN, HIGH); delayMicroseconds(TOGGLE_PULSE_US);
    digitalWrite(TOGGLE_PUL_PIN, LOW);  delayMicroseconds(period - TOGGLE_PULSE_US);
  }
}

// ============================================================
// stepBoth — both front+rear steppers (au/ad command)
//
// Going UP  : normal blocking, no switch check
// Going DOWN: each stepper stops independently when its
//             limit switch triggers; the other keeps going
//             until it hits its switch or exhausts pulse count
// ============================================================
void stepBoth(bool dirUp, long pulses) {
  digitalWrite(FRONT_DIR_PIN, dirUp ? HIGH : LOW);
  digitalWrite(REAR_DIR_PIN,  dirUp ? HIGH : LOW);
  delayMicroseconds(10);

  int accelSteps = (MAX_PPS - START_PPS) / ACCEL;
  int decelSteps = (MAX_PPS - START_PPS) / DECEL;

  if (accelSteps + decelSteps > pulses) {
    accelSteps = pulses / 2;
    decelSteps = pulses - accelSteps;
  }

  long cruisePulses = pulses - accelSteps - decelSteps;
  int pps = START_PPS;

  // ── Going UP: no switch check ─────────────────────────────
  if (dirUp) {

    // Accel
    for (int i = 0; i < accelSteps; i++) {
      unsigned long period = 1000000UL / pps;
      digitalWrite(FRONT_PUL_PIN, HIGH); digitalWrite(REAR_PUL_PIN, HIGH);
      delayMicroseconds(PULSE_US);
      digitalWrite(FRONT_PUL_PIN, LOW);  digitalWrite(REAR_PUL_PIN, LOW);
      delayMicroseconds(period - PULSE_US);
      pps += ACCEL;
      if (pps > MAX_PPS) pps = MAX_PPS;
    }

    // Cruise
    unsigned long cruisePeriod = 1000000UL / MAX_PPS;
    for (long i = 0; i < cruisePulses; i++) {
      digitalWrite(FRONT_PUL_PIN, HIGH); digitalWrite(REAR_PUL_PIN, HIGH);
      delayMicroseconds(PULSE_US);
      digitalWrite(FRONT_PUL_PIN, LOW);  digitalWrite(REAR_PUL_PIN, LOW);
      delayMicroseconds(cruisePeriod - PULSE_US);
    }

    // Decel
    pps = MAX_PPS;
    for (int i = 0; i < decelSteps; i++) {
      pps -= DECEL;
      if (pps < START_PPS) pps = START_PPS;
      unsigned long period = 1000000UL / pps;
      digitalWrite(FRONT_PUL_PIN, HIGH); digitalWrite(REAR_PUL_PIN, HIGH);
      delayMicroseconds(PULSE_US);
      digitalWrite(FRONT_PUL_PIN, LOW);  digitalWrite(REAR_PUL_PIN, LOW);
      delayMicroseconds(period - PULSE_US);
    }

  // ── Going DOWN: independent limit switch stop ──────────────
  } else {

    bool frontDone = false;
    bool rearDone  = false;

    // Accel
    for (int i = 0; i < accelSteps; i++) {
      if (frontDone && rearDone) break;
      unsigned long period = 1000000UL / pps;
      if (!frontDone) digitalWrite(FRONT_PUL_PIN, HIGH);
      if (!rearDone)  digitalWrite(REAR_PUL_PIN,  HIGH);
      delayMicroseconds(PULSE_US);
      if (!frontDone) digitalWrite(FRONT_PUL_PIN, LOW);
      if (!rearDone)  digitalWrite(REAR_PUL_PIN,  LOW);
      delayMicroseconds(period - PULSE_US);
      if (!frontDone && digitalRead(FRONT_LIMIT_PIN) == LIMIT_TRIGGERED) {
        frontDone = true;
        digitalWrite(FRONT_PUL_PIN, LOW);
        Serial.println("LIMIT: front hit (accel)");
      }
      if (!rearDone && digitalRead(REAR_LIMIT_PIN) == LIMIT_TRIGGERED) {
        rearDone = true;
        digitalWrite(REAR_PUL_PIN, LOW);
        Serial.println("LIMIT: rear hit (accel)");
      }
      pps += ACCEL;
      if (pps > MAX_PPS) pps = MAX_PPS;
    }

    // Cruise
    unsigned long cruisePeriod = 1000000UL / MAX_PPS;
    for (long i = 0; i < cruisePulses; i++) {
      if (frontDone && rearDone) break;
      if (!frontDone) digitalWrite(FRONT_PUL_PIN, HIGH);
      if (!rearDone)  digitalWrite(REAR_PUL_PIN,  HIGH);
      delayMicroseconds(PULSE_US);
      if (!frontDone) digitalWrite(FRONT_PUL_PIN, LOW);
      if (!rearDone)  digitalWrite(REAR_PUL_PIN,  LOW);
      delayMicroseconds(cruisePeriod - PULSE_US);
      if (!frontDone && digitalRead(FRONT_LIMIT_PIN) == LIMIT_TRIGGERED) {
        frontDone = true;
        digitalWrite(FRONT_PUL_PIN, LOW);
        Serial.println("LIMIT: front hit (cruise)");
      }
      if (!rearDone && digitalRead(REAR_LIMIT_PIN) == LIMIT_TRIGGERED) {
        rearDone = true;
        digitalWrite(REAR_PUL_PIN, LOW);
        Serial.println("LIMIT: rear hit (cruise)");
      }
    }

    // Decel
    pps = MAX_PPS;
    for (int i = 0; i < decelSteps; i++) {
      if (frontDone && rearDone) break;
      pps -= DECEL;
      if (pps < START_PPS) pps = START_PPS;
      unsigned long period = 1000000UL / pps;
      if (!frontDone) digitalWrite(FRONT_PUL_PIN, HIGH);
      if (!rearDone)  digitalWrite(REAR_PUL_PIN,  HIGH);
      delayMicroseconds(PULSE_US);
      if (!frontDone) digitalWrite(FRONT_PUL_PIN, LOW);
      if (!rearDone)  digitalWrite(REAR_PUL_PIN,  LOW);
      delayMicroseconds(period - PULSE_US);
      if (!frontDone && digitalRead(FRONT_LIMIT_PIN) == LIMIT_TRIGGERED) {
        frontDone = true;
        digitalWrite(FRONT_PUL_PIN, LOW);
        Serial.println("LIMIT: front hit (decel)");
      }
      if (!rearDone && digitalRead(REAR_LIMIT_PIN) == LIMIT_TRIGGERED) {
        rearDone = true;
        digitalWrite(REAR_PUL_PIN, LOW);
        Serial.println("LIMIT: rear hit (decel)");
      }
    }
  }
}

// ============================================================
// Homing — pulse tick for descent phase
// ============================================================
static bool frontStopped = false;
static bool rearStopped  = false;

void homingPulseTick(unsigned long intervalUs) {
  if (!frontStopped) digitalWrite(FRONT_PUL_PIN, HIGH);
  if (!rearStopped)  digitalWrite(REAR_PUL_PIN,  HIGH);
  delayMicroseconds(PULSE_US);
  if (!frontStopped) digitalWrite(FRONT_PUL_PIN, LOW);
  if (!rearStopped)  digitalWrite(REAR_PUL_PIN,  LOW);
  delayMicroseconds(intervalUs - PULSE_US);

  if (!frontStopped && digitalRead(FRONT_LIMIT_PIN) == LIMIT_TRIGGERED) {
    frontStopped = true;
    digitalWrite(FRONT_PUL_PIN, LOW);
    Serial.println("HOM: front switch hit");
  }
  if (!rearStopped && digitalRead(REAR_LIMIT_PIN) == LIMIT_TRIGGERED) {
    rearStopped = true;
    digitalWrite(REAR_PUL_PIN, LOW);
    Serial.println("HOM: rear switch hit");
  }
}

// ============================================================
// Homing sequence (fully blocking)
// ============================================================
void doHoming() {
  Serial.println("HOM: starting");

  Serial.println("HOM: UP_CLEAR");
  stepBoth(true, HOMING_CLEAR_PULSES);

  Serial.println("HOM: DOWN");
  frontStopped = false;
  rearStopped  = false;
  digitalWrite(FRONT_DIR_PIN, LOW);
  digitalWrite(REAR_DIR_PIN,  LOW);
  delayMicroseconds(10);
  while (!frontStopped || !rearStopped) {
    homingPulseTick(HOMING_DOWN_US);
  }

  Serial.println("HOM: ZERO");

  Serial.println("HOM: BUMP_UP");
  stepBoth(true, HOMING_BUMP_PULSES);

  Serial.println("HOMING_DONE");
}

// ============================================================
// Setup
// ============================================================
void setup() {
  // Drive
  pinMode(LF_PWM_PIN, OUTPUT); pinMode(LF_DIR_PIN, OUTPUT);
  pinMode(RF_PWM_PIN, OUTPUT); pinMode(RF_DIR_PIN, OUTPUT);
  pinMode(LB_PWM_PIN, OUTPUT); pinMode(LB_DIR_PIN, OUTPUT);
  pinMode(RB_PWM_PIN, OUTPUT); pinMode(RB_DIR_PIN, OUTPUT);
  stopAll();

  // Steppers
  pinMode(FRONT_DIR_PIN,  OUTPUT); pinMode(FRONT_PUL_PIN,  OUTPUT);
  pinMode(REAR_DIR_PIN,   OUTPUT); pinMode(REAR_PUL_PIN,   OUTPUT);
  pinMode(TOGGLE_DIR_PIN, OUTPUT); pinMode(TOGGLE_PUL_PIN, OUTPUT);
  digitalWrite(FRONT_PUL_PIN,  LOW);
  digitalWrite(REAR_PUL_PIN,   LOW);
  digitalWrite(TOGGLE_PUL_PIN, LOW);

  // Limit switches (NC, INPUT_PULLUP)
  pinMode(FRONT_LIMIT_PIN, INPUT_PULLUP);
  pinMode(REAR_LIMIT_PIN,  INPUT_PULLUP);

  // Servo
  servo1.attach(SERVO1_PIN, 500, 2500);
  servo1.write(SERVO1_POS_A);        // default 100°
  servo2.attach(SERVO2_PIN, SERVO2_MIN_US, SERVO2_MAX_US);
  servo2.writeMicroseconds(servo2AngleToUs(servo2_pos));   // default 185°

  // Pneumatic DCVs (active LOW — start open)
  pinMode(DCV_SH_PIN,  OUTPUT); digitalWrite(DCV_SH_PIN,  HIGH);
  pinMode(DCV_SH2_PIN, OUTPUT); digitalWrite(DCV_SH2_PIN, HIGH);

  // IR sensors
  pinMode(IR_51_PIN, INPUT);
  pinMode(IR_15_PIN, INPUT);   // unused, reserved

  Serial.begin(115200);
  Serial.println("READY");
}

// ============================================================
// Loop
// ============================================================
void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.length() < 1) { Serial.println("ERR"); return; }

    char c0 = cmd.charAt(0);

    // ── Homing ───────────────────────────────────────────────
    if (c0 == 'h') {
      doHoming();
      return;
    }

    // ── Servo2 3-state (i1/i2/i3) ────────────────────────────
    // i1=95°, i2=185°, i3=270°  (270° servo, uses writeMicroseconds)
    if (c0 == 'i') {
      char state = cmd.charAt(1);
      if      (state == '1') { servo2_pos = SERVO2_POS_1; }
      else if (state == '2') { servo2_pos = SERVO2_POS_2; }
      else if (state == '3') { servo2_pos = SERVO2_POS_3; }
      else                   { Serial.println("ERR"); return; }
      servo2.writeMicroseconds(servo2AngleToUs(servo2_pos));
      Serial.print("SERVO2: ");
      Serial.println(servo2_pos);
      return;
    }

    // ── Servo1 2-state toggle (v) ────────────────────────────
    // v → toggle between 100° (POS_A) and 10° (POS_B)
    if (c0 == 'v') {
      servo1_at_A = !servo1_at_A;
      int angle = servo1_at_A ? SERVO1_POS_A : SERVO1_POS_B;
      servo1.write(angle);
      Serial.print("SERVO1: ");
      Serial.println(angle);
      return;
    }

    // ── Pneumatic 1 toggle (p) ───────────────────────────────
    // ── Pneumatic 2 toggle (k) ───────────────────────────────
    if (c0 == 'k') {
      dcv_sh2_state = !dcv_sh2_state;
      digitalWrite(DCV_SH2_PIN, dcv_sh2_state ? LOW : HIGH);
      Serial.print("PNEUMATIC2: ");
      Serial.println(dcv_sh2_state ? "CLOSED" : "OPEN");
      return;
    }

    // ── Toggle stepper forward (g[pulses]) ───────────────────
    if (c0 == 'g') {
      long pulses = cmd.substring(1).toInt();
      if (pulses > 0) {
        stepToggle(true, pulses);
        Serial.println("DONE");
      } else {
        Serial.println("ERR");
      }
      return;
    }

    // ── Toggle stepper backward (j[pulses]) ──────────────────
    if (c0 == 'j') {
      long pulses = cmd.substring(1).toInt();
      if (pulses > 0) {
        stepToggle(false, pulses);
        Serial.println("DONE");
      } else {
        Serial.println("ERR");
      }
      return;
    }

    if (cmd.length() < 2) { Serial.println("ERR"); return; }

    char c1 = cmd.charAt(1);

    // ── Stepper commands ─────────────────────────────────────
    // Format: [f/r/a][u/d][pulses]
    if ((c0=='f' || c0=='r' || c0=='a') && (c1=='u' || c1=='d')) {
      long pulses = cmd.substring(2).toInt();
      bool up = (c1 == 'u');

      if      (c0 == 'f') stepMotor(FRONT_PUL_PIN, FRONT_DIR_PIN, up, pulses);
      else if (c0 == 'r') stepMotor(REAR_PUL_PIN,  REAR_DIR_PIN,  up, pulses);
      else if (c0 == 'a') stepBoth(up, pulses);

      Serial.println("DONE");
      return;
    }

    // ── Drive commands ───────────────────────────────────────
    float val = cmd.substring(1).toFloat();
    int S = SPEED;

    switch (c0) {
      case 'f': {
        unsigned long ms = (unsigned long)(val * MS_PER_M / 1000.0f);
        runFor(S, S, S, S, ms);
        Serial.println("DONE");
        break;
      }
      case 'b': {
        unsigned long ms = (unsigned long)(val * MS_PER_M / 1000.0f);
        runFor(-S, -S, -S, -S, ms);
        Serial.println("DONE");
        break;
      }
      case 'l': {
        unsigned long ms = (unsigned long)(val * MS_PER_M_STRAFE / 1000.0f);
        runFor(-S, S, S, -S, ms);
        Serial.println("DONE");
        break;
      }
      case 'r': {
        unsigned long ms = (unsigned long)(val * MS_PER_M_STRAFE / 1000.0f);
        runFor(S, -S, -S, S, ms);
        Serial.println("DONE");
        break;
      }
      case 'e': {
        unsigned long ms = (unsigned long)(val * MS_PER_DEG);
        runFor(S, -S, S, -S, ms);
        Serial.println("DONE");
        break;
      }
      case 'q': {
        unsigned long ms = (unsigned long)(val * MS_PER_DEG);
        runFor(-S, S, -S, S, ms);
        Serial.println("DONE");
        break;
      }
      case 's': {
        stopAll();
        Serial.println("DONE");
        break;
      }
      default:
        Serial.println("ERR");
        break;
    }
  }

  // ── IR sensor 51 → pneumatic 1 (pin 46) ──────────────────
  // Runs every loop tick regardless of serial activity
  // IR reads 0 (LOW) → close pneumatic (LOW = active)
  // IR reads 1 (HIGH) → open pneumatic (HIGH = inactive)
  //digitalWrite(DCV_SH_PIN, digitalRead(IR_51_PIN) == LOW ? LOW : HIGH);
  if(digitalRead(IR_51_PIN)==LOW) isPneumaticDetected = true;
  digitalWrite(DCV_SH_PIN,!isPneumaticDetected);
}
