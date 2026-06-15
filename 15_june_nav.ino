// ============================================================
//  R2 - Encoder Navigation (added to Full Manual v2 base)
//  Date: June 2026
//
//  ADDS to existing Full Manual v2:
//    - Encoder ISRs for X (strafe) and Y (forward) dead wheels
//    - Encoder counts broadcast every 100ms in feedback
//    - NAV mode: Python sends target pulse counts, Arduino drives
//      closed-loop toward them using P controller
//    - Manual mode: same 10-field CSV packet as before
//
//  PACKET FORMAT:
//    Manual mode:  "M,LF,RF,LB,RB,LIFT,S1,S2,ARM,DCV_KFS,DCV_SH\n"
//    Nav mode:     "N,TARGET_X,TARGET_Y,SPEED\n"
//    Reset encoders: "R\n"
//    Abort nav:    "A\n"
//
//  FEEDBACK (every 100ms):
//    "EX:<pulses> EY:<pulses> MODE:<M/N> NV:<0/1>\n"
//    NV:1 = nav active, NV:0 = nav done/idle
// ============================================================

#include <Servo.h>

// Forward declarations (Arduino IDE auto-generates function prototypes
// before struct definitions — these prevent 'not declared' errors)
struct Stepper;
struct DriveMotor;

// ============================================================
//  CONFIG BLOCK
// ============================================================

// --- DRIVE ---
#define LF_PWM_PIN    8
#define LF_DIR_PIN    39
#define RF_PWM_PIN    9
#define RF_DIR_PIN    38
#define LB_PWM_PIN    4
#define LB_DIR_PIN    41
#define RB_PWM_PIN    5
#define RB_DIR_PIN    40
#define DRIVE_FWD     HIGH
#define DRIVE_REV     LOW
#define DRIVE_RAMP    4

// --- LIFT STEPPERS ---
#define LIFT1_PUL     11
#define LIFT1_DIR_PIN 10
#define LIFT2_PUL     37
#define LIFT2_DIR_PIN 36
#define DIR_UP        HIGH
#define DIR_DOWN      LOW
#define LIFT_START_US 800UL
#define LIFT_MIN_US   150UL
#define LIFT_ACCEL_US 4UL

// --- ARM STEPPER ---
#define ARM_PUL_PIN   7
#define ARM_DIR_PIN   53
#define ARM_EXTEND    true
#define ARM_RETRACT   false
#define ARM_START_US  1000UL
#define ARM_MIN_US    500UL
#define ARM_ACCEL_US  6UL
#define ARM_DECEL_US  8UL

// --- SERVO1 ---
#define SERVO1_PIN      6
#define SERVO1_MIN_US   500
#define SERVO1_MAX_US   2500
#define SERVO1_DEG_MIN  0
#define SERVO1_DEG_MAX  180

// --- SERVO2 ---
#define SERVO2_PIN      12
#define SERVO2_MIN_US   500
#define SERVO2_MAX_US   2500
#define SERVO2_DEG_MIN  0
#define SERVO2_DEG_MAX  270
#define SERVO2_HOME     180
#define SERVO2_FWD      90
#define SERVO2_BACK     260

#define SERVO_RAMP_INTERVAL_MS  20UL

// --- DCV ---
#define DCV_KFS_PIN   46
#define DCV_SH_PIN    44

// --- ENCODERS ---
#define ENC_Y_A   18    // Y axis (forward/back) -- interrupt
#define ENC_Y_B   17
#define ENC_X_A   19    // X axis (strafe) -- interrupt
#define ENC_X_B   16

// --- NAV P CONTROLLER ---
#define PULSES_PER_METER   2050L   // calibrated
#define NAV_BASE_SPEED     60      // cruise speed (0-255) -- reduced for testing
#define NAV_SLOW_SPEED     30      // slow zone speed
#define NAV_SLOW_PULSES    300L    // start slowing within this many pulses
#define NAV_STOP_TOLERANCE 30L     // stop when within this many pulses
// (NAV_KP_CROSS removed — cross-axis is handled inherently by mecanum mix)

// --- SERIAL ---
#define SERIAL_BAUD         115200
#define SERIAL_TIMEOUT_MS   500

// ============================================================
//  ENCODER STATE (volatile)
// ============================================================
volatile long encX = 0;   // strafe axis
volatile long encY = 0;   // forward axis

