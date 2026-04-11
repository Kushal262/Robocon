/*
 * ╔══════════════════════════════════════════════════════════════╗
 * ║  R1 - Arduino Mega "FLASH ONCE" Firmware                   ║
 * ║  Robocon 2026 "Kung Fu Quest"                              ║
 * ╚══════════════════════════════════════════════════════════════╝
 *
 * COMMANDS (from RPi):
 *   <M,LF,RF,LB,RB>           → Drive motor speeds (-255 to +255)
 *   <X,m5_pwm,m6_pwm>         → Extra motor base PWM (-255 to +255 each)
 *   <XCFG,sync_strength_x100> → Sync strength × 100
 *   <E>                       → Request drive encoder ticks
 *   <EX>                      → Request M5/M6 encoder ticks
 *   <S,id,pos>                → Servo position (id=1or2, pos degrees)
 *   <SCFG,id,speed,min,max>   → Servo sweep speed + limits
 *
 * REPLIES (to RPi):
 *   E,lf,rf,lb,rb             → Drive encoder ticks (resets after send)
 *   EX,m5,m6                  → Extra motor encoder ticks (resets after send)
 *
 * WIRING — Drive Motors:
 *   LF → PWM:7  DIR:48    RF → PWM:11 DIR:36
 *   LB → PWM:6  DIR:49    RB → PWM:10 DIR:37
 *
 * WIRING — Extra Motors (M5/M6):
 *   M5 → PWM:9  DIR:42    M6 → PWM:8  DIR:43

 *
 * WIRING — Drive Encoders:
 *   LF(A:20 B:26)  RF(A:3 B:23)  LB(A:19 B:25)  RB(A:2 B:22)
 *
 * WIRING — Extra Motor Encoders (interrupt-capable A pins):
 *   M5(A:18 B:24)  M6(A:21 B:27)
 *
 * WIRING — Servos:
 *   S1 → Pin 12    S2 → Pin 13
 *
 * ⚠️  RE-FLASH ONLY IF: You change physical pin wiring.
 *     All logic/tuning lives in config.json on the RPi.
 */

#include <Servo.h>


// ══════════════════════════════════════════════════
// PIN CONFIG — Change here if you rewire, then flash
// ══════════════════════════════════════════════════

// ── Drive Motor Pins ──
#define LF_PWM  7
#define LF_DIR  48
#define LB_PWM  6
#define LB_DIR  49
#define RF_PWM  11
#define RF_DIR  36
#define RB_PWM  10
#define RB_DIR  37

// ── Extra Motor Pins (M5, M6) ──
#define M5_PWM  9
#define M5_DIR  42
#define M6_PWM  8
#define M6_DIR  43


// ── Drive Encoder Pins ──
#define LF_ENC_A  20
#define LF_ENC_B  26
#define RF_ENC_A  3
#define RF_ENC_B  23
#define LB_ENC_A  19
#define LB_ENC_B  25
#define RB_ENC_A  2
#define RB_ENC_B  22

// ── Extra Motor Encoder Pins (A must be interrupt-capable) ──
#define M5_ENC_A  18
#define M5_ENC_B  24
#define M6_ENC_A  21
#define M6_ENC_B  27

// ── Servo Pins ──
#define S1_PIN  12
#define S2_PIN  13

// ── Safety ──
#define TIMEOUT_MS       300
#define PID_INTERVAL_MS  20
#define MAX_INTEGRAL     5000.0f
#define SERVO_STEP_MS    20


// ══════════════════════════════════════════════════
// VARIABLES
// ══════════════════════════════════════════════════

// Drive encoder ticks (volatile, updated by ISR)
volatile long encLF = 0, encRF = 0, encLB = 0, encRB = 0;

// Extra motor encoder ticks (volatile, updated by ISR)
volatile long encM5 = 0, encM6 = 0;

// ── Extra Motor Sync state ──
float sync_kp       = 1.0f;

int   base_pwm_m5   = 0;
int   base_pwm_m6   = 0;
long  sync_ticks_m5 = 0;
long  sync_ticks_m6 = 0;
long  total_enc_m5  = 0;
long  total_enc_m6  = 0;
unsigned long last_pid_time = 0;

