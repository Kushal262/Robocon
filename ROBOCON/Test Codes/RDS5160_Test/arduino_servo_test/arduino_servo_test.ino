#include <Servo.h>

Servo myServo;

// RDS5160 PWM range: 500µs (0°) to 2500µs (270°)
#define MIN_PULSE  500
#define MAX_PULSE  2500
#define MAX_ANGLE  270

// Connect the orange/yellow SIGNAL wire of the servo to Pin 9
const int SERVO_PIN = 9;

void setup() {
  Serial.begin(9600);
  
  // Set initial position to 0 degrees before attaching
  myServo.writeMicroseconds(MIN_PULSE);
  
  // Attach the servo with specific pulse boundaries
  myServo.attach(SERVO_PIN, MIN_PULSE, MAX_PULSE);

  // Send a ready signal back to Python
  Serial.println("READY");
}

void loop() {
  // Check if Python has sent any data
  if (Serial.available() > 0) {
    // Read the integer sent by Python
    int targetAngle = Serial.parseInt();
    
    // Clear the rest of the serial buffer (like \n characters)
    while(Serial.available() > 0 && Serial.peek() <= 32) {
      Serial.read();
    }

    // Validate and move the servo
    if (targetAngle >= 0 && targetAngle <= MAX_ANGLE) {
      // Map angle to microsecond pulse
      int pulse = map(targetAngle, 0, MAX_ANGLE, MIN_PULSE, MAX_PULSE);
      
      // Move servo
      myServo.writeMicroseconds(pulse);
      
      // Acknowledge receipt to Python
      Serial.print("OK:");
      Serial.println(targetAngle);
    } else {
      Serial.println("ERROR: Angle must be 0 to 270");
    }
  }
}