void ISR_Y() { encY += (digitalRead(ENC_Y_B) == LOW) ? 1 : -1; }
void ISR_X() { encX += (digitalRead(ENC_X_B) == LOW) ? -1 : 1; }

// ============================================================
//  NAV STATE
// ============================================================
bool  navActive   = false;
long  navTargetX  = 0;
long  navTargetY  = 0;
int   navSpeed    = NAV_BASE_SPEED;

// ============================================================
//  STEPPER STRUCT
// ============================================================
struct Stepper {
  uint8_t  pulPin, dirPin;
  bool     running, direction, pulseHigh, decelerating;
  uint32_t currentIntervalUs, lastPulseUs;
  long     pulseCount;
};
Stepper lift1, lift2, armStep;

// ============================================================
//  DRIVE STRUCT
// ============================================================
struct DriveMotor {
  uint8_t pwmPin, dirPin;
  int targetSpeed, currentSpeed;
};
DriveMotor mLF, mRF, mLB, mRB;

// ============================================================
//  SERVO
// ============================================================
Servo servo1, servo2;
float s1Current = 180.0f, s2Current = (float)SERVO2_HOME;
int   s1Target  = 180,    s2Target  = SERVO2_HOME;
uint32_t lastServoRampMs = 0;

// ============================================================
//  PACKET
// ============================================================
char    cmdBuffer[80];
uint8_t cmdIndex  = 0;
uint32_t lastCmdMs = 0;
char    mode = 'M';   // 'M'=manual, 'N'=nav

// ============================================================
//  STEPPER FUNCTIONS
// ============================================================
void startStepper(Stepper &s, bool dir, uint32_t startUs) {
  if (s.running && s.direction == dir && !s.decelerating) return;
  s.running=true; s.direction=dir; s.decelerating=false;
  s.currentIntervalUs=startUs; s.pulseHigh=false;
  s.lastPulseUs=micros();
  digitalWrite(s.dirPin, dir?HIGH:LOW);
}
void stopStepper(Stepper &s) {
  s.running=false; s.decelerating=false;
  digitalWrite(s.pulPin,LOW);
}
void decelerateStepper(Stepper &s) {
  if(s.running && !s.decelerating) s.decelerating=true;
}
void updateStepper(Stepper &s, uint32_t minUs, uint32_t accelUs, uint32_t decelUs, uint32_t stopUs) {
  if(!s.running) return;
  uint32_t now=micros();
  if((now-s.lastPulseUs)>=(s.currentIntervalUs/2)) {
    s.pulseHigh=!s.pulseHigh;
    digitalWrite(s.pulPin, s.pulseHigh?HIGH:LOW);
    s.lastPulseUs=now;
    if(!s.pulseHigh) {
      s.pulseCount += s.direction?1L:-1L;
      if(s.decelerating) {
        s.currentIntervalUs+=decelUs;
        if(s.currentIntervalUs>=stopUs) { stopStepper(s); return; }
      } else {
        if(s.currentIntervalUs>minUs)
          s.currentIntervalUs=(s.currentIntervalUs-accelUs>minUs)?s.currentIntervalUs-accelUs:minUs;
      }
    }
  }
}
void setLiftState(Stepper &s, bool run, bool dir) {
  if(run) { if(!s.running||s.direction!=dir) startStepper(s,dir,LIFT_START_US); else s.decelerating=false; }
  else    { if(s.running) decelerateStepper(s); }
}

// ============================================================
//  DRIVE FUNCTIONS
// ============================================================
void setMotorDirect(uint8_t pwm, uint8_t dir, int spd) {
  if(spd>=0){digitalWrite(dir,DRIVE_FWD);analogWrite(pwm,spd);}
  else      {digitalWrite(dir,DRIVE_REV);analogWrite(pwm,-spd);}
}
void updateDriveMotor(DriveMotor &m) {
  if(m.currentSpeed<m.targetSpeed){m.currentSpeed+=DRIVE_RAMP;if(m.currentSpeed>m.targetSpeed)m.currentSpeed=m.targetSpeed;}
  else if(m.currentSpeed>m.targetSpeed){m.currentSpeed-=DRIVE_RAMP;if(m.currentSpeed<m.targetSpeed)m.currentSpeed=m.targetSpeed;}
  if(m.currentSpeed>=0){digitalWrite(m.dirPin,DRIVE_FWD);analogWrite(m.pwmPin,m.currentSpeed);}
  else{digitalWrite(m.dirPin,DRIVE_REV);analogWrite(m.pwmPin,-m.currentSpeed);}
}
void stopAllDriveImmediate() {
  mLF.targetSpeed=mLF.currentSpeed=0; mRF.targetSpeed=mRF.currentSpeed=0;
  mLB.targetSpeed=mLB.currentSpeed=0; mRB.targetSpeed=mRB.currentSpeed=0;
  analogWrite(mLF.pwmPin,0);analogWrite(mRF.pwmPin,0);
  analogWrite(mLB.pwmPin,0);analogWrite(mRB.pwmPin,0);
}

