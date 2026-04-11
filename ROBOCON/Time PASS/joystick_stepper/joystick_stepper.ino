/*
 * Stepper Motor Control using Joystick and DM542 Microstep Driver
 * 
 * Target Board: Arduino Mega 2560
 * 
 * Hardware Connections (Common Ground Configuration suggested):
 * - DM542 PUL- -> Arduino GND
 * - DM542 DIR- -> Arduino GND
 * - DM542 ENA- -> Arduino GND
 * - DM542 PUL+ -> Arduino Pin 9 (PUL_PIN)
 * - DM542 DIR+ -> Arduino Pin 8 (DIR_PIN)
 * - DM542 ENA+ -> Arduino Pin 7 (ENA_PIN)
 * 
 * - Joystick VCC -> 5V
 * - Joystick GND -> GND
 * - Joystick VRx -> Arduino A0 (JOY_X_PIN)
 */

// --- Configuration Variables ---

// Define maximum speed (adjust for testing).
// This value is the minimum delay in microseconds between steps.
// A SMALLER value means HIGHER maximum speed.
int MAX_SPEED_DELAY = 500;  // Adjust this variable to change max speed. E.g., 200 for faster, 1000 for slower.
int MIN_SPEED_DELAY = 4000; // Delay for lowest speed (slowest motion) near the joystick center.

// --- Pin Definitions ---
const int PUL_PIN = 9;   // Pulse pin
const int DIR_PIN = 8;   // Direction pin
const int ENA_PIN = 7;   // Enable pin
const int JOY_X_PIN = A0; // Joystick X-axis analog pin

// --- Joystick Calibration ---
const int joyCenter = 512; // Middle value of analogRead (roughly 512 out of 0-1023)
const int deadZone = 50;   // Deadzone to prevent jitter when joystick is untouched

void setup() {
  Serial.begin(115200);

  // Set driver pins as outputs
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENA_PIN, OUTPUT);

  // Enable the DM542 driver
  // On most DM542 drivers, ENA+ needs to be LOW (or disconnected) to enable the motor,
  // and HIGH to disable (free-wheel). We'll keep it active (LOW) in common-ground setup.
  digitalWrite(ENA_PIN, LOW); 

  Serial.println("System Initialized. Stepper ready.");
}

void loop() {
  // Read joystick X-axis value (0 to 1023)
  int joyVal = analogRead(JOY_X_PIN);

  int stepDelay = 0;

  // Check if joystick is pushed right (above center + deadzone)
  if (joyVal > joyCenter + deadZone) {
    digitalWrite(DIR_PIN, HIGH); // Set motor direction (e.g., CW)
    
    // Map joystick value to step delay. 
    // Closer to edge (1023) -> smaller delay (highest speed limit)
    // Closer to deadzone -> larger delay (lowest speed limit)
    stepDelay = map(joyVal, joyCenter + deadZone, 1023, MIN_SPEED_DELAY, MAX_SPEED_DELAY);
    
    pulseMotor(stepDelay);
  }
  // Check if joystick is pushed left (below center - deadzone)
  else if (joyVal < joyCenter - deadZone) {
    digitalWrite(DIR_PIN, LOW); // Set opposite motor direction (e.g., CCW)
    
    // Map joystick value to step delay.
    // Closer to edge (0) -> smaller delay (highest speed limit)
    // Closer to deadzone -> larger delay (lowest speed limit)
    stepDelay = map(joyVal, joyCenter - deadZone, 0, MIN_SPEED_DELAY, MAX_SPEED_DELAY);
    
    pulseMotor(stepDelay);
  }
  else {
    // Joystick is in the deadzone (centered)
    // Motor stops receiving pulses, and intrinsically holds its position (as ENA is LOW)
    // No pulse commands sent here.
  }
}

// Function to send a single pulse to the step pin
void pulseMotor(int delayTime) {
  // Constrain to ensure delay doesn't accidentally exceed our max/min bounds due to sensor noise
  delayTime = constrain(delayTime, MAX_SPEED_DELAY, MIN_SPEED_DELAY);
  
  digitalWrite(PUL_PIN, HIGH);
  delayMicroseconds(20); // Short high pulse for DM542 driver to read (typically needs minimum 2.5us)
  digitalWrite(PUL_PIN, LOW);
  delayMicroseconds(delayTime); // The delay controls the speed between steps. Shorter delay = Faster rotation.
}