// ── Servos ──
Servo servo1, servo2;
int target_s1  = 90,  current_s1  = 90;
int target_s2  = 90,  current_s2  = 90;
int servo1_speed = 5, servo2_speed = 5;
int servo1_min   = 0, servo1_max   = 180;
int servo2_min   = 0, servo2_max   = 180;
unsigned long last_servo_time = 0;

// ── Serial parsing ──
char inputBuffer[64];
int  bufferIndex = 0;
bool receiving   = false;
unsigned long lastCmdTime = 0;


// ══════════════════════════════════════════════════
// ENCODER ISRs
// ══════════════════════════════════════════════════
void isrLF() { encLF += digitalRead(LF_ENC_B) ? 1 : -1; }
void isrRF() { encRF += digitalRead(RF_ENC_B) ? 1 : -1; }
void isrLB() { encLB += digitalRead(LB_ENC_B) ? 1 : -1; }
void isrRB() { encRB += digitalRead(RB_ENC_B) ? 1 : -1; }
void isrM5() { encM5 += digitalRead(M5_ENC_B) ? 1 : -1; }
void isrM6() { encM6 += digitalRead(M6_ENC_B) ? 1 : -1; }


// ══════════════════════════════════════════════════
// SETUP
// ══════════════════════════════════════════════════
void setup() {
    Serial.begin(115200);

    // ── Drive motor pins ──
    pinMode(LF_PWM, OUTPUT); pinMode(LF_DIR, OUTPUT);
    pinMode(LB_PWM, OUTPUT); pinMode(LB_DIR, OUTPUT);
    pinMode(RF_PWM, OUTPUT); pinMode(RF_DIR, OUTPUT);
    pinMode(RB_PWM, OUTPUT); pinMode(RB_DIR, OUTPUT);

    // ── Extra motor pins ──
    pinMode(M5_PWM, OUTPUT); pinMode(M5_DIR, OUTPUT);
    pinMode(M6_PWM, OUTPUT); pinMode(M6_DIR, OUTPUT);



    // ── Drive encoder pins ──
    pinMode(LF_ENC_A, INPUT_PULLUP); pinMode(LF_ENC_B, INPUT_PULLUP);
    pinMode(RF_ENC_A, INPUT_PULLUP); pinMode(RF_ENC_B, INPUT_PULLUP);
    pinMode(LB_ENC_A, INPUT_PULLUP); pinMode(LB_ENC_B, INPUT_PULLUP);
    pinMode(RB_ENC_A, INPUT_PULLUP); pinMode(RB_ENC_B, INPUT_PULLUP);

    // ── Extra encoder pins ──
    pinMode(M5_ENC_A, INPUT_PULLUP); pinMode(M5_ENC_B, INPUT_PULLUP);
    pinMode(M6_ENC_A, INPUT_PULLUP); pinMode(M6_ENC_B, INPUT_PULLUP);

    // ── Attach encoder interrupts ──
    attachInterrupt(digitalPinToInterrupt(LF_ENC_A), isrLF, RISING);
    attachInterrupt(digitalPinToInterrupt(RF_ENC_A), isrRF, RISING);
    attachInterrupt(digitalPinToInterrupt(LB_ENC_A), isrLB, RISING);
    attachInterrupt(digitalPinToInterrupt(RB_ENC_A), isrRB, RISING);
    attachInterrupt(digitalPinToInterrupt(M5_ENC_A), isrM5, RISING);
    attachInterrupt(digitalPinToInterrupt(M6_ENC_A), isrM6, RISING);

    // ── Servos — default 90° ──
    servo1.attach(S1_PIN);
    servo2.attach(S2_PIN);
    servo1.write(90);
    servo2.write(90);

    // ── Everything off at start ──
    stopAllMotors();

    last_pid_time   = millis();
    last_servo_time = millis();

    Serial.println("[R1] Firmware Ready — Drive + Extra Motors + Servos");
}


// ══════════════════════════════════════════════════
// MAIN LOOP
// ══════════════════════════════════════════════════
void loop() {
    recvSerial();

    // Safety timeout: stop ALL motors if no command for TIMEOUT_MS
    if (millis() - lastCmdTime > TIMEOUT_MS) {
        stopAllMotors();
        base_pwm_m5 = 0;
        base_pwm_m6 = 0;
    }

    pidStep();
    updateServos();
}


