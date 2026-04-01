// ================================================================
//  R2 NORMAL WHEEL CAR  —  Arduino Mega 2560 + Serial from Pi
//  Hardware  : Arduino Mega 2560
//              + Rhino MDD20Amp ×2 (drive, 4 DC motors with encoders)
//              + Rhino MDD20Amp ×1 (2 pneumatic solenoid valves)
//
//  Serial packet from Raspberry Pi (via USB cable):
//    <leftSpeed,rightSpeed,P1,P2>\n
//    leftSpeed  : -60…+60  (left  motors target RPM, post arcade-mix)
//    rightSpeed : -60…+60  (right motors target RPM, post arcade-mix)
//    P1         : 0 or 1   (pneumatic 1 state)
//    P2         : 0 or 1   (pneumatic 2 state)
//
//  Features:
//    • ENCODER-BASED PID SPEED CONTROL — all 4 wheels locked to
//      equal RPM via quadrature encoder feedback + PID loop
//    • S-Curve motor ramping (cubic ease-in-out) on RPM target
//    • Feedforward + PID for fast, accurate speed tracking
//    • Pneumatic solenoid ON/OFF via 3rd motor driver
//    • Safety timeout: motors stop if no packet for 500 ms
//      (pneumatics HOLD their state — same as ESP32 behaviour)
//    • Heartbeat LED on pin 13
//    • PING/PONG connectivity check
// ================================================================

// ================================================================
//  WIRING  —  Rhino MDD20Amp  (DIR + PWM per channel)
//
//  LEFT MDD20Amp (drive)
//    CH1: DIR=22  PWM=2   →  Left Front  (LF)
//    CH2: DIR=24  PWM=3   →  Left Back   (LB)
//
//  RIGHT MDD20Amp (drive)
//    CH1: DIR=26  PWM=4   →  Right Front (RF)
//    CH2: DIR=36  PWM=6   →  Right Back  (RB)
//
//  3rd MDD20Amp (pneumatics)
//    CH1: DIR=23  PWM=5   →  Pneumatic 1
//    CH2: DIR=25  PWM=7   →  Pneumatic 2
//
//  ENCODERS (4-wire: VCC, GND, Channel A, Channel B)
//    LF Encoder: A=18 (INT3)  B=31
//    LB Encoder: A=19 (INT2)  B=33
//    RF Encoder: A=20 (INT1)  B=35
//    RB Encoder: A=21 (INT0)  B=37
//    VCC → 5V    GND → GND  (all 4 share same 5V/GND rail)
// ================================================================

// ================================================================
//  PIN DEFINITIONS — Drive Motors
// ================================================================
#define LF_DIR 36
#define LF_PWM 2

#define LB_DIR 22
#define LB_PWM 3

#define RF_DIR 26
#define RF_PWM 6

#define RB_DIR 24
#define RB_PWM 4

// ================================================================
//  PIN DEFINITIONS — Encoder Channels (4-wire encoders)
//  Channel A MUST be on interrupt-capable pins (Mega: 2,3,18,19,20,21)
//  Channel B can be any digital pin
// ================================================================
#define ENC_LF_A  18    // Interrupt pin (INT3 on Mega)
#define ENC_LF_B  31    // Direction sense pin

#define ENC_LB_A  19    // Interrupt pin (INT2 on Mega)
#define ENC_LB_B  33    // Direction sense pin

#define ENC_RF_A  20    // Interrupt pin (INT1 on Mega)
#define ENC_RF_B  35    // Direction sense pin

#define ENC_RB_A  21    // Interrupt pin (INT0 on Mega)
#define ENC_RB_B  37    // Direction sense pin


// ================================================================
//  PIN DEFINITIONS — Pneumatic Solenoids (3rd motor driver)
// ================================================================
#define PNEU1_DIR 23
#define PNEU1_PWM 5

#define PNEU2_DIR 25
#define PNEU2_PWM 7

// ================================================================
//  MISC PINS
// ================================================================
#define LED_PIN 13   // Onboard LED — heartbeat indicator

