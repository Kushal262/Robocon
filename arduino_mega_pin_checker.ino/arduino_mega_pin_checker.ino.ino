// Arduino Mega PCB Pin Continuity Tester
// Press pin 12 momentarily to HIGH — all others stay LOW
// Use DMM to probe the selected pin

const int testPins[] = {
  2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
  22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
  32, 33, 34, 35, 36, 37, 38, 39, 40, 41,
  42, 43, 44, 45, 46, 47, 48, 49,
  A0, A1, A2, A3, A4, A5, A6, A7,
  A8, A9, A10, A11, A12, A13, A14, A15
};

const int totalPins = sizeof(testPins) / sizeof(testPins[0]);
int selectedPin = -1;    // currently HIGH pin (-1 = none)

void setup() {
  Serial.begin(9600);
  // Set ALL test pins LOW
  for (int i = 0; i < totalPins; i++) {
    pinMode(testPins[i], OUTPUT);
    digitalWrite(testPins[i], LOW);
  }
  Serial.println("PCB Tester Ready. Send pin number via Serial.");
  Serial.println("Example: send '12' to set pin 12 HIGH.");
}

void loop() {
  if (Serial.available() > 0) {
    int pinNum = Serial.parseInt();

    // Check if pin is in our list
    bool valid = false;
    for (int i = 0; i < totalPins; i++) {
      if (testPins[i] == pinNum) { valid = true; break; }
    }

    if (valid) {
      // Set previous pin LOW
      if (selectedPin != -1) {
        digitalWrite(selectedPin, LOW);
      }
      // Set new pin HIGH
      selectedPin = pinNum;
      digitalWrite(selectedPin, HIGH);

      Serial.print("Pin ");
      Serial.print(selectedPin);
      Serial.println(" is HIGH. All others LOW.");
      Serial.println("Probe with DMM. Send next pin when ready.");
    } else {
      Serial.print("Pin ");
      Serial.print(pinNum);
      Serial.println(" not in test list. Try again.");
    }
  }
}