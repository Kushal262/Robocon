#include <AccelStepper.h>

#define STEP_PIN 2
#define DIR_PIN 3
#define EN_PIN 4

AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);

String inputString = "";
int speedValue = 0;

void setup() {
  Serial.begin(115200);

  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW);  // enable DM542

  stepper.setMaxSpeed(1000);
}

void loop() {

  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n') {
      speedValue = inputString.toInt();
      inputString = "";
    } else {
      inputString += c;
    }
  }

  stepper.setSpeed(speedValue);
  stepper.runSpeed();
}