/*
 * ╔══════════════════════════════════════════════════════════════╗
 * ║  R1 - Arduino Mega "FLASH ONCE" Firmware                   ║
 * ║  Robocon 2026 "Kung Fu Quest"                              ║
 * ╚══════════════════════════════════════════════════════════════╝
 * 
 * COMMANDS (from RPi):
 *   <M,LF,RF,LB,RB>    → Motor speeds (-255 to +255 each)
 *   <P,id,state>        → Pneumatic control (id=1or2, state=0or1)
 *   <E>                 → Request encoder ticks
 * 
 * REPLIES (to RPi):
 *   E,lf,rf,lb,rb       → Encoder ticks (then resets)
 * 
 * WIRING:
 *   Motors (Cytron MDDS30 Driver 1 — Left):
 *     LF → PWM:9  DIR:35
 *     LB → PWM:8  DIR:36
 *   Motors (Cytron MDDS30 Driver 2 — Right):
 *     RF → PWM:5  DIR:33
 *     RB → PWM:4  DIR:34
 *   Pneumatics (Cytron MDDS30 Driver 3):
 *     P1 → PWM:6  DIR:37
 *     P2 → PWM:7  DIR:38
 *   Encoders:
 *     LF(A:20 B:26) RF(A:3 B:23) LB(A:19 B:25) RB(A:2 B:22)
 * 
 * ⚠️ RE-FLASH ONLY IF: You change physical pin wiring.
 */


// ══════════════════════════════════════════════════
// PIN CONFIG — Change here if you rewire, then flash
// ══════════════════════════════════════════════════

// ── Motor Driver Pins (MDDS30 #1 and #2) ──
#define LF_PWM  9
#define LF_DIR  34
#define LB_PWM  8
#define LB_DIR  35
#define RF_PWM  5
#define RF_DIR  32
#define RB_PWM  4
#define RB_DIR  33

// ── Pneumatic Pins (MDDS30 #3) ──
// If you only need PWM (no DIR), just leave DIR wired but unused.
// RPi sends PWM=255 for ON and PWM=0 for OFF via <P,id,state>
#define P1_PWM  7
#define P1_DIR  30
#define P2_PWM  6
#define P2_DIR  31

// ── Encoder Pins ──
#define LF_ENC_A  20
#define LF_ENC_B  26
#define RF_ENC_A  3
#define RF_ENC_B  23
#define LB_ENC_A  19
#define LB_ENC_B  25
#define RB_ENC_A  2
#define RB_ENC_B  22

// ── Safety ──
#define TIMEOUT_MS  300


// ══════════════════════════════════════════════════
// VARIABLES
// ══════════════════════════════════════════════════

// Encoder ticks
volatile long encLF = 0, encRF = 0, encLB = 0, encRB = 0;

// Serial parsing
char inputBuffer[48];
int bufferIndex = 0;
bool receiving = false;
unsigned long lastCmdTime = 0;


// ══════════════════════════════════════════════════
// ENCODER ISRs
// ══════════════════════════════════════════════════
void isrLF() { encLF += digitalRead(LF_ENC_B) ? 1 : -1; }
void isrRF() { encRF += digitalRead(RF_ENC_B) ? 1 : -1; }
void isrLB() { encLB += digitalRead(LB_ENC_B) ? 1 : -1; }
void isrRB() { encRB += digitalRead(RB_ENC_B) ? 1 : -1; }


// ══════════════════════════════════════════════════
// SETUP
// ══════════════════════════════════════════════════
void setup() {
    Serial.begin(115200);

    // Motor pins
    pinMode(LF_PWM, OUTPUT); pinMode(LF_DIR, OUTPUT);
    pinMode(LB_PWM, OUTPUT); pinMode(LB_DIR, OUTPUT);
    pinMode(RF_PWM, OUTPUT); pinMode(RF_DIR, OUTPUT);
    pinMode(RB_PWM, OUTPUT); pinMode(RB_DIR, OUTPUT);

    // Pneumatic pins
    pinMode(P1_PWM, OUTPUT); pinMode(P1_DIR, OUTPUT);
    pinMode(P2_PWM, OUTPUT); pinMode(P2_DIR, OUTPUT);

    // Set pneumatic DIR pins LOW (forward direction, valve open)
    digitalWrite(P1_DIR, LOW);
    digitalWrite(P2_DIR, LOW);

    // Encoder pins
    pinMode(LF_ENC_A, INPUT_PULLUP); pinMode(LF_ENC_B, INPUT_PULLUP);
    pinMode(RF_ENC_A, INPUT_PULLUP); pinMode(RF_ENC_B, INPUT_PULLUP);
    pinMode(LB_ENC_A, INPUT_PULLUP); pinMode(LB_ENC_B, INPUT_PULLUP);
    pinMode(RB_ENC_A, INPUT_PULLUP); pinMode(RB_ENC_B, INPUT_PULLUP);

    // Attach encoder interrupts
    attachInterrupt(digitalPinToInterrupt(LF_ENC_A), isrLF, RISING);
    attachInterrupt(digitalPinToInterrupt(RF_ENC_A), isrRF, RISING);
    attachInterrupt(digitalPinToInterrupt(LB_ENC_A), isrLB, RISING);
    attachInterrupt(digitalPinToInterrupt(RB_ENC_A), isrRB, RISING);

    // Everything off at start
    stopAllMotors();
    analogWrite(P1_PWM, 0);
    analogWrite(P2_PWM, 0);

    Serial.println("[R1] Firmware Ready — Motors + Pneumatics");
}


