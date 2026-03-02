// ================================================================
//  MECANUM WHEEL CAR  —  v2.2  (no startup test, reduced latency)
//  Hardware  : Arduino Mega 2560 + Rhino MDD20Amp ×2 + 4 DC Motors
//  Interface : PS4 via Python (pygame + pyserial) over USB cable
//
//  Serial packet received from Python:
//    <LX,LY,RX>\n
//    LX  : left  stick X   -255…+255   (+ve = strafe right)
//    LY  : left  stick Y   -255…+255   (+ve = forward)
//    RX  : right stick X   -255…+255   (+ve = rotate CW)
//
//  Controls:
//    Left  Stick → Forward / Backward / Strafe / All diagonals
//    Right Stick → Rotate Clockwise / Anti-Clockwise
//
//  Features:
//    • Smooth ramp-up / ramp-down
//    • Detailed serial monitor: INPUT → TARGET → ACTUAL → DIR
//    • Safety timeout: motors stop if no packet for 500 ms
//    • RB_DIR fixed to pin 36 (pin 34 was unreliable on some boards)
//    • RB motor direction invert flag for mirrored-mount correction
//    • Heartbeat LED on pin 13
//    • Serial command  "TEST\n"  triggers motor self-test on demand
//    • Serial command  "PING\n"  replies  "PONG"  for comms check
//    • Low-latency 5 ms loop (200 Hz) — reduced from 20 ms
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
//         ^^^  changed from 34 → 36 (see note below)
//
//  DIR HIGH  =  forward spin
//  DIR LOW   =  reverse spin
//
// ================================================================
//  WHY RB_DIR IS PIN 36, NOT PIN 34
// ================================================================
//  Pin 34 (Port C bit 3) is a valid output but has been observed
//  to stay stuck LOW on some Mega boards due to board-level leakage
//  or solder joint issues near the JTAG header (pins 22-29 area).
//  Pin 36 (Port C bit 1) is further from that cluster and tested
//  reliable.  If RB still only spins one way after this change,
//  set RB_INVERT to 1 below — this flips the direction in software.
//
// ================================================================
//  WHY RB_PWM IS PIN 6, NOT PIN 5
// ================================================================
//  Arduino Mega Timer3 controls: Pin 2 (OC3B), Pin 3 (OC3C),
//  Pin 5 (OC3A).  In Phase-Correct PWM mode, OCR3A is the TOP
//  register — so pin 5's duty cycle register is permanently
//  hijacked.  analogWrite(5, x) has ZERO effect.
//  Pin 6 uses Timer4A — a completely independent timer.
//
//  Final timer assignment (no conflicts):
//    Pin 2  →  Timer3B  (LF)
//    Pin 3  →  Timer3C  (LB)
//    Pin 4  →  Timer0B  (RF)
//    Pin 6  →  Timer4A  (RB)  ✓
// ================================================================


// ================================================================
//  PIN DEFINITIONS
// ================================================================
#define LF_DIR  22
#define LF_PWM   2

#define LB_DIR  24
#define LB_PWM   3

#define RF_DIR  26
#define RF_PWM   4

#define RB_DIR  36          // ← FIXED: was 34 (possible stuck-LOW). Now 36 ✓
#define RB_PWM   6          // ← FIXED: was 5  (Timer3A conflict).  Now 6  ✓

#define LED_PIN 13          // Onboard LED used as heartbeat


// ================================================================
//  MOTOR INVERT FLAGS
//  Set to 1 if a motor spins the wrong way for its position on
//  the chassis (e.g. mounted mirrored / gearbox on opposite side).
//  This is a SOFTWARE fix — no rewiring needed.
//
//  Default: all 0.
//  If RB still goes wrong way after DIR pin fix → set RB_INVERT 1.
// ================================================================
#define LF_INVERT  0
#define LB_INVERT  0
#define RF_INVERT  0
#define RB_INVERT  0        // ← change to 1 if RB still wrong direction