// ============================================================
//  SERVO RAMP
// ============================================================
void updateServoRamp() {
  uint32_t now=millis();
  if(now-lastServoRampMs<SERVO_RAMP_INTERVAL_MS) return;
  lastServoRampMs=now;
  if((int)s1Current!=s1Target){
    s1Current+=(s1Current<s1Target)?1.0f:-1.0f;
    s1Current=constrain(s1Current,SERVO1_DEG_MIN,SERVO1_DEG_MAX);
    servo1.writeMicroseconds(map((int)s1Current,SERVO1_DEG_MIN,SERVO1_DEG_MAX,SERVO1_MIN_US,SERVO1_MAX_US));
  }
  if((int)s2Current!=s2Target){
    s2Current+=(s2Current<s2Target)?1.0f:-1.0f;
    s2Current=constrain(s2Current,SERVO2_DEG_MIN,SERVO2_DEG_MAX);
    servo2.writeMicroseconds(map((int)s2Current,SERVO2_DEG_MIN,SERVO2_DEG_MAX,SERVO2_MIN_US,SERVO2_MAX_US));
  }
}

// ============================================================
//  NAV CONTROLLER (closed loop P)
//
//  Mecanum mixing for simultaneous X+Y movement:
//    Forward(Y): all 4 wheels same direction
//    Strafe(X):  LF+RB forward, RF+LB reverse
//  Cross-axis correction added proportionally to kill drift.
// ============================================================
void updateNav() {
  if(!navActive) return;

  noInterrupts();
  long cx=encX, cy=encY;
  interrupts();

  long errX = navTargetX - cx;
  long errY = navTargetY - cy;
  long absX = abs(errX);
  long absY = abs(errY);

  // Check arrival
  if(absX<=NAV_STOP_TOLERANCE && absY<=NAV_STOP_TOLERANCE) {
    stopAllDriveImmediate();
    navActive=false;
    Serial.println("NAV_DONE");
    return;
  }

  // Speed scaling: slow down near target
  long maxErr = max(absX, absY);
  int spd = navSpeed;
  if(maxErr < NAV_SLOW_PULSES) {
    spd = (int)(NAV_SLOW_SPEED + (navSpeed-NAV_SLOW_SPEED) * ((float)maxErr/NAV_SLOW_PULSES));
    if(spd < NAV_SLOW_SPEED) spd = NAV_SLOW_SPEED;
  }

  // Normalise error to -1..+1
  float ny = (absY>0) ? (float)errY/max(absX,absY) : 0.0f;
  float nx = (absX>0) ? (float)errX/max(absX,absY) : 0.0f;

  // Mecanum mix
  float lf = ny + nx;
  float rf = ny - nx;
  float lb = ny - nx;
  float rb = ny + nx;

  // Scale to speed (Arduino max() only takes 2 args, chain them)
  float mx = max(max(max(max(abs(lf), abs(rf)), abs(lb)), abs(rb)), 1.0f);
  int LF = (int)(lf/mx*spd);
  int RF = (int)(rf/mx*spd);
  int LB = (int)(lb/mx*spd);
  int RB = (int)(rb/mx*spd);

  // Apply directly (bypass ramp for nav responsiveness)
  setMotorDirect(LF_PWM_PIN,LF_DIR_PIN,LF);
  setMotorDirect(RF_PWM_PIN,RF_DIR_PIN,RF);
  setMotorDirect(LB_PWM_PIN,LB_DIR_PIN,LB);
  setMotorDirect(RB_PWM_PIN,RB_DIR_PIN,RB);

  mLF.currentSpeed=LF; mRF.currentSpeed=RF;
  mLB.currentSpeed=LB; mRB.currentSpeed=RB;
}

