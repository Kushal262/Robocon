// ================================================================
//  RC MECANUM WHEEL CONTROL  —  v1.0
//  Hardware  : Arduino Mega 2560 + Rhino MDD20Amp ×2 + 4 DC Motors + 6-CH RC
//
//  Interface : 6-Channel RC Receiver (PWM output)
//  Wiring to Arduino Mega: 
//    CH1 (Right Stick Horizontal) → Pin A8 (PCINT16)
//    CH2 (Right Stick Vertical)   → Pin A9 (PCINT17) - Unused directly
//    CH3 (Left Stick Vertical)    → Pin A10(PCINT18)
//    CH4 (Left Stick Horizontal)  → Pin A11(PCINT19)
//    CH5 (Toggle Switch)          → Pin A12(PCINT20)
//    CH6 (Aux Switch/Knob)        → Pin A13(PCINT21)
//
//  Controls:
//    Left  Stick Vertical   (CH3) → Forward / Backward
//    Left  Stick Horizontal (CH4) → Crabwalk (Strafe Left / Right)
//    Right Stick Horizontal (CH1) → Rotate (Clockwise / Anti-Clockwise)
//    CH5 Toggle Switch            → Safety Motor Enable / Disable 
//
//  Features:
//    • Interrupt-driven extremely fast RC reading (Non-blocking)
//    • Mecanum vector mixing
//    • Smooth ramp-up / down algorithms ported from original codebase
//    • Fail-safe out-of-bounds drop/disconnect detection
// ================================================================

// ================================================================
//  PIN DEFINITIONS (Same as original Rhino MDD20A setup!)
// ================================================================
#define LF_DIR 22
#define LF_PWM 2

#define LB_DIR 24
#define LB_PWM 3

#define RF_DIR 26
#define RF_PWM 4

#define RB_DIR 36
#define RB_PWM 6

#define LED_PIN 13

// ================================================================
//  RC RECEIVER CHANNEL MAPPING
//  Change these indices (0 to 5) if your receiver behaves differently.
//  Index 0 = CH1, Index 1 = CH2, etc. (Connected to A8..A13 sequentially)
// ================================================================
// 0 = CH1 (Usually Right Stick Horizontal)
// 1 = CH2 (Usually Right Stick Vertical)
// 2 = CH3 (Usually Left Stick Vertical - non centering throttle)
// 3 = CH4 (Usually Left Stick Horizontal)
// 4 = CH5 (Switch)
// 5 = CH6 (Switch/Knob)

#define CH_ROTATE  0    // Mapping Z-Axis (Rotation) to Right Joystick H
#define CH_FWD_BWD 2    // Mapping Y-Axis (Forward) to Left Joystick V
#define CH_STRAFE  3    // Mapping X-Axis (Crabwalk) to Left Joystick H
#define CH_ENABLE  4    // Mapping Safety toggle to switch CH5

// ================================================================
//  INVERT FLAGS
// ================================================================
// 1. RC Transmitter Inverts (Change to 1 if stick feels backwards)
#define INV_RC_FWD_BWD 0
#define INV_RC_STRAFE  0
#define INV_RC_ROTATE  0
#define INV_RC_ENABLE  0  // Flip switch direction for enable/disable

// 2. Motor Inverts (Change to 1 if a single motor spins strangely)
#define LF_INVERT 0
#define LB_INVERT 0
#define RF_INVERT 0
#define RB_INVERT 0 // Used to be 1 in some notes, adjust as necessary

// ================================================================
//  TUNING & RAMPING
// ================================================================
// Global Limits
#define MAX_SPEED       255 // Rhino MDD20 accepts up to 255.
#define RC_DEADZONE     30  // How wide the center "stop" zone of your sticks is
#define RC_RANGE        400 // The deviation from 1500 (e.g. 1500 +- 400 means 1100 to 1900 stick travel gives full speed)

// Ramp speeds (lower = smoother but delayed; higher = snappy but aggressive)
#define RAMP_UP_STEP    14
#define RAMP_DOWN_STEP  20

#define LOOP_MS         5   // Main logic loop cadence
#define RC_TIMEOUT      500 // Stop motors if no RC signal change detected in ms

// ================================================================
//  STATE VARIABLES
// ================================================================
volatile uint16_t rc_shared[6] = {1500, 1500, 1500, 1500, 1500, 1500};
volatile uint32_t rc_start[6];
volatile uint32_t last_rc_time;
uint16_t rc_values[6];

int targetLF = 0, targetLB = 0, targetRF = 0, targetRB = 0;
int currentLF = 0, currentLB = 0, currentRF = 0, currentRB = 0;

