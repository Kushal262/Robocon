// ================================================================
//  MECANUM WHEEL CAR — Path Follower
//  Arduino Mega 2560 + Rhino MDD20Amp x2 + 4 DC Motors
//
//  Receives packets from Python map game:
//    <LX,LY,RX>\n
//    LX : -255 to +255  (strafe)
//    LY : -255 to +255  (forward/back)
//    RX : -255 to +255  (rotate)
//
//  Commands:
//    PING  → replies PONG
//    TEST  → runs motor self test
// ================================================================

// ── PIN CONFIG (same as original) ────────────────────────────────
#define LF_DIR  22
#define LF_PWM   2

#define LB_DIR  24                                                                                      
#define LB_PWM   3

#define RF_DIR  26
#define RF_PWM   4

#define RB_DIR  36
#define RB_PWM   6

#define LED_PIN 13

// ── INVERT FLAGS ─────────────────────────────────────────────────
// Set to 1 if a motor spins wrong direction
#define LF_INVERT  0
#define LB_INVERT  0
#define RF_INVERT  0
#define RB_INVERT  0

// ── TUNING ───────────────────────────────────────────────────────
#define MAX_SPEED      100  // max PWM — must match DRIVE_SPEED in Python
#define DEADZONE        15
#define RAMP_STEP       25   // ramp per 5ms tick (snappy for path following)
#define LOOP_MS          5
#define TIMEOUT_MS     800   // stop if no packet for this long

// ── STATE ────────────────────────────────────────────────────────
int targetLF = 0, targetLB = 0, targetRF = 0, targetRB = 0;
int  currLF  = 0,  currLB  = 0,  currRF  = 0,  currRB  = 0;

unsigned long lastPacket = 0;
unsigned long lastLED    = 0;
bool ledState = false;


// ── setMotor ─────────────────────────────────────────────────────
void setMotor(uint8_t dir, uint8_t pwm, int speed) {
    speed = constrain(speed, -255, 255);
    if (speed > 0) {
        digitalWrite(dir, HIGH);
        analogWrite(pwm, speed);
    } else if (speed < 0) {
        digitalWrite(dir, LOW);
        analogWrite(pwm, -speed);
    } else {
        digitalWrite(dir, LOW);
        analogWrite(pwm, 0);
    }
}


// ── stopAll ──────────────────────────────────────────────────────
void stopAll() {
    setMotor(LF_DIR, LF_PWM, 0);
    setMotor(LB_DIR, LB_PWM, 0);
    setMotor(RF_DIR, RF_PWM, 0);
    setMotor(RB_DIR, RB_PWM, 0);
    targetLF = targetLB = targetRF = targetRB = 0;
    currLF   = currLB   = currRF   = currRB   = 0;
}


// ── ramp ─────────────────────────────────────────────────────────
int ramp(int cur, int tgt) {
    if (cur == tgt) return cur;
    if (tgt > cur) { cur += RAMP_STEP; if (cur > tgt) cur = tgt; }
    else           { cur -= RAMP_STEP; if (cur < tgt) cur = tgt; }
    return cur;
}


// ── applyRamp ────────────────────────────────────────────────────
void applyRamp() {
    currLF = ramp(currLF, targetLF);
    currLB = ramp(currLB, targetLB);
    currRF = ramp(currRF, targetRF);
    currRB = ramp(currRB, targetRB);

    setMotor(LF_DIR, LF_PWM, LF_INVERT ? -currLF : currLF);
    setMotor(LB_DIR, LB_PWM, LB_INVERT ? -currLB : currLB);
    setMotor(RF_DIR, RF_PWM, RF_INVERT ? -currRF : currRF);
    setMotor(RB_DIR, RB_PWM, RB_INVERT ? -currRB : currRB);
}