// ============================================================
//  LIFT PARSER
// ============================================================
void parseLiftCmd(char cmd) {
  switch(cmd){
    case 'N': setLiftState(lift1,true,true); setLiftState(lift2,true,true); break;
    case 'M': setLiftState(lift1,true,false);setLiftState(lift2,true,false);break;
    case 'H': setLiftState(lift1,true,true); setLiftState(lift2,false,false);break;
    case 'J': setLiftState(lift1,true,false);setLiftState(lift2,false,false);break;
    case 'K': setLiftState(lift2,true,true); setLiftState(lift1,false,false);break;
    case 'L': setLiftState(lift2,true,false);setLiftState(lift1,false,false);break;
    default:  setLiftState(lift1,false,false);setLiftState(lift2,false,false);break;
  }
}

// ============================================================
//  PACKET PARSER
// ============================================================
void parsePacket(char *pkt) {
  if(pkt[0]=='R'){
    noInterrupts(); encX=0; encY=0; interrupts();
    Serial.println("ENC_RESET");
    return;
  }
  if(pkt[0]=='A'){
    navActive=false; stopAllDriveImmediate(); mode='M';
    Serial.println("NAV_ABORT");
    return;
  }

  char *tok[12]; uint8_t n=0;
  char *p=pkt; tok[n++]=p;
  while(*p && n<12){ if(*p==','){ *p='\0'; tok[n++]=p+1; } p++; }

  if(tok[0][0]=='N' && n>=3) {
    // Nav packet: N,TARGET_X_PULSES,TARGET_Y_PULSES,SPEED
    navTargetX = atol(tok[1]);
    navTargetY = atol(tok[2]);
    navSpeed   = (n>=4) ? constrain(atoi(tok[3]),20,255) : NAV_BASE_SPEED;
    navActive  = true;
    mode       = 'N';
    Serial.print("NAV_START TX:"); Serial.print(navTargetX);
    Serial.print(" TY:"); Serial.println(navTargetY);
    return;
  }

  if(tok[0][0]=='M' && n>=11) {
    // Manual packet: M,LF,RF,LB,RB,LIFT,S1,S2,ARM,DCV_KFS,DCV_SH
    navActive=false; mode='M';
    auto clamp=[](long v)->int{return(int)(v>255?255:(v<-255?-255:v));};
    mLF.targetSpeed=clamp(atol(tok[1]));
    mRF.targetSpeed=clamp(atol(tok[2]));
    mLB.targetSpeed=clamp(atol(tok[3]));
    mRB.targetSpeed=clamp(atol(tok[4]));
    parseLiftCmd(tok[5][0]);
    s1Target=constrain(atoi(tok[6]),SERVO1_DEG_MIN,SERVO1_DEG_MAX);
    s2Target=constrain(atoi(tok[7]),SERVO2_DEG_MIN,SERVO2_DEG_MAX);
    int arm=atoi(tok[8]);
    if(arm==1)      startStepper(armStep,ARM_EXTEND,ARM_START_US);
    else if(arm==2) startStepper(armStep,ARM_RETRACT,ARM_START_US);
    else if(armStep.running) decelerateStepper(armStep);
    digitalWrite(DCV_KFS_PIN,atoi(tok[9])==1?LOW:HIGH);
    digitalWrite(DCV_SH_PIN, atoi(tok[10])==1?LOW:HIGH);
  }
}