unsigned long lastLoopTime = 0;
unsigned long lastLEDTime = 0;
bool ledState = false;
bool motorsEnabled = true;

// ================================================================
//  INTERRUPT SERVICE ROUTINE (Fast PWM read for A8-A13)
// ================================================================
ISR(PCINT2_vect) {
  uint32_t current_time = micros();
  uint8_t current_port = PINK; // Read PORTK pins directly (A8 -> PK0, A13 -> PK5)
  static uint8_t previous_port = 0;
  
  uint8_t changed_pins = current_port ^ previous_port;
  
  for (uint8_t i = 0; i < 6; i++) {
    if (changed_pins & (1 << i)) {
      if (current_port & (1 << i)) {
        // Pin went HIGH -> Start timing
        rc_start[i] = current_time;
      } else {
        // Pin went LOW -> Calculate duration
        uint16_t pulse = (uint16_t)(current_time - rc_start[i]);
        if (pulse > 800 && pulse < 2200) { // Valid boundaries
          rc_shared[i] = pulse;
          last_rc_time = current_time;    // Reset RC timeout watchdog
        }
      }
    }
  }
  previous_port = current_port;
}

// Ensure Interrupts are properly initialized
void setupPCINT() {
  DDRK = 0x00;           // Set PORTK as input (A8..A15)
  PORTK = 0x3F;          // Enable internal pull-ups for A8..A13 for stability
  PCICR |= (1 << PCIE2); // Enable Pin Change Interrupts for PORTK
  PCMSK2 |= 0x3F;        // Unmask pins PK0 to PK5 (A8 to A13)
}

// Atomically fetch the RC values from the volatile interrupt array
void fetchRC() {
  noInterrupts();
  for (int i = 0; i < 6; i++) {
    rc_values[i] = rc_shared[i];
  }
  uint32_t time_since_comms = (micros() - last_rc_time) / 1000UL;
  interrupts();
  
  // Hard Failsafe: if disconnected or transmitter off -> center sticks
  if (time_since_comms > RC_TIMEOUT) {
    for (int i = 0; i < 6; i++) {
      rc_values[i] = 1500; 
    }
    motorsEnabled = false; // Safety fallback
  } else {
    // Check CH5 (Toggle Switch) to enable/disable motors. (> 1500 usually UP/ON)
    bool switch_state = (rc_values[CH_ENABLE] > 1500);
    if (INV_RC_ENABLE) switch_state = !switch_state;
    motorsEnabled = switch_state;
  }
}

// Map the raw 1000-2000 ms pulse into a -MAX_SPEED to MAX_SPEED range
int mapRC(uint16_t pulse_width, bool invert) {
  if (pulse_width < 900 || pulse_width > 2100) return 0; // Absolute bound fail-safe

  int centered = (int)pulse_width - 1500;
  
  if (abs(centered) < RC_DEADZONE) {
    return 0; // Ignore stick drift/resting tolerance
  }
  
  int mapped = 0;
  // Map linear output from edge of deadzone to full stick throw
  if (centered > 0) {
    mapped = map(centered, RC_DEADZONE, RC_RANGE, 0, MAX_SPEED);
  } else {
    mapped = map(centered, -RC_DEADZONE, -RC_RANGE, 0, -MAX_SPEED);
  }
  
  mapped = constrain(mapped, -MAX_SPEED, MAX_SPEED);
  
  return invert ? -mapped : mapped;
}

// ================================================================
//  MOTOR DRIVER LOGIC
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

void applyRamp() {
  if (!motorsEnabled) {
    // Snappy stop if disabled
    targetLF = targetLB = targetRF = targetRB = 0;
    currentLF = currentLB = currentRF = currentRB = 0;
  } else {
    currentLF = rampStep(currentLF, targetLF);
    currentLB = rampStep(currentLB, targetLB);
    currentRF = rampStep(currentRF, targetRF);
    currentRB = rampStep(currentRB, targetRB);
  }

  setMotor(LF_DIR, LF_PWM, applyInvert(currentLF, LF_INVERT));
  setMotor(LB_DIR, LB_PWM, applyInvert(currentLB, LB_INVERT));
  setMotor(RF_DIR, RF_PWM, applyInvert(currentRF, RF_INVERT));
  setMotor(RB_DIR, RB_PWM, applyInvert(currentRB, RB_INVERT));
}