// ================================================================
//  TUNING
// ================================================================
#define MAX_SPEED       60    // ← change ONLY this during testing
                              //   bench test   →  60
                              //   first floor  →  100
                              //   normal use   →  180
                              //   full speed   →  255

#define DEADZONE        20    // ignore stick drift below this value

#define RAMP_UP_STEP    14    // acceleration step per 5 ms tick
                              //   full 0→255 ramp in ~105 ms (snappy but smooth)
                              //   increase toward 20 for even faster start
#define RAMP_DOWN_STEP  16    // deceleration step per 5 ms tick
                              //   full 255→0 stop in ~70 ms (quick stop)
                              //   increase toward 25 for even harder braking

#define LOOP_MS          5    // 200 Hz loop — reduced from 20 ms
                              //   gives ~5 ms input-to-motor latency
#define SERIAL_TIMEOUT 500    // ms — stop motors if comms lost

#define SELFTEST_SPEED  80    // PWM value used during on-demand self-test
#define SELFTEST_MS    400    // ms each motor runs during self-test


// ================================================================
//  RAMP STATE
// ================================================================
int targetLF  = 0,  targetLB  = 0,  targetRF  = 0,  targetRB  = 0;
int currentLF = 0,  currentLB = 0,  currentRF = 0,  currentRB = 0;

unsigned long lastPacketTime = 0;
unsigned long lastLEDTime    = 0;
bool          ledState       = false;
bool          motorsEnabled  = true;   // set false while TEST command runs


// ================================================================
//  applyInvert()
//  Applies the per-motor invert flag before sending to hardware.
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
//
//  The DIR pin is ALWAYS explicitly set — no floating state.
// ================================================================
void setMotor(uint8_t dirPin, uint8_t pwmPin, int speed) {
    speed = constrain(speed, -255, 255);

    if (speed > 0) {
        digitalWrite(dirPin, HIGH);
        analogWrite (pwmPin,  speed);
    }
    else if (speed < 0) {
        digitalWrite(dirPin, LOW);
        analogWrite (pwmPin, -speed);
    }
    else {
        digitalWrite(dirPin, LOW);
        analogWrite (pwmPin,  0);
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
    targetLF  = targetLB  = targetRF  = targetRB  = 0;
    currentLF = currentLB = currentRF = currentRB = 0;
}


// ================================================================
//  rampStep()
//  Moves 'current' one step toward 'target'.
//  Faster step when accelerating, slower step when braking.
// ================================================================
int rampStep(int current, int target) {
    if (current == target) return current;

    bool sameDir    = (current > 0 && target > 0) ||
                      (current < 0 && target < 0);
    bool speedingUp = sameDir && (abs(target) > abs(current));
    int  step       = speedingUp ? RAMP_UP_STEP : RAMP_DOWN_STEP;

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
//  applyRamp()
//  Called EVERY loop tick (5 ms) — not only when data arrives.
// ================================================================
void applyRamp() {
    if (!motorsEnabled) return;

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
//  dirChar()  —  returns 'F' (forward), 'R' (reverse), or 'S'
//  for clean one-character direction indicator in serial output.
// ================================================================
char dirChar(int speed) {
    if (speed > 0) return 'F';
    if (speed < 0) return 'R';
    return 'S';
}


// ================================================================
//  printBar()  —  ASCII speed bar  e.g.  [####      ] +80
//  width = number of chars inside brackets (default 10)
// ================================================================
void printBar(int speed, int maxSpeed, int width) {
    int filled = (int)((float)abs(speed) / maxSpeed * width + 0.5f);
    filled = constrain(filled, 0, width);

    Serial.print('[');
    for (int i = 0; i < width; i++) {
        Serial.print(i < filled ? '#' : ' ');
    }
    Serial.print(']');
    if (speed >= 0) Serial.print(' ');
    Serial.print(speed);
}


// ================================================================
//  processGamepad()
//  Takes joystick values, sets targetXX for all 4 motors,
//  and prints a detailed status block to Serial.
//
//  MECANUM FORMULA (top view):
//
//          FRONT
//    [LF] ──── [RF]
//     |            |
//    [LB] ──── [RB]
//          BACK
//
//    LF =  Vy + Vx      RF =  Vy - Vx
//    LB =  Vy - Vx      RB =  Vy + Vx
//
//  ROTATION:
//    CW  (rJoyX > 0):  lf=lb=+rJoyX,  rf=rb=−rJoyX
// ================================================================
void processGamepad(int joyX, int joyY, int rJoyX) {

    // ----------------------------------------------------------
    //  Deadzone
    // ----------------------------------------------------------
    if (abs(joyX)  < DEADZONE) joyX  = 0;
    if (abs(joyY)  < DEADZONE) joyY  = 0;
    if (abs(rJoyX) < DEADZONE) rJoyX = 0;

    // ----------------------------------------------------------
    //  Cap to MAX_SPEED
    // ----------------------------------------------------------
    joyX  = constrain(joyX,  -MAX_SPEED, MAX_SPEED);
    joyY  = constrain(joyY,  -MAX_SPEED, MAX_SPEED);
    rJoyX = constrain(rJoyX, -MAX_SPEED, MAX_SPEED);

    int lf = 0, lb = 0, rf = 0, rb = 0;

    // ----------------------------------------------------------
    //  Determine motion mode
    // ----------------------------------------------------------
    const char* mode;

    if (rJoyX != 0) {
        // PRIORITY 1 — ROTATE
        lf =  rJoyX;
        lb =  rJoyX;
        rf = -rJoyX;
        rb = -rJoyX;
        mode = (rJoyX > 0) ? "ROTATE CW" : "ROTATE CCW";
    }
    else if (joyX != 0 || joyY != 0) {
        // PRIORITY 2 — MOVE (mecanum)
        lf = joyY + joyX;
        lb = joyY - joyX;
        rf = joyY - joyX;
        rb = joyY + joyX;

        if      (joyX == 0 && joyY > 0)  mode = "FORWARD";
        else if (joyX == 0 && joyY < 0)  mode = "BACKWARD";
        else if (joyY == 0 && joyX > 0)  mode = "STRAFE RIGHT";
        else if (joyY == 0 && joyX < 0)  mode = "STRAFE LEFT";
        else if (joyY > 0  && joyX > 0)  mode = "FWD-RIGHT";
        else if (joyY > 0  && joyX < 0)  mode = "FWD-LEFT";
        else if (joyY < 0  && joyX > 0)  mode = "BWD-RIGHT";
        else                              mode = "BWD-LEFT";
    }
    else {
        // PRIORITY 3 — STOP
        mode = "STOP";
    }

    // ----------------------------------------------------------
    //  Clamp to prevent diagonal overflow
    // ----------------------------------------------------------
    lf = constrain(lf, -MAX_SPEED, MAX_SPEED);
    lb = constrain(lb, -MAX_SPEED, MAX_SPEED);
    rf = constrain(rf, -MAX_SPEED, MAX_SPEED);
    rb = constrain(rb, -MAX_SPEED, MAX_SPEED);

    // Write to ramp targets
    targetLF = lf;
    targetLB = lb;
    targetRF = rf;
    targetRB = rb;

    // ----------------------------------------------------------
    //  ===  SERIAL OUTPUT  ===
    //
    //  ┌──────────────────────────────────────────────┐
    //  │  MODE: FORWARD                               │
    //  ├──────────────────────────────────────────────┤
    //  │  INPUT   LX=  0  LY=+60  RX=  0             │
    //  │  TARGET  LF=+60[######    ]  LB=+60[######    ]│
    //  │          RF=+60[######    ]  RB=+60[######    ]│
    //  │  ACTUAL  LF=+48[#####     ]  DIR=F            │
    //  │          ...                                  │
    //  └──────────────────────────────────────────────┘
    // ----------------------------------------------------------
    Serial.println(F("================================================"));
    Serial.print  (F("  MODE  : "));
    Serial.println(mode);
    Serial.println(F("------------------------------------------------"));

    // Input row
    Serial.print(F("  INPUT   LX="));
    if (joyX >= 0) Serial.print('+');
    Serial.print(joyX);
    Serial.print(F("  LY="));
    if (joyY >= 0) Serial.print('+');
    Serial.print(joyY);
    Serial.print(F("  RX="));
    if (rJoyX >= 0) Serial.print('+');
    Serial.println(rJoyX);

    // Target row
    Serial.print(F("  TARGET  LF="));
    if (lf >= 0) Serial.print('+');
    printBar(lf, MAX_SPEED, 10);
    Serial.print(F("  RF="));
    if (rf >= 0) Serial.print('+');
    printBar(rf, MAX_SPEED, 10);
    Serial.println();

    Serial.print(F("           LB="));
    if (lb >= 0) Serial.print('+');
    printBar(lb, MAX_SPEED, 10);
    Serial.print(F("  RB="));
    if (rb >= 0) Serial.print('+');
    printBar(rb, MAX_SPEED, 10);
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
//  motorSelfTest()
//  Spins each motor forward then backward briefly so you can
//  visually confirm each wheel turns the correct direction.
//  Triggered ON DEMAND via "TEST\n" serial command only.
//  NOT called on startup.
// ================================================================
void motorSelfTest() {
    motorsEnabled = false;
    stopAll();

    Serial.println(F(""));
    Serial.println(F(">>> SELF-TEST START — watch each wheel <<<"));

    struct MotorDef {
        const char* name;
        uint8_t     dirPin;
        uint8_t     pwmPin;
    };

    MotorDef motors[] = {
        {"LF (Left  Front)", LF_DIR, LF_PWM},
        {"LB (Left  Back )", LB_DIR, LB_PWM},
        {"RF (Right Front)", RF_DIR, RF_PWM},
        {"RB (Right Back )", RB_DIR, RB_PWM},
    };

    for (int i = 0; i < 4; i++) {
        Serial.print(F("  Testing "));
        Serial.print(motors[i].name);
        Serial.print(F("  → FWD ... "));
        setMotor(motors[i].dirPin, motors[i].pwmPin,  SELFTEST_SPEED);
        delay(SELFTEST_MS);

        Serial.print(F("REV ... "));
        setMotor(motors[i].dirPin, motors[i].pwmPin, -SELFTEST_SPEED);
        delay(SELFTEST_MS);

        setMotor(motors[i].dirPin, motors[i].pwmPin,  0);
        Serial.println(F("DONE"));
        delay(150);
    }

    Serial.println(F(">>> SELF-TEST COMPLETE <<<"));
    Serial.println(F("    If RB only spun one way, set RB_INVERT 1"));
    Serial.println(F(""));

    motorsEnabled    = true;
    lastPacketTime   = millis();   // reset timeout so car doesn't e-stop
}


// ================================================================
//  SERIAL PARSER
//  Reads bytes until a complete <...> packet is received.
//  Returns true and fills rxBuf[] when packet is complete.
//  Also intercepts plain-text commands  TEST  and  PING.
// ================================================================
const int BUF_SIZE = 32;
char      rxBuf[BUF_SIZE];
int       rxIdx    = 0;
bool      inPacket = false;

// Line buffer for plain-text commands (TEST / PING)
char      cmdBuf[BUF_SIZE];
int       cmdIdx = 0;

bool readPacket() {
    while (Serial.available()) {
        char c = Serial.read();

        // ---- structured packet parser  <LX,LY,RX> ----
        if (c == '<') {
            inPacket = true;
            rxIdx    = 0;
            cmdIdx   = 0;        // reset cmd buffer on new packet
        }
        else if (c == '>' && inPacket) {
            rxBuf[rxIdx] = '\0';
            inPacket     = false;
            rxIdx        = 0;
            return true;
        }
        else if (inPacket && rxIdx < BUF_SIZE - 1) {
            rxBuf[rxIdx++] = c;
        }

        // ---- plain-text command parser (newline terminated) ----
        else if (!inPacket) {
            if (c == '\n' || c == '\r') {
                if (cmdIdx > 0) {
                    cmdBuf[cmdIdx] = '\0';
                    cmdIdx = 0;

                    if (strcmp(cmdBuf, "TEST") == 0) {
                        motorSelfTest();
                    }
                    else if (strcmp(cmdBuf, "PING") == 0) {
                        Serial.println(F("PONG"));
                    }
                }
            }
            else if (cmdIdx < BUF_SIZE - 1) {
                cmdBuf[cmdIdx++] = c;
            }
        }
    }
    return false;
}


// ================================================================
//  heartbeat()
//  Blinks LED on pin 13:
//    • Fast blink (200 ms) = active packets coming in
//    • Slow blink (800 ms) = idle / waiting
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
    Serial.begin(115200);

    Serial.println(F("================================================"));
    Serial.println(F("  MECANUM CAR  v2.2  —  Arduino Mega 2560"));
    Serial.println(F("================================================"));
    Serial.print  (F("  MAX_SPEED   = ")); Serial.println(MAX_SPEED);
    Serial.print  (F("  DEADZONE    = ")); Serial.println(DEADZONE);
    Serial.print  (F("  RAMP UP     = ")); Serial.println(RAMP_UP_STEP);
    Serial.print  (F("  RAMP DOWN   = ")); Serial.println(RAMP_DOWN_STEP);
    Serial.print  (F("  TIMEOUT     = ")); Serial.print(SERIAL_TIMEOUT); Serial.println(F(" ms"));
    Serial.println(F("  RB_DIR      = pin 36  (Timer-safe, reliable)"));
    Serial.println(F("  RB_PWM      = pin 6   (Timer4A, no conflict)"));
    Serial.print  (F("  INVERT FLAGS: LF=")); Serial.print(LF_INVERT);
    Serial.print  (F(" LB="));              Serial.print(LB_INVERT);
    Serial.print  (F(" RF="));              Serial.print(RF_INVERT);
    Serial.print  (F(" RB="));              Serial.println(RB_INVERT);
    Serial.println(F("------------------------------------------------"));
    Serial.println(F("  Serial commands (send as plain text + Enter):"));
    Serial.println(F("    TEST  — run motor self-test sequence"));
    Serial.println(F("    PING  — connectivity check (replies PONG)"));
    Serial.println(F("================================================"));

    // Motor pins
    pinMode(LF_DIR, OUTPUT); pinMode(LF_PWM, OUTPUT);
    pinMode(LB_DIR, OUTPUT); pinMode(LB_PWM, OUTPUT);
    pinMode(RF_DIR, OUTPUT); pinMode(RF_PWM, OUTPUT);
    pinMode(RB_DIR, OUTPUT); pinMode(RB_PWM, OUTPUT);
    pinMode(LED_PIN, OUTPUT);

    stopAll();

    lastPacketTime = millis();
    Serial.println(F("Ready. Run ps4_to_arduino.py on your PC."));
    Serial.println(F("================================================"));
}


// ================================================================
//  LOOP  (runs every ~5 ms = 200 Hz)
// ================================================================
void loop() {

    bool activeComms = (millis() - lastPacketTime < SERIAL_TIMEOUT);

    // Step 1 — parse incoming serial packet or command
    if (readPacket()) {
        int lx, ly, rx;
        if (sscanf(rxBuf, "%d,%d,%d", &lx, &ly, &rx) == 3) {
            lastPacketTime = millis();
            processGamepad(lx, ly, rx);
        }
        else {
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