// ============================================================
//  FAILSAFE
// ============================================================
void checkFailsafe() {
  if((millis()-lastCmdMs)>SERIAL_TIMEOUT_MS) {
    if(navActive) { navActive=false; stopAllDriveImmediate(); }
    decelerateStepper(lift1); decelerateStepper(lift2); decelerateStepper(armStep);
    mLF.targetSpeed=mRF.targetSpeed=mLB.targetSpeed=mRB.targetSpeed=0;
  }
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
  // Encoders
  pinMode(ENC_Y_A,INPUT_PULLUP); pinMode(ENC_Y_B,INPUT_PULLUP);
  pinMode(ENC_X_A,INPUT_PULLUP); pinMode(ENC_X_B,INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(ENC_Y_A),ISR_Y,RISING);
  attachInterrupt(digitalPinToInterrupt(ENC_X_A),ISR_X,RISING);

  // Drive
  mLF={LF_PWM_PIN,LF_DIR_PIN,0,0}; mRF={RF_PWM_PIN,RF_DIR_PIN,0,0};
  mLB={LB_PWM_PIN,LB_DIR_PIN,0,0}; mRB={RB_PWM_PIN,RB_DIR_PIN,0,0};
  pinMode(LF_PWM_PIN,OUTPUT);pinMode(LF_DIR_PIN,OUTPUT);
  pinMode(RF_PWM_PIN,OUTPUT);pinMode(RF_DIR_PIN,OUTPUT);
  pinMode(LB_PWM_PIN,OUTPUT);pinMode(LB_DIR_PIN,OUTPUT);
  pinMode(RB_PWM_PIN,OUTPUT);pinMode(RB_DIR_PIN,OUTPUT);
  stopAllDriveImmediate();

  // Lifts
  lift1={LIFT1_PUL,LIFT1_DIR_PIN,false,true,false,false,LIFT_START_US,0,0L};
  stopStepper(lift1); pinMode(LIFT1_PUL,OUTPUT);pinMode(LIFT1_DIR_PIN,OUTPUT);
  lift2={LIFT2_PUL,LIFT2_DIR_PIN,false,true,false,false,LIFT_START_US,0,0L};
  stopStepper(lift2); pinMode(LIFT2_PUL,OUTPUT);pinMode(LIFT2_DIR_PIN,OUTPUT);

  // Arm
  armStep={ARM_PUL_PIN,ARM_DIR_PIN,false,true,false,false,ARM_START_US,0,0L};
  stopStepper(armStep); pinMode(ARM_PUL_PIN,OUTPUT);pinMode(ARM_DIR_PIN,OUTPUT);

  // Servos (write microseconds BEFORE attach so servo goes to correct position on attach)
  servo1.writeMicroseconds(map((int)s1Current,SERVO1_DEG_MIN,SERVO1_DEG_MAX,SERVO1_MIN_US,SERVO1_MAX_US));
  servo1.attach(SERVO1_PIN,SERVO1_MIN_US,SERVO1_MAX_US);
  servo2.writeMicroseconds(map((int)s2Current,SERVO2_DEG_MIN,SERVO2_DEG_MAX,SERVO2_MIN_US,SERVO2_MAX_US));
  servo2.attach(SERVO2_PIN,SERVO2_MIN_US,SERVO2_MAX_US);

  // DCVs
  pinMode(DCV_KFS_PIN,OUTPUT);digitalWrite(DCV_KFS_PIN,HIGH);
  pinMode(DCV_SH_PIN,OUTPUT); digitalWrite(DCV_SH_PIN,HIGH);

  Serial.begin(SERIAL_BAUD);
  lastCmdMs=millis(); lastServoRampMs=millis();
  Serial.println("R2 READY");
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
  while(Serial.available()>0){
    char c=Serial.read();
    if(c=='\n'||c=='\r'){
      if(cmdIndex>0){
        cmdBuffer[cmdIndex]='\0';
        lastCmdMs=millis();
        parsePacket(cmdBuffer);
        cmdIndex=0;
      }
    } else { if(cmdIndex<79) cmdBuffer[cmdIndex++]=c; }
  }

  if(navActive) updateNav();

  updateStepper(lift1,LIFT_MIN_US,LIFT_ACCEL_US,LIFT_ACCEL_US,LIFT_START_US);
  updateStepper(lift2,LIFT_MIN_US,LIFT_ACCEL_US,LIFT_ACCEL_US,LIFT_START_US);
  updateStepper(armStep,ARM_MIN_US,ARM_ACCEL_US,ARM_DECEL_US,ARM_START_US);
  if(!navActive){ updateDriveMotor(mLF);updateDriveMotor(mRF);updateDriveMotor(mLB);updateDriveMotor(mRB); }
  updateServoRamp();
  checkFailsafe();

  // Feedback every 100ms
  static uint32_t lastFbMs=0;
  if(millis()-lastFbMs>=100){
    lastFbMs=millis();
    noInterrupts(); long cx=encX,cy=encY; interrupts();
    char fb[80];
    snprintf(fb,sizeof(fb),"EX:%ld EY:%ld MODE:%c NV:%d",cx,cy,mode,navActive?1:0);
    Serial.println(fb);
  }
}
