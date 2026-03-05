/*
 * ESP32 + BluePad32 + Rhino MDD20 Motor Driver
 * -----------------------------------------------
 * Controls a single DC motor via PS4 controller.
 *
 * PS4 Controls:
 *   L1 → Motor backward
 *   R1 → Motor forward
 *   Neither / Both → Motor stop
 *
 * Motor Driver: Rhino MDD20 (Channel A)
 *   - PWM_A pin → speed (PWM)
 *   - DIR_A pin → direction (HIGH/LOW)
 *
 * Connection Note:
 *   Press the EN (reset) button on the ESP32 to start
 *   BluePad32 pairing mode. Put your PS4 controller in
 *   pairing mode (hold SHARE + PS button until light bar
 *   flashes rapidly), and it will auto-connect.
 *
 * Wiring:
 *   ESP32 GPIO 25 → MDD20 PWM A
 *   ESP32 GPIO 26 → MDD20 DIR A
 *   ESP32 GND      → MDD20 GND
 *   Motor supply    → MDD20 VIN / GND
 *   Motor terminals → MDD20 Motor A+ / A-
 */

#include <Bluepad32.h>

// ─── Motor Driver Pins (MDD20 Channel A) ────────────────────
#define MOTOR_PWM_PIN  25   // PWM speed control
#define MOTOR_DIR_PIN  26   // Direction control

// ─── Motor Speed (low for testing) ──────────────────────────
// PWM range is 0-255; keep it low so the motor barely spins.
#define TEST_SPEED     80   // ~31 % duty cycle

// ─── BluePad32 ──────────────────────────────────────────────
ControllerPtr myControllers[BP32_MAX_GAMEPADS];

// ─── Callbacks ──────────────────────────────────────────────
void onConnectedController(ControllerPtr ctl) {
    bool foundEmptySlot = false;
    for (int i = 0; i < BP32_MAX_GAMEPADS; i++) {
        if (myControllers[i] == nullptr) {
            Serial.printf("CONNECTED: controller index=%d\n", i);
            myControllers[i] = ctl;
            foundEmptySlot = true;
            break;
        }
    }
    if (!foundEmptySlot) {
        Serial.println("CONNECTED: but no empty slot available!");
    }
}

void onDisconnectedController(ControllerPtr ctl) {
    for (int i = 0; i < BP32_MAX_GAMEPADS; i++) {
        if (myControllers[i] == ctl) {
            Serial.printf("DISCONNECTED: controller index=%d\n", i);
            myControllers[i] = nullptr;
            break;
        }
    }
    // Safety: stop the motor when the controller disconnects
    stopMotor();
}

// ─── Motor helpers ──────────────────────────────────────────
void motorForward(uint8_t speed) {
    digitalWrite(MOTOR_DIR_PIN, HIGH);
    analogWrite(MOTOR_PWM_PIN, speed);
}

void motorBackward(uint8_t speed) {
    digitalWrite(MOTOR_DIR_PIN, LOW);
    analogWrite(MOTOR_PWM_PIN, speed);
}

void stopMotor() {
    analogWrite(MOTOR_PWM_PIN, 0);
}

// ─── Process Gamepad ────────────────────────────────────────
void processGamepad(ControllerPtr ctl) {
    // Read shoulder buttons
    bool l1 = ctl->l1();   // L1 pressed?
    bool r1 = ctl->r1();   // R1 pressed?

    if (r1 && !l1) {
        // R1 only → forward
        motorForward(TEST_SPEED);
        Serial.println(">> FORWARD");
    } else if (l1 && !r1) {
        // L1 only → backward
        motorBackward(TEST_SPEED);
        Serial.println("<< BACKWARD");
    } else {
        // Neither or both → stop
        stopMotor();
    }
}

// ─── Setup ──────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("ESP32 + BluePad32 + MDD20 Motor Control");
    Serial.println("Press EN button to reset & start pairing...");

    // Motor pins
    pinMode(MOTOR_PWM_PIN, OUTPUT);
    pinMode(MOTOR_DIR_PIN, OUTPUT);
    stopMotor();

    // BluePad32 setup
    BP32.setup(&onConnectedController, &onDisconnectedController);

    // "forgetBluetoothKeys()" removes all saved paired devices.
    // Uncomment if you want to force re-pairing every boot:
    // BP32.forgetBluetoothKeys();

    Serial.println("Waiting for PS4 controller...");
    Serial.println("Put controller in pairing mode: hold SHARE + PS button");
}

// ─── Loop ───────────────────────────────────────────────────
void loop() {
    // Must call this to update controller data
    bool dataUpdated = BP32.update();

    if (dataUpdated) {
        for (int i = 0; i < BP32_MAX_GAMEPADS; i++) {
            ControllerPtr ctl = myControllers[i];
            if (ctl && ctl->isConnected() && ctl->hasData()) {
                if (ctl->isGamepad()) {
                    processGamepad(ctl);
                }
            }
        }
    }

    // Small delay to avoid flooding the serial monitor
    delay(50);
}
