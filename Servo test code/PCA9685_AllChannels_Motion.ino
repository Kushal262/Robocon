#include <Servo.h>

// ── 6 Servo Setup ─────────────────────────────────────────────
#define NUM_SERVOS 6

// RDS5160 PWM range: 500µs (0°) to 2500µs (max°)
#define MIN_PULSE  500
#define MAX_PULSE  2500

// Assign each servo to a digital pin on the Arduino Mega
// Change these pins to match YOUR wiring
//const int SERVO_PINS[NUM_SERVOS] = {2, 3, 4, 5, 6, 7};
const int SERVO_PINS[NUM_SERVOS] = {24,27,26,25,43,45};

Servo servos[NUM_SERVOS];

void setup() {
  Serial.begin(9600);

  for (int i = 0; i < NUM_SERVOS; i++) {
    // Start each servo at 0 degrees
    servos[i].writeMicroseconds(MIN_PULSE);
    servos[i].attach(SERVO_PINS[i], MIN_PULSE, MAX_PULSE);
  }

  Serial.println("READY");
}

void loop() {
  // Protocol from Python:  <servo_id>,<angle>,<max_angle>\n
  // Example:  2,135,270\n  → move servo #2 to 135° (out of 270°)

  if (Serial.available() > 0) {
    int id       = Serial.parseInt();   // servo index 0-5
    int angle    = Serial.parseInt();   // target angle
    int maxAngle = Serial.parseInt();   // max range (180 or 270)

    // Consume any trailing whitespace / newline
    while (Serial.available() > 0 && Serial.peek() <= 32) {
      Serial.read();
    }

    // ── Validate servo ID ───────────────────────────────────
    if (id < 0 || id >= NUM_SERVOS) {
      Serial.print("ERROR:Invalid servo ID ");
      Serial.println(id);
      return;
    }

    // ── Validate max angle ──────────────────────────────────
    if (maxAngle != 180 && maxAngle != 270) {
      Serial.print("ERROR:Invalid max angle ");
      Serial.println(maxAngle);
      return;
    }

    // ── Validate target angle ───────────────────────────────
    if (angle < 0 || angle > maxAngle) {
      Serial.print("ERROR:Angle must be 0-");
      Serial.println(maxAngle);
      return;
    }

    // ── Move the servo ──────────────────────────────────────
    int pulse = map(angle, 0, maxAngle, MIN_PULSE, MAX_PULSE);
    servos[id].writeMicroseconds(pulse);

    // Acknowledge
    Serial.print("OK:");
    Serial.print(id);
    Serial.print(":");
    Serial.println(angle);
  }
}
