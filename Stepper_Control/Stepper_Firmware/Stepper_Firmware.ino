/*
 ╔══════════════════════════════════════════════════════════════╗
 ║  STEPPER MOTOR FIRMWARE — Arduino Mega                      ║
 ║  Receives commands from Jetson Nano via USB Serial          ║
 ║  Drives T60S stepper driver (PUL/DIR interface)             ║
 ╚══════════════════════════════════════════════════════════════╝

 WIRING (Common-Cathode to T60S):
   Arduino Pin 9  → T60S PUL+   (Step/Pulse signal)
   Arduino Pin 8  → T60S DIR+   (Direction signal)
   Arduino Pin 7  → T60S ENA+   (Enable, optional)
   Arduino GND    → T60S PUL-, DIR-, ENA-  (all tied to GND)

 PROTOCOL FROM JETSON NANO:
   <ST,speed,dir>   → Set stepper speed (PPS) and direction (1=CW, 0=CCW)
   <STOP>           → Emergency stop
   <HOME>           → Return to home position (step count = 0)

 PROTOCOL TO JETSON NANO:
   POS,step_count   → Current position (sent periodically)
   [MSG]            → Status/debug messages
*/

// ═══════════════════════════════════════════════════
// PIN DEFINITIONS
// ═══════════════════════════════════════════════════

#define PUL_PIN   9     // Pulse/Step pin → T60S PUL+
#define DIR_PIN   8     // Direction pin  → T60S DIR+
#define ENA_PIN   7     // Enable pin     → T60S ENA+

// ═══════════════════════════════════════════════════
// STEPPER PARAMETERS
// ═══════════════════════════════════════════════════

#define PULSE_WIDTH_US    5       // Minimum pulse HIGH width (T60S needs ≥2.5μs)
#define MAX_SPEED_PPS     10000   // Absolute max pulses per second (safety limit)
#define POS_REPORT_MS     200     // Position report interval (ms)
#define SAFETY_TIMEOUT_MS 500     // Stop motor if no command received for this long

// ═══════════════════════════════════════════════════
// SERIAL PARSING
// ═══════════════════════════════════════════════════

#define SERIAL_BUF_SIZE   64
char serialBuf[SERIAL_BUF_SIZE];
int  serialIdx = 0;
bool receiving = false;

// ═══════════════════════════════════════════════════
// STEPPER STATE
// ═══════════════════════════════════════════════════

volatile long    stepPosition     = 0;       // Current position in steps
volatile int     targetSpeed      = 0;       // Target speed in PPS
volatile int     currentDirection  = 1;      // 1 = CW, 0 = CCW
volatile bool    motorRunning     = false;
volatile bool    emergencyStop    = false;

// Homing state
volatile bool    homing           = false;
volatile long    homeTarget       = 0;

// Timing for pulse generation (non-blocking)
unsigned long    lastPulseTime    = 0;
unsigned long    pulseInterval    = 0;       // Microseconds between pulses
bool             pulseState       = false;   // Track HIGH/LOW state of pulse pin

// Position reporting
unsigned long    lastPosReport    = 0;

// Safety timeout
unsigned long    lastCommandTime  = 0;


// ═══════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════

void setup() {
    // Pin modes
    pinMode(PUL_PIN, OUTPUT);
    pinMode(DIR_PIN, OUTPUT);
    pinMode(ENA_PIN, OUTPUT);

    // Initial state
    digitalWrite(PUL_PIN, LOW);
    digitalWrite(DIR_PIN, HIGH);   // Default direction CW
    digitalWrite(ENA_PIN, LOW);    // Enable motor (LOW = no current through opto = enabled)

    // Serial communication
    Serial.begin(115200);
    while (!Serial) { ; }

    lastCommandTime = millis();

    Serial.println("[OK] Stepper Firmware Ready");
    Serial.println("[INFO] Pins: PUL=9 DIR=8 ENA=7");
}


// ═══════════════════════════════════════════════════
// SERIAL COMMAND PARSER
// ═══════════════════════════════════════════════════

void parseCommand(char* cmd) {

    // Reset safety timeout on any valid command
    lastCommandTime = millis();

    // ── Emergency Stop: <STOP> ──
    if (strcmp(cmd, "STOP") == 0) {
        emergencyStop = true;
        targetSpeed = 0;
        motorRunning = false;
        homing = false;
        pulseState = false;
        digitalWrite(PUL_PIN, LOW);
        Serial.println("[STOP] Emergency stop activated");
        return;
    }

    // ── Home: <HOME> ──
    if (strcmp(cmd, "HOME") == 0) {
        emergencyStop = false;
        homing = true;
        homeTarget = 0;

        // Determine direction to home
        if (stepPosition > 0) {
            currentDirection = 0;   // Go CCW to reach 0
        } else if (stepPosition < 0) {
            currentDirection = 1;   // Go CW to reach 0
        } else {
            homing = false;         // Already at home
            Serial.println("[HOME] Already at home position");
            return;
        }

        digitalWrite(DIR_PIN, currentDirection ? HIGH : LOW);
        targetSpeed = 2000;  // Moderate homing speed
        motorRunning = true;
        updatePulseInterval();
        Serial.println("[HOME] Returning to home position...");
        return;
    }

    // ── Stepper Command: <ST,speed,dir> ──
    if (strncmp(cmd, "ST,", 3) == 0) {
        emergencyStop = false;
        homing = false;

        // Parse speed and direction
        char* token = strtok(cmd + 3, ",");
        if (token == NULL) return;
        int speed = atoi(token);

        token = strtok(NULL, ",");
        if (token == NULL) return;
        int dir = atoi(token);

        // Validate
        speed = constrain(speed, 0, MAX_SPEED_PPS);
        dir = (dir != 0) ? 1 : 0;

        // Apply
        targetSpeed = speed;
        currentDirection = dir;
        motorRunning = (speed > 0);

        // Set direction pin
        digitalWrite(DIR_PIN, currentDirection ? HIGH : LOW);

        // Calculate pulse interval
        updatePulseInterval();

        // If stopped, ensure pulse pin is LOW
        if (!motorRunning) {
            pulseState = false;
            digitalWrite(PUL_PIN, LOW);
        }
        return;
    }
}

void updatePulseInterval() {
    if (targetSpeed > 0) {
        // Total cycle = HIGH time + LOW time
        // We need interval for the full cycle
        pulseInterval = 1000000UL / (unsigned long)targetSpeed;

        // Enforce minimum (safety)
        if (pulseInterval < (2 * PULSE_WIDTH_US)) {
            pulseInterval = 2 * PULSE_WIDTH_US;
        }
    } else {
        pulseInterval = 0;
        motorRunning = false;
    }
}


// ═══════════════════════════════════════════════════
// SERIAL READ (non-blocking, bracket-delimited)
// ═══════════════════════════════════════════════════

void readSerial() {
    while (Serial.available() > 0) {
        char c = Serial.read();

        if (c == '<') {
            // Start of command
            receiving = true;
            serialIdx = 0;
        }
        else if (c == '>') {
            // End of command
            if (receiving) {
                serialBuf[serialIdx] = '\0';
                parseCommand(serialBuf);
                receiving = false;
                serialIdx = 0;
            }
        }
        else if (receiving) {
            if (serialIdx < SERIAL_BUF_SIZE - 1) {
                serialBuf[serialIdx++] = c;
            } else {
                // Buffer overflow — discard
                receiving = false;
                serialIdx = 0;
            }
        }
    }
}


// ═══════════════════════════════════════════════════
// GENERATE STEP PULSES (non-blocking)
// ═══════════════════════════════════════════════════

void generatePulse() {
    if (!motorRunning || emergencyStop || pulseInterval == 0) {
        return;
    }

    unsigned long now = micros();
    unsigned long elapsed = now - lastPulseTime;

    // Handle micros() overflow (every ~70 minutes)
    if (elapsed > 10000000UL) {
        lastPulseTime = now;
        return;
    }

    if (!pulseState) {
        // Waiting for next pulse — check if it's time
        if (elapsed >= pulseInterval) {
            // Start pulse (HIGH)
            digitalWrite(PUL_PIN, HIGH);
            pulseState = true;
            lastPulseTime = now;

            // Track position
            if (currentDirection == 1) {
                stepPosition++;
            } else {
                stepPosition--;
            }

            // ── Homing check ──
            if (homing) {
                if (stepPosition == homeTarget) {
                    motorRunning = false;
                    homing = false;
                    targetSpeed = 0;
                    pulseState = false;
                    digitalWrite(PUL_PIN, LOW);
                    Serial.println("[HOME] Home position reached!");
                }
            }
        }
    } else {
        // Pulse is HIGH — wait for pulse width then go LOW
        if (elapsed >= PULSE_WIDTH_US) {
            digitalWrite(PUL_PIN, LOW);
            pulseState = false;
        }
    }
}


// ═══════════════════════════════════════════════════
// SAFETY TIMEOUT — Stop motor if Pi disconnects
// ═══════════════════════════════════════════════════

void checkSafetyTimeout() {
    if (motorRunning && !homing) {
        unsigned long elapsed = millis() - lastCommandTime;
        if (elapsed > SAFETY_TIMEOUT_MS) {
            targetSpeed = 0;
            motorRunning = false;
            pulseState = false;
            digitalWrite(PUL_PIN, LOW);
            Serial.println("[SAFETY] No command received — motor stopped");
        }
    }
}


// ═══════════════════════════════════════════════════
// POSITION REPORTING
// ═══════════════════════════════════════════════════

void reportPosition() {
    unsigned long now = millis();
    if (now - lastPosReport >= POS_REPORT_MS) {
        lastPosReport = now;
        Serial.print("POS,");
        Serial.println(stepPosition);
    }
}


// ═══════════════════════════════════════════════════
// MAIN LOOP
// ═══════════════════════════════════════════════════

void loop() {
    readSerial();
    generatePulse();
    reportPosition();
    checkSafetyTimeout();
}