// ================================================================
//  MOTOR INVERT FLAGS
//  Set to 1 if a motor spins the wrong way for its chassis position.
// ================================================================
#define LF_INVERT 0
#define LB_INVERT 0
#define RF_INVERT 0
#define RB_INVERT 0

// ================================================================
//  ENCODER INVERT FLAGS
//  Set to 1 if an encoder counts positive when the motor spins
//  backward. Symptoms: motor runs away to max speed or oscillates
//  wildly. Flip the flag for that motor to fix it.
// ================================================================
#define ENC_LF_INVERT 0
#define ENC_LB_INVERT 0
#define ENC_RF_INVERT 0
#define ENC_RB_INVERT 0

// ================================================================
//  TUNING
// ================================================================
#define RAMP_DURATION_MS  80     // S-curve ramp (ms) — ultra-snappy response
#define SERIAL_TIMEOUT    500    // ms — stop motors if no packet

// Serial output throttle — only print every Nth packet to avoid
// blocking the main loop while the UART drains its buffer.
#define PRINT_EVERY       25     // Print 1 in 25 packets (~8 Hz display at 200 Hz input)

// ================================================================
//  ENCODER & PID TUNING
// ================================================================

// *** CRITICAL: Change ENCODER_PPR to match YOUR encoder + gearbox ***
// Effective PPR = encoder_native_PPR × gear_ratio
// Example: 11 PPR encoder × 30:1 gearbox = 330 effective PPR
#define ENCODER_PPR       330    // Pulses Per Revolution at output shaft

// Maximum motor RPM at 100% PWM (used for feedforward calculation).
// Measure this with your motors if possible, or start with 100 and adjust.
#define MAX_RPM           100.0f

// Maximum RPM the Pi will ever send (used for input clamping)
#define INPUT_MAX_RPM     60

// PID gains — tune these for your motors.
// Start with defaults, then adjust:
//   - If motors oscillate: reduce Kp
//   - If motors don't reach target: increase Ki
//   - If motors overshoot: increase Kd slightly
#define PID_KP            0.8f   // Proportional gain  (reduced to prevent overshoot)
#define PID_KI            1.0f   // Integral gain      (reduced to prevent windup runaway)
#define PID_KD            0.05f  // Derivative gain
#define PID_INTEGRAL_MAX  80.0f  // Anti-windup limit for integral term (tighter cap)

// How often to compute RPM from encoder counts (ms).
// 20 ms = 50 Hz — good balance of resolution and responsiveness.
#define RPM_CALC_INTERVAL 20

// ================================================================
//  S-CURVE RAMP STATE (per motor) — smooths RPM target transitions
// ================================================================
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

// ================================================================
//  PID CONTROLLER (per motor)
// ================================================================
struct PIDController {
  float Kp, Ki, Kd;
  float integral;
  float prevError;
  int   pwmOutput;   // Final PWM value: -255 … +255
};

PIDController pidLF = {PID_KP, PID_KI, PID_KD, 0, 0, 0};
PIDController pidLB = {PID_KP, PID_KI, PID_KD, 0, 0, 0};
PIDController pidRF = {PID_KP, PID_KI, PID_KD, 0, 0, 0};
PIDController pidRB = {PID_KP, PID_KI, PID_KD, 0, 0, 0};

// ================================================================
//  ENCODER STATE — volatile because modified in ISR
// ================================================================
volatile long encCountLF = 0;
volatile long encCountLB = 0;
volatile long encCountRF = 0;
volatile long encCountRB = 0;

// Actual measured RPM (updated every RPM_CALC_INTERVAL ms)
float actualRPM_LF = 0.0f;
float actualRPM_LB = 0.0f;
float actualRPM_RF = 0.0f;
float actualRPM_RB = 0.0f;

// ================================================================
//  ENCODER ISR (Interrupt Service Routines)
//  On rising edge of Channel A, read Channel B to get direction.
//  Channel B HIGH when A rises = one direction, LOW = other.
// ================================================================
void ISR_ENC_LF() {
  if (ENC_LF_INVERT)
    encCountLF += digitalRead(ENC_LF_B) ? 1 : -1;
  else
    encCountLF += digitalRead(ENC_LF_B) ? -1 : 1;
}
void ISR_ENC_LB() {
  if (ENC_LB_INVERT)
    encCountLB += digitalRead(ENC_LB_B) ? 1 : -1;
  else
    encCountLB += digitalRead(ENC_LB_B) ? -1 : 1;
}
void ISR_ENC_RF() {
  if (ENC_RF_INVERT)
    encCountRF += digitalRead(ENC_RF_B) ? 1 : -1;
  else
    encCountRF += digitalRead(ENC_RF_B) ? -1 : 1;
}
void ISR_ENC_RB() {
  if (ENC_RB_INVERT)
    encCountRB += digitalRead(ENC_RB_B) ? 1 : -1;
  else
    encCountRB += digitalRead(ENC_RB_B) ? -1 : 1;
}


// ================================================================
//  MOTOR TARGETS & MISC STATE
// ================================================================
int targetLF = 0, targetLB = 0, targetRF = 0, targetRB = 0;

// Pneumatic state
bool pneu1State = false;
bool pneu2State = false;

// Timing
unsigned long lastPacketTime  = 0;
unsigned long lastLEDTime     = 0;
unsigned long lastRPMCalcTime = 0;
bool ledState = false;

// ================================================================
//  MOTOR FUNCTIONS
// ================================================================
int applyInvert(int speed, int invertFlag) {
  return invertFlag ? -speed : speed;
}

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

void setPneumatic(uint8_t dirPin, uint8_t pwmPin, bool state) {
  if (state) {
    digitalWrite(dirPin, HIGH);
    analogWrite(pwmPin, 255);   // Full power to energize solenoid
  } else {
    digitalWrite(dirPin, LOW);
    analogWrite(pwmPin, 0);     // Off
  }
}

// ================================================================
//  PID HELPER FUNCTIONS
// ================================================================
void resetPID(PIDController &pid) {
  pid.integral  = 0;
  pid.prevError = 0;
  pid.pwmOutput = 0;
}

float computeRPM(volatile long &count, unsigned long dtMs) {
  // Atomically read and reset pulse counter
  noInterrupts();
  long pulses = count;
  count = 0;
  interrupts();

  // RPM = (pulses / PPR) × (60000 / dt_ms)
  return ((float)pulses / (float)ENCODER_PPR) * (60000.0f / (float)dtMs);
}

void updatePID(PIDController &pid, float targetRPM, float actualRPM, float dtSec) {
  // When target is ~0 and motor is basically stopped, bypass PID
  if (abs(targetRPM) < 0.5f) {
    pid.integral  = 0;
    pid.prevError = 0;
    pid.pwmOutput = 0;
    return;
  }

  float error = targetRPM - actualRPM;

  // --- Anti-windup: only accumulate integral when output is not saturated ---
  // Also reset integral if error changes sign (crossing zero)
  if ((pid.prevError > 0 && error < 0) || (pid.prevError < 0 && error > 0)) {
    pid.integral = 0;  // Zero-crossing reset prevents overshoot
  }
  pid.integral += error * dtSec;
  pid.integral = constrain(pid.integral, -PID_INTEGRAL_MAX, PID_INTEGRAL_MAX);

  // Derivative (avoid division by zero)
  float derivative = (dtSec > 0.001f) ? (error - pid.prevError) / dtSec : 0.0f;
  pid.prevError = error;

  // Feedforward: estimate PWM from target RPM (linear approximation)
  float ff = targetRPM * (255.0f / MAX_RPM);

  // PID correction on top of feedforward
  float correction = pid.Kp * error + pid.Ki * pid.integral + pid.Kd * derivative;
  float output = ff + correction;

  // Clamp total output to safe PWM range
  // Also cap proportional to target — a 10 RPM target should never produce 255 PWM
  float maxPWM = min(255.0f, abs(targetRPM) * (255.0f / MAX_RPM) * 1.5f);
  pid.pwmOutput = constrain((int)output, (int)-maxPWM, (int)maxPWM);
}

// ================================================================
//  STOP ALL — reset motors, ramps, PID, and pneumatics
// ================================================================
void stopAll() {
  setMotor(LF_DIR, LF_PWM, 0);
  setMotor(LB_DIR, LB_PWM, 0);
  setMotor(RF_DIR, RF_PWM, 0);
  setMotor(RB_DIR, RB_PWM, 0);
  targetLF = targetLB = targetRF = targetRB = 0;
  rampLF = rampLB = rampRF = rampRB = {0, 0, 0, 0, false};

  // Reset PID controllers
  resetPID(pidLF);
  resetPID(pidLB);
  resetPID(pidRF);
  resetPID(pidRB);

  // Reset encoder counters
  noInterrupts();
  encCountLF = encCountLB = encCountRF = encCountRB = 0;
  interrupts();
  actualRPM_LF = actualRPM_LB = actualRPM_RF = actualRPM_RB = 0.0f;

  // Close both pneumatics
  pneu1State = false;
  pneu2State = false;
  setPneumatic(PNEU1_DIR, PNEU1_PWM, false);
  setPneumatic(PNEU2_DIR, PNEU2_PWM, false);
}

// ================================================================
//  S-CURVE RAMP  (cubic ease-in-out — identical to ESP32 v3.0)
//  Now used to smooth the RPM TARGET transition, not the PWM output.
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
    m.startSpeed      = m.currentSpeed;
    m.targetSpeed     = newTarget;
    m.transitionStart = millis();
    m.transitioning   = true;
  }
  if (m.transitioning) {
    float elapsed = (float)(millis() - m.transitionStart);
    float t       = elapsed / (float)RAMP_DURATION_MS;
    if (t >= 1.0f) {
      m.currentSpeed  = m.targetSpeed;
      m.transitioning = false;
    } else {
      float progress  = sCurve(t);
      m.currentSpeed  = m.startSpeed +
                         (int)((float)(m.targetSpeed - m.startSpeed) * progress);
    }
  }
}

// ================================================================
//  applyRamp()  —  S-curve ramp targets + PID-corrected motor output
//
//  Flow: target → S-curve ramp → smooth RPM setpoint → PID uses
//        encoder feedback to compute PWM → setMotor()
// ================================================================
void applyRamp() {
  // Step A: S-curve smooth the RPM targets
  updateMotorRamp(rampLF, targetLF);
  updateMotorRamp(rampLB, targetLB);
  updateMotorRamp(rampRF, targetRF);
  updateMotorRamp(rampRB, targetRB);

  // Step B: Apply PID-corrected PWM output to motors
  // (PID was updated in loop() at RPM_CALC_INTERVAL rate)
  setMotor(LF_DIR, LF_PWM, applyInvert(pidLF.pwmOutput, LF_INVERT));
  setMotor(LB_DIR, LB_PWM, applyInvert(pidLB.pwmOutput, LB_INVERT));
  setMotor(RF_DIR, RF_PWM, applyInvert(pidRF.pwmOutput, RF_INVERT));
  setMotor(RB_DIR, RB_PWM, applyInvert(pidRB.pwmOutput, RB_INVERT));
}

// ================================================================
//  SERIAL HELPERS
// ================================================================
char dirChar(int s) { return s > 0 ? 'F' : (s < 0 ? 'R' : 'S'); }

// ================================================================
//  processPacket()  —  parse and apply <leftSpeed,rightSpeed,P1,P2>
//  MINIMAL-LATENCY VERSION: compact output, throttled printing
// ================================================================
static unsigned long pktCount = 0;   // Packet counter for throttling

void processPacket(int leftSpeed, int rightSpeed, int p1, int p2) {
  // Constrain motor speed targets to max RPM the Pi sends
  leftSpeed  = constrain(leftSpeed,  -INPUT_MAX_RPM, INPUT_MAX_RPM);
  rightSpeed = constrain(rightSpeed, -INPUT_MAX_RPM, INPUT_MAX_RPM);

  // Set motor targets — left pair gets leftSpeed, right pair gets rightSpeed
  targetLF = leftSpeed;
  targetLB = leftSpeed;
  targetRF = rightSpeed;
  targetRB = rightSpeed;

  // Set pneumatic states (always print on change — these are rare events)
  bool newP1 = (p1 != 0);
  bool newP2 = (p2 != 0);

  if (newP1 != pneu1State) {
    pneu1State = newP1;
    setPneumatic(PNEU1_DIR, PNEU1_PWM, pneu1State);
    Serial.print(F("[PNEU] P1="));
    Serial.println(pneu1State ? '1' : '0');
  }
  if (newP2 != pneu2State) {
    pneu2State = newP2;
    setPneumatic(PNEU2_DIR, PNEU2_PWM, pneu2State);
    Serial.print(F("[PNEU] P2="));
    Serial.println(pneu2State ? '1' : '0');
  }

  // Throttled compact output — only print every PRINT_EVERY packets
  pktCount++;
  if (pktCount >= PRINT_EVERY) {
    pktCount = 0;
    // Show target RPM, actual RPM (from encoders), and PID PWM output
    Serial.print(F("T="));
    if (leftSpeed >= 0) Serial.print('+');
    Serial.print(leftSpeed);
    Serial.print('/');
    if (rightSpeed >= 0) Serial.print('+');
    Serial.print(rightSpeed);
    Serial.print(F(" RPM="));
    Serial.print((int)actualRPM_LF);
    Serial.print('/');
    Serial.print((int)actualRPM_LB);
    Serial.print('/');
    Serial.print((int)actualRPM_RF);
    Serial.print('/');
    Serial.print((int)actualRPM_RB);
    Serial.print(F(" PWM="));
    Serial.print(pidLF.pwmOutput);
    Serial.print('/');
    Serial.print(pidRF.pwmOutput);
    Serial.print(F(" P="));
    Serial.print(pneu1State ? '1' : '0');
    Serial.println(pneu2State ? '1' : '0');
  }
}

// ================================================================
//  FAST PARSER — replaces heavy sscanf() for ~10x speed on AVR
// ================================================================
bool fastParse4(const char *buf, int &a, int &b, int &c, int &d) {
  char *p = (char *)buf;
  char *end;
  a = strtol(p,     &end, 10); if (*end != ',') return false;
  b = strtol(end+1, &end, 10); if (*end != ',') return false;
  c = strtol(end+1, &end, 10); if (*end != ',') return false;
  d = strtol(end+1, &end, 10);
  return true;
}

// ================================================================
//  SERIAL PARSER  —  reads <...> packets + plain-text commands
// ================================================================
const int BUF_SIZE = 48;
char rxBuf[BUF_SIZE];
int  rxIdx = 0;
bool inPacket = false;

char cmdBuf[BUF_SIZE];
int  cmdIdx = 0;

bool readPacket() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '<') {
      inPacket = true;
      rxIdx    = 0;
      cmdIdx   = 0;
    } else if (c == '>' && inPacket) {
      rxBuf[rxIdx] = '\0';
      inPacket = false;
      rxIdx    = 0;
      return true;
    } else if (inPacket && rxIdx < BUF_SIZE - 1) {
      rxBuf[rxIdx++] = c;
    }

    else if (!inPacket) {
      if (c == '\n' || c == '\r') {
        if (cmdIdx > 0) {
          cmdBuf[cmdIdx] = '\0';
          cmdIdx = 0;
          // Handle plain-text commands
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
//  heartbeat()  —  blink LED (fast=active, slow=no comms)
// ================================================================
void heartbeat(bool activeComms) {
  unsigned long interval = activeComms ? 200UL : 800UL;
  if (millis() - lastLEDTime >= interval) {
    lastLEDTime = millis();
    ledState    = !ledState;
    digitalWrite(LED_PIN, ledState);
  }
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
  Serial.begin(250000);   // Must match Pi BAUD_RATE

  Serial.println(F("================================================"));
  Serial.println(F("  R2 NORMAL WHEEL CAR  —  Arduino Mega"));
  Serial.println(F("  Encoder PID | S-Curve Ramp | Serial from Pi"));
  Serial.println(F("================================================"));
  Serial.print(F("  RAMP_DURATION = "));
  Serial.print(RAMP_DURATION_MS);
  Serial.println(F(" ms"));
  Serial.print(F("  TIMEOUT       = "));
  Serial.print(SERIAL_TIMEOUT);
  Serial.println(F(" ms"));
  Serial.print(F("  ENCODER_PPR   = "));
  Serial.println(ENCODER_PPR);
  Serial.print(F("  MAX_RPM       = "));
  Serial.println((int)MAX_RPM);
  Serial.print(F("  PID  Kp="));
  Serial.print(PID_KP);
  Serial.print(F("  Ki="));
  Serial.print(PID_KI);
  Serial.print(F("  Kd="));
  Serial.println(PID_KD);
  Serial.print(F("  INVERT FLAGS  : LF="));
  Serial.print(LF_INVERT);
  Serial.print(F(" LB="));
  Serial.print(LB_INVERT);
  Serial.print(F(" RF="));
  Serial.print(RF_INVERT);
  Serial.print(F(" RB="));
  Serial.println(RB_INVERT);
  Serial.print(F("  ENC INVERT    : LF="));
  Serial.print(ENC_LF_INVERT);
  Serial.print(F(" LB="));
  Serial.print(ENC_LB_INVERT);
  Serial.print(F(" RF="));
  Serial.print(ENC_RF_INVERT);
  Serial.print(F(" RB="));
  Serial.println(ENC_RB_INVERT);
  Serial.println(F("------------------------------------------------"));
  Serial.print(F("  MOTOR: LF="));
  Serial.print(LF_DIR); Serial.print('/'); Serial.print(LF_PWM);
  Serial.print(F("  LB="));
  Serial.print(LB_DIR); Serial.print('/'); Serial.print(LB_PWM);
  Serial.print(F("  RF="));
  Serial.print(RF_DIR); Serial.print('/'); Serial.print(RF_PWM);
  Serial.print(F("  RB="));
  Serial.print(RB_DIR); Serial.print('/'); Serial.println(RB_PWM);
  Serial.print(F("  ENC:   LF="));
  Serial.print(ENC_LF_A); Serial.print('/'); Serial.print(ENC_LF_B);
  Serial.print(F("  LB="));
  Serial.print(ENC_LB_A); Serial.print('/'); Serial.print(ENC_LB_B);
  Serial.print(F("  RF="));
  Serial.print(ENC_RF_A); Serial.print('/'); Serial.print(ENC_RF_B);
  Serial.print(F("  RB="));
  Serial.print(ENC_RB_A); Serial.print('/'); Serial.println(ENC_RB_B);
  Serial.print(F("  PNEU: P1="));
  Serial.print(PNEU1_DIR); Serial.print('/'); Serial.print(PNEU1_PWM);
  Serial.print(F("  P2="));
  Serial.print(PNEU2_DIR); Serial.print('/'); Serial.println(PNEU2_PWM);
  Serial.println(F("------------------------------------------------"));
  Serial.println(F("  Packet format: <leftRPM,rightRPM,P1,P2>"));
  Serial.println(F("  Text commands: PING → PONG"));
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

  // Encoder pins — Channel A as INPUT_PULLUP (interrupt), Channel B as INPUT_PULLUP
  pinMode(ENC_LF_A, INPUT_PULLUP);
  pinMode(ENC_LF_B, INPUT_PULLUP);
  pinMode(ENC_LB_A, INPUT_PULLUP);
  pinMode(ENC_LB_B, INPUT_PULLUP);
  pinMode(ENC_RF_A, INPUT_PULLUP);
  pinMode(ENC_RF_B, INPUT_PULLUP);
  pinMode(ENC_RB_A, INPUT_PULLUP);
  pinMode(ENC_RB_B, INPUT_PULLUP);

  // Attach interrupts for encoder Channel A (RISING edge)
  attachInterrupt(digitalPinToInterrupt(ENC_LF_A), ISR_ENC_LF, RISING);
  attachInterrupt(digitalPinToInterrupt(ENC_LB_A), ISR_ENC_LB, RISING);
  attachInterrupt(digitalPinToInterrupt(ENC_RF_A), ISR_ENC_RF, RISING);
  attachInterrupt(digitalPinToInterrupt(ENC_RB_A), ISR_ENC_RB, RISING);

  // Pneumatic pins
  pinMode(PNEU1_DIR, OUTPUT);
  pinMode(PNEU1_PWM, OUTPUT);
  pinMode(PNEU2_DIR, OUTPUT);
  pinMode(PNEU2_PWM, OUTPUT);

  // LED
  pinMode(LED_PIN, OUTPUT);

  stopAll();

  lastPacketTime  = millis();
  lastRPMCalcTime = millis();
  Serial.println(F("Ready. Run r2_pi_ps4.py on Raspberry Pi."));
  Serial.println(F("================================================"));
}

// ================================================================
//  LOOP  —  1 ms delay (1000 Hz, 10× the Pi's 100 Hz input rate)
// ================================================================
void loop() {

  bool activeComms = (millis() - lastPacketTime < SERIAL_TIMEOUT);

  // Step 1 — Parse incoming serial packet
  if (readPacket()) {
    int leftSpeed, rightSpeed, p1, p2;
    if (fastParse4(rxBuf, leftSpeed, rightSpeed, p1, p2)) {
      lastPacketTime = millis();
      processPacket(leftSpeed, rightSpeed, p1, p2);
    } else {
      Serial.print(F("[ERR] Bad packet: <"));
      Serial.print(rxBuf);
      Serial.println('>');
    }
  }

  // Step 2 — Safety timeout (motors only; pneumatics hold state)
  if (!activeComms) {
    if (targetLF != 0 || targetLB != 0 || targetRF != 0 || targetRB != 0) {
      Serial.println(F("[TIMEOUT] No data from Pi — zeroing motor targets"));
    }
    targetLF = targetLB = targetRF = targetRB = 0;
  }

  // Step 3 — S-Curve smooth ramp (updates RPM setpoints smoothly)
  //          + apply PID-corrected PWM to motors
  applyRamp();

  // Step 4 — Encoder RPM computation + PID update (every 20 ms)
  if (millis() - lastRPMCalcTime >= RPM_CALC_INTERVAL) {
    unsigned long dt = millis() - lastRPMCalcTime;
    lastRPMCalcTime = millis();
    float dtSec = (float)dt / 1000.0f;

    // Compute actual RPM from encoder pulse counts
    actualRPM_LF = computeRPM(encCountLF, dt);
    actualRPM_LB = computeRPM(encCountLB, dt);
    actualRPM_RF = computeRPM(encCountRF, dt);
    actualRPM_RB = computeRPM(encCountRB, dt);

    // PID: compare ramped RPM setpoint vs actual RPM → compute PWM
    updatePID(pidLF, (float)rampLF.currentSpeed, actualRPM_LF, dtSec);
    updatePID(pidLB, (float)rampLB.currentSpeed, actualRPM_LB, dtSec);
    updatePID(pidRF, (float)rampRF.currentSpeed, actualRPM_RF, dtSec);
    updatePID(pidRB, (float)rampRB.currentSpeed, actualRPM_RB, dtSec);
  }

  // Step 5 — Heartbeat LED
  heartbeat(activeComms);

  // 1 ms delay — runs loop at ~1000 Hz (10× the Pi's 100 Hz input)
  // Smooth S-curve ramp resolution preserved, prevents unnecessary heat
  delay(1);
}