// ── drive ────────────────────────────────────────────────────────
// Mecanum formula:
//   LF = LY + LX    RF = LY - LX
//   LB = LY - LX    RB = LY + LX
// Rotation overrides translation.
void drive(int lx, int ly, int rx) {

    // Deadzone
    if (abs(lx) < DEADZONE) lx = 0;
    if (abs(ly) < DEADZONE) ly = 0;
    if (abs(rx) < DEADZONE) rx = 0;

    // Instant stop on all-zero packet
    if (lx == 0 && ly == 0 && rx == 0) {
        stopAll();
        return;
    }

    int lf, lb, rf, rb;

    if (rx != 0) {
        // Rotation
        rx = constrain(rx, -MAX_SPEED, MAX_SPEED);
        lf = lb =  rx;
        rf = rb = -rx;
    } else {
        // Translation
        lx = constrain(lx, -MAX_SPEED, MAX_SPEED);
        ly = constrain(ly, -MAX_SPEED, MAX_SPEED);
        lf = ly + lx;
        lb = ly - lx;
        rf = ly - lx;
        rb = ly + lx;
    }

    targetLF = constrain(lf, -MAX_SPEED, MAX_SPEED);
    targetLB = constrain(lb, -MAX_SPEED, MAX_SPEED);
    targetRF = constrain(rf, -MAX_SPEED, MAX_SPEED);
    targetRB = constrain(rb, -MAX_SPEED, MAX_SPEED);

    Serial.print(F("LF=")); Serial.print(targetLF);
    Serial.print(F(" LB=")); Serial.print(targetLB);
    Serial.print(F(" RF=")); Serial.print(targetRF);
    Serial.print(F(" RB=")); Serial.println(targetRB);
}


// ── selfTest ─────────────────────────────────────────────────────
void selfTest() {
    stopAll();
    Serial.println(F("=== SELF TEST ==="));
    const char* names[] = {"LF","LB","RF","RB"};
    uint8_t dirs[] = {LF_DIR, LB_DIR, RF_DIR, RB_DIR};
    uint8_t pwms[] = {LF_PWM, LB_PWM, RF_PWM, RB_PWM};
    for (int i = 0; i < 4; i++) {
        Serial.print(names[i]); Serial.print(F(" FWD..."));
        setMotor(dirs[i], pwms[i], 80);  delay(400);
        Serial.print(F("REV..."));
        setMotor(dirs[i], pwms[i], -80); delay(400);
        setMotor(dirs[i], pwms[i], 0);
        Serial.println(F("OK"));
        delay(150);
    }
    Serial.println(F("=== DONE ==="));
    lastPacket = millis();
}


// ── Serial parser ────────────────────────────────────────────────
char rxBuf[32];
int  rxIdx    = 0;
bool inPacket = false;
char cmdBuf[32];
int  cmdIdx   = 0;

bool readPacket() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '<') {
            inPacket = true; rxIdx = 0; cmdIdx = 0;
        } else if (c == '>' && inPacket) {
            rxBuf[rxIdx] = '\0';
            inPacket = false; rxIdx = 0;
            return true;
        } else if (inPacket && rxIdx < 31) {
            rxBuf[rxIdx++] = c;
        } else if (!inPacket) {
            if (c == '\n' || c == '\r') {
                if (cmdIdx > 0) {
                    cmdBuf[cmdIdx] = '\0'; cmdIdx = 0;
                    if      (strcmp(cmdBuf, "PING") == 0) Serial.println(F("PONG"));
                    else if (strcmp(cmdBuf, "TEST") == 0) selfTest();
                }
            } else if (cmdIdx < 31) {
                cmdBuf[cmdIdx++] = c;
            }
        }
    }
    return false;
}


// ── Heartbeat LED ────────────────────────────────────────────────
void heartbeat(bool active) {
    unsigned long interval = active ? 200 : 800;
    if (millis() - lastLED >= interval) {
        lastLED  = millis();
        ledState = !ledState;
        digitalWrite(LED_PIN, ledState);
    }
}


// ── setup ────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    pinMode(LF_DIR, OUTPUT); pinMode(LF_PWM, OUTPUT);
    pinMode(LB_DIR, OUTPUT); pinMode(LB_PWM, OUTPUT);
    pinMode(RF_DIR, OUTPUT); pinMode(RF_PWM, OUTPUT);
    pinMode(RB_DIR, OUTPUT); pinMode(RB_PWM, OUTPUT);
    pinMode(LED_PIN, OUTPUT);

    stopAll();
    lastPacket = millis();

    Serial.println(F("=== Mecanum Path Follower Ready ==="));
    Serial.println(F("Waiting for Python map game..."));
    Serial.println(F("Commands: PING | TEST"));
}


// ── loop ─────────────────────────────────────────────────────────
void loop() {
    bool active = (millis() - lastPacket < TIMEOUT_MS);

    if (readPacket()) {
        int lx, ly, rx;
        if (sscanf(rxBuf, "%d,%d,%d", &lx, &ly, &rx) == 3) {
            lastPacket = millis();
            drive(lx, ly, rx);
        }
    }

    // Safety timeout
    if (!active) {
        targetLF = targetLB = targetRF = targetRB = 0;
    }

    applyRamp();
    heartbeat(active);
    delay(LOOP_MS);
}