// ══════════════════════════════════════════════════
// SERIAL RECEIVE
// ══════════════════════════════════════════════════
void recvSerial() {
    while (Serial.available() > 0) {
        char c = Serial.read();
        if (c == '<') {
            receiving    = true;
            bufferIndex  = 0;
            memset(inputBuffer, 0, sizeof(inputBuffer));
        } else if (c == '>') {
            receiving = false;
            processMessage();
        } else if (receiving && bufferIndex < 62) {
            inputBuffer[bufferIndex++] = c;
        }
    }
}


// ══════════════════════════════════════════════════
// MESSAGE ROUTER
// ══════════════════════════════════════════════════
void processMessage() {
    char t0 = inputBuffer[0];
    char t1 = (bufferIndex > 1) ? inputBuffer[1] : '\0';

    // ── DRIVE MOTORS: <M,LF,RF,LB,RB> ──
    if (t0 == 'M') {
        char* token = strtok(inputBuffer + 2, ",");
        int mLF = token ? atoi(token) : 0;
        token = strtok(NULL, ",");
        int mRF = token ? atoi(token) : 0;
        token = strtok(NULL, ",");
        int mLB = token ? atoi(token) : 0;
        token = strtok(NULL, ",");
        int mRB = token ? atoi(token) : 0;

        setMotor(LF_DIR, LF_PWM, constrain(mLF, -255, 255));
        setMotor(RF_DIR, RF_PWM, constrain(mRF, -255, 255));
        setMotor(LB_DIR, LB_PWM, constrain(mLB, -255, 255));
        setMotor(RB_DIR, RB_PWM, constrain(mRB, -255, 255));
        lastCmdTime = millis();
    }

    // ── EXTRA MOTORS: <X,m5_pwm,m6_pwm> ──
    // ── SYNC CONFIG:  <XCFG,sync_strength_x100> ──
    else if (t0 == 'X') {
        if (t1 == 'C') {
            // XCFG — Sync config (gain × 100)
            char* token = strtok(inputBuffer + 5, ",");
            if (token) {
                sync_kp = atoi(token) / 100.0f;
            }
        } else {
            // X — extra motor base PWM (-255 to +255)
            char* token = strtok(inputBuffer + 2, ",");
            int p5 = token ? atoi(token) : 0;
            token = strtok(NULL, ",");
            int p6 = token ? atoi(token) : 0;

            // Reset sync state on direction change or stop
            if ((p5 == 0 && p6 == 0) || 
                (p5 * base_pwm_m5 <= 0) || 
                (p6 * base_pwm_m6 <= 0)) {
                sync_ticks_m5 = 0;
                sync_ticks_m6 = 0;
            }
            base_pwm_m5 = constrain(p5, -255, 255);
            base_pwm_m6 = constrain(p6, -255, 255);
            lastCmdTime = millis();
        }
    }


    // ── ENCODERS: <E> drive  |  <EX> extra motors ──
    else if (t0 == 'E') {
        if (t1 == 'X') {
            // Return accumulated M5 / M6 ticks, then reset
            long m5 = total_enc_m5; long m6 = total_enc_m6;
            total_enc_m5 = 0;        total_enc_m6 = 0;
            Serial.print("EX,");
            Serial.print(m5); Serial.print(",");
            Serial.println(m6);
        } else {
            // Return drive encoder ticks, then reset
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
        }
        lastCmdTime = millis();
    }

    // ── SERVO POSITION: <S,id,pos> ──
    // ── SERVO CONFIG:   <SCFG,id,speed,min,max> ──
    else if (t0 == 'S') {
        if (t1 == 'C') {
            // SCFG — servo sweep speed and position limits
            int id, spd, mn, mx;
            if (sscanf(inputBuffer + 5, "%d,%d,%d,%d", &id, &spd, &mn, &mx) == 4) {
                if (id == 1) {
                    servo1_speed = constrain(spd, 1, 180);
                    servo1_min   = constrain(mn,  0, 180);
                    servo1_max   = constrain(mx,  0, 180);
                } else if (id == 2) {
                    servo2_speed = constrain(spd, 1, 180);
                    servo2_min   = constrain(mn,  0, 180);
                    servo2_max   = constrain(mx,  0, 180);
                }
            }
        } else {
            // S — set servo target position
            int id, pos;
            if (sscanf(inputBuffer + 2, "%d,%d", &id, &pos) == 2) {
                if (id == 1) {
                    target_s1 = constrain(pos, servo1_min, servo1_max);
                } else if (id == 2) {
                    target_s2 = constrain(pos, servo2_min, servo2_max);
                }
            }
        }
    }
}


