// ================================================================
// MECANUM WHEEL CAR — v2.2 (Reference Code)
// Hardware : Arduino Mega 2560 + Rhino MDD20Amp ×2 + 4 DC Motors
// Interface : PS4 via Python (integrated_robot_control.py)
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

#define MAX_SPEED 30
#define DEADZONE 20
#define RAMP_UP_STEP 14
#define RAMP_DOWN_STEP 16
#define LOOP_MS 5
#define SERIAL_TIMEOUT 500

int targetLF = 0, targetLB = 0, targetRF = 0, targetRB = 0;
int currentLF = 0, currentLB = 0, currentRF = 0, currentRB = 0;
unsigned long lastPacketTime = 0;

void setMotor(uint8_t dirPin, uint8_t pwmPin, int speed) {
    speed = constrain(speed, -30, 30);
    if (speed > 0) {
        digitalWrite(dirPin, HIGH);
        analogWrite (pwmPin, speed);
    } else if (speed < 0) {
        digitalWrite(dirPin, LOW);
        analogWrite (pwmPin, -speed);
    } else {
        digitalWrite(dirPin, LOW);
        analogWrite (pwmPin, 0);
    }
}

void applyRamp() {
    auto step = [](int cur, int tar) {
        if (cur == tar) return cur;
        int s = (abs(tar) > abs(cur)) ? RAMP_UP_STEP : RAMP_DOWN_STEP;
        if (tar > cur) { cur += s; if (cur > tar) cur = tar; }
        else { cur -= s; if (cur < tar) cur = tar; }
        return cur;
    };
    currentLF = step(currentLF, targetLF);
    currentLB = step(currentLB, targetLB);
    currentRF = step(currentRF, targetRF);
    currentRB = step(currentRB, targetRB);
    setMotor(LF_DIR, LF_PWM, currentLF);
    setMotor(LB_DIR, LB_PWM, currentLB);
    setMotor(RF_DIR, RF_PWM, currentRF);
    setMotor(RB_DIR, RB_PWM, currentRB);
}

void processPacket(int lx, int ly, int rx) {
    if (abs(lx) < DEADZONE) lx = 0;
    if (abs(ly) < DEADZONE) ly = 0;
    if (abs(rx) < DEADZONE) rx = 0;
    targetLF = constrain(ly + lx + rx, -MAX_SPEED, MAX_SPEED);
    targetLB = constrain(ly - lx + rx, -MAX_SPEED, MAX_SPEED);
    targetRF = constrain(ly - lx - rx, -MAX_SPEED, MAX_SPEED);
    targetRB = constrain(ly + lx - rx, -MAX_SPEED, MAX_SPEED);
}

void setup() {
    Serial.begin(115200);
    pinMode(LF_DIR, OUTPUT); pinMode(LF_PWM, OUTPUT);
    pinMode(LB_DIR, OUTPUT); pinMode(LB_PWM, OUTPUT);
    pinMode(RF_DIR, OUTPUT); pinMode(RF_PWM, OUTPUT);
    pinMode(RB_DIR, OUTPUT); pinMode(RB_PWM, OUTPUT);
}

char buf[32]; int idx = 0; bool in = false;
void loop() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '<') { in = true; idx = 0; }
        else if (c == '>' && in) {
            buf[idx] = 0; in = false;
            int x, y, r; if (sscanf(buf, "%d,%d,%d", &x, &y, &r) == 3) {
                lastPacketTime = millis(); processPacket(x, y, r);
            }
        } else if (in && idx < 31) buf[idx++] = c;
    }
    if (millis() - lastPacketTime > SERIAL_TIMEOUT) targetLF = targetLB = targetRF = targetRB = 0;
    applyRamp();
    delay(LOOP_MS);
}