int rampStep(int current, int target) {
  if (current == target) return current;

  bool speedingUp = false;
  if (target > 0 && current >= 0) {
    speedingUp = (target > current);
  } else if (target < 0 && current <= 0) {
    speedingUp = (target < current);
  }

  int step = speedingUp ? RAMP_UP_STEP : RAMP_DOWN_STEP;

  if (target > current) {
    current += step;
    if (current > target) current = target;
  } else {
    current -= step;
    if (current < target) current = target;
  }
  return current;
}

// ================================================================
//  MAIN KINEMATICS CALCULATOR
// ================================================================
void processMecanumMix() {
  // Grab desired RC vectors
  long int x = mapRC(rc_values[CH_STRAFE],  INV_RC_STRAFE);
  long int y = mapRC(rc_values[CH_FWD_BWD], INV_RC_FWD_BWD);
  long int z = mapRC(rc_values[CH_ROTATE],  INV_RC_ROTATE);
  
  // Mecanum mixing equations
  // LF = Y(Fwd) + X(Right) + Z(CW)
  long int lf = y + x + z;
  long int lb = y - x + z;
  long int rf = y - x - z;
  long int rb = y + x - z;

  // Normalization block — Ensure we never send a value > MAX_SPEED to the motors 
  // (Maintains turning proportions even when sticking full forward + full right)
  long int max_val = max(abs(lf), max(abs(lb), max(abs(rf), abs(rb))));
  
  if (max_val > MAX_SPEED) {
    lf = (lf * MAX_SPEED) / max_val;
    lb = (lb * MAX_SPEED) / max_val;
    rf = (rf * MAX_SPEED) / max_val;
    rb = (rb * MAX_SPEED) / max_val;
  }

  targetLF = (int)lf;
  targetLB = (int)lb;
  targetRF = (int)rf;
  targetRB = (int)rb;
}

// ================================================================
//  DEBUG TERMINAL LOGIC
// ================================================================
void printTelemetry() {
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint < 200) return; // Print at 5Hz
  lastPrint = millis();

  Serial.print("CH-> Rotate(Z):"); Serial.print(rc_values[CH_ROTATE]);
  Serial.print("  Fwd(Y):"); Serial.print(rc_values[CH_FWD_BWD]);
  Serial.print("  Strafe(X):"); Serial.print(rc_values[CH_STRAFE]);
  Serial.print("  Enable(Sw):"); Serial.print(rc_values[CH_ENABLE]);
  
  Serial.print(" || M-> LF:"); Serial.print(targetLF);
  Serial.print("  LB:"); Serial.print(targetLB);
  Serial.print("  RF:"); Serial.print(targetRF);
  Serial.print("  RB:"); Serial.print(targetRB);
  
  if (!motorsEnabled) {
    Serial.print(" [DISABLED]");
  }
  Serial.println();
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
  Serial.begin(115200);

  Serial.println(F("================================================"));
  Serial.println(F("  RC MECANUM WHEEL CAR  v1.0  —  Arduino Mega"));
  Serial.println(F("================================================"));

  // Initialize Motor Pins
  pinMode(LF_DIR, OUTPUT); pinMode(LF_PWM, OUTPUT);
  pinMode(LB_DIR, OUTPUT); pinMode(LB_PWM, OUTPUT);
  pinMode(RF_DIR, OUTPUT); pinMode(RF_PWM, OUTPUT);
  pinMode(RB_DIR, OUTPUT); pinMode(RB_PWM, OUTPUT);

  pinMode(LED_PIN, OUTPUT);

  // Stop initial spin
  setMotor(LF_DIR, LF_PWM, 0);
  setMotor(LB_DIR, LB_PWM, 0);
  setMotor(RF_DIR, RF_PWM, 0);
  setMotor(RB_DIR, RB_PWM, 0);

  // Initialize PCINT for fast RC readings
  setupPCINT();
  
  last_rc_time = micros();
  Serial.println(F("System Ready... Waiting for RC inputs on A8-A13."));
}

// ================================================================
//  LOOP
// ================================================================
void loop() {
  unsigned long nowMillis = millis();
  
  // Maintain precise loop timing (runs every LOOP_MS)
  if (nowMillis - lastLoopTime >= LOOP_MS) {
    lastLoopTime = nowMillis;

    // 1. Fetch live RC values securely from interrupts
    fetchRC();

    // 2. Mix vectors and calculate target motor speeds safely
    processMecanumMix();

    // 3. Incrementively slope actual motor powers towards target (smoothing)
    applyRamp();
  }

  // Debug Prints (non-blocking)
  printTelemetry();

  // Heartbeat LED
  if (nowMillis - lastLEDTime > (motorsEnabled ? 100UL : 500UL)) {
    lastLEDTime = nowMillis;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }
}