// ══════════════════════════════════════════════════
// EXTRA MOTOR SYNC — runs every PID_INTERVAL_MS
// Position-Sync (Electronic Shaft) matches RPM without knowing ticks/rev
// ══════════════════════════════════════════════════
void pidStep() {
    unsigned long now = millis();
    if (now - last_pid_time < PID_INTERVAL_MS) return;
    last_pid_time = now;

    // Read and clear encoder ticks for THIS interval
    noInterrupts();
    long d5 = encM5; encM5 = 0;
    long d6 = encM6; encM6 = 0;
    interrupts();

    // Accumulate total for the 'EX' command so the RPi can see running totals
    total_enc_m5 += d5;
    total_enc_m6 += d6;

    if (base_pwm_m5 == 0 && base_pwm_m6 == 0) {
        setMotor(M5_DIR, M5_PWM, 0);
        setMotor(M6_DIR, M6_PWM, 0);
        return;
    }

    // Accumulate ticks ONLY in the direction of intended travel for sync purposes
    // To make them directly comparable, we align their signs.
    int sign5 = (base_pwm_m5 > 0) ? 1 : -1;
    int sign6 = (base_pwm_m6 > 0) ? 1 : -1;

    sync_ticks_m5 += (d5 * sign5);
    sync_ticks_m6 += (d6 * sign6);

    // Difference in distance traveled
    long diff = sync_ticks_m5 - sync_ticks_m6;
    
    // Correction factor
    int correction = (int)(diff * sync_kp);

    // Apply correction: slow down the one that's ahead, speed up the one that is behind
    // M5 adjustment
    int pwm5 = abs(base_pwm_m5) - correction;
    int pwm6 = abs(base_pwm_m6) + correction;

    // Prevent going backwards or exceeding 255
    pwm5 = constrain(pwm5, 0, 255);
    pwm6 = constrain(pwm6, 0, 255);

    setMotor(M5_DIR, M5_PWM, pwm5 * sign5);
    setMotor(M6_DIR, M6_PWM, pwm6 * sign6);
}


// ══════════════════════════════════════════════════
// SERVO SLEW — smooth sweep to target, runs every SERVO_STEP_MS
// ══════════════════════════════════════════════════
void updateServos() {
    if (millis() - last_servo_time < SERVO_STEP_MS) return;
    last_servo_time = millis();

    if (current_s1 < target_s1)
        current_s1 = min(current_s1 + servo1_speed, target_s1);
    else if (current_s1 > target_s1)
        current_s1 = max(current_s1 - servo1_speed, target_s1);
    servo1.write(current_s1);

    if (current_s2 < target_s2)
        current_s2 = min(current_s2 + servo2_speed, target_s2);
    else if (current_s2 > target_s2)
        current_s2 = max(current_s2 - servo2_speed, target_s2);
    servo2.write(current_s2);
}


// ══════════════════════════════════════════════════
// MOTOR CONTROL
// ══════════════════════════════════════════════════
void setMotor(int dirPin, int pwmPin, int speed) {
    if (speed > 0) {
        digitalWrite(dirPin, LOW);
        analogWrite(pwmPin, speed);
    } else if (speed < 0) {
        digitalWrite(dirPin, HIGH);
        analogWrite(pwmPin, -speed);
    } else {
        digitalWrite(dirPin, LOW);
        analogWrite(pwmPin, 0);
    }
}

void stopAllMotors() {
    analogWrite(LF_PWM, 0); analogWrite(RF_PWM, 0);
    analogWrite(LB_PWM, 0); analogWrite(RB_PWM, 0);
    analogWrite(M5_PWM, 0); analogWrite(M6_PWM, 0);
}