// ══════════════════════════════════════════════════
// MAIN LOOP
// ══════════════════════════════════════════════════
void loop() {
    recvSerial();

    // Safety: stop MOTORS if no command for 300ms
    // Pneumatics keep their last state (no auto-off on timeout)
    if (millis() - lastCmdTime > TIMEOUT_MS) {
        stopAllMotors();
    }
}


// ══════════════════════════════════════════════════
// SERIAL RECEIVE
// ══════════════════════════════════════════════════
void recvSerial() {
    while (Serial.available() > 0) {
        char c = Serial.read();
        if (c == '<') {
            receiving = true;
            bufferIndex = 0;
            memset(inputBuffer, 0, sizeof(inputBuffer));
        }
        else if (c == '>') {
            receiving = false;
            processMessage();
        }
        else if (receiving && bufferIndex < 46) {
            inputBuffer[bufferIndex++] = c;
        }
    }
}


// ══════════════════════════════════════════════════
// MESSAGE ROUTER
// ══════════════════════════════════════════════════
// First char = type: M=motor, P=pneumatic, E=encoder
void processMessage() {
    char type = inputBuffer[0];

    if (type == 'M') {
        // ── MOTOR: <M,LF,RF,LB,RB> ──
        int mLF, mRF, mLB, mRB;
        if (sscanf(inputBuffer + 2, "%d,%d,%d,%d", &mLF, &mRF, &mLB, &mRB) == 4) {
            setMotor(LF_DIR, LF_PWM, constrain(mLF, -255, 255));
            setMotor(RF_DIR, RF_PWM, constrain(mRF, -255, 255));
            setMotor(LB_DIR, LB_PWM, constrain(mLB, -255, 255));
            setMotor(RB_DIR, RB_PWM, constrain(mRB, -255, 255));
            lastCmdTime = millis();
        }
    }
    else if (type == 'P') {
        // ── PNEUMATIC: <P,id,state> ──
        // id = 1 or 2
        // state = 0 (OFF) or 1 (ON, full PWM 255)
        int id, state;
        if (sscanf(inputBuffer + 2, "%d,%d", &id, &state) == 2) {
            int pwmVal = (state > 0) ? 255 : 0;

            if (id == 1) {
                analogWrite(P1_PWM, pwmVal);
            }
            else if (id == 2) {
                analogWrite(P2_PWM, pwmVal);
            }
            lastCmdTime = millis();
        }
    }
    else if (type == 'E') {
        // ── ENCODER: <E> ──
        noInterrupts();
        long lf = encLF; long rf = encRF;
        long lb = encLB; long rb = encRB;
        encLF = 0; encRF = 0; encLB = 0; encRB = 0;
        interrupts();

        Serial.print("E,");
        Serial.print(lf); Serial.print(",");
        Serial.print(rf); Serial.print(",");
        Serial.print(lb); Serial.print(",");
        Serial.println(rb);
        lastCmdTime = millis();
    }
    // Future: S=servo, etc.
}


// ══════════════════════════════════════════════════
// MOTOR CONTROL
// ══════════════════════════════════════════════════
void setMotor(int dirPin, int pwmPin, int speed) {
    if (speed > 0) {
        digitalWrite(dirPin, LOW);
        analogWrite(pwmPin, speed);
    }
    else if (speed < 0) {
        digitalWrite(dirPin, HIGH);
        analogWrite(pwmPin, -speed);
    }
    else {
        digitalWrite(dirPin, LOW);
        analogWrite(pwmPin, 0);
    }
}

void stopAllMotors() {
    analogWrite(LF_PWM, 0);
    analogWrite(RF_PWM, 0);
    analogWrite(LB_PWM, 0);
    analogWrite(RB_PWM, 0);
    // Pneumatics NOT stopped here — they hold state
}
