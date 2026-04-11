"""
╔══════════════════════════════════════════════════════════════╗
║  R1 - Raspberry Pi MASTER CONTROLLER                         ║
║  Robocon 2026 "Kung Fu Quest"                                ║
╚══════════════════════════════════════════════════════════════╝

CONTROLS:
  Left Stick        = Drive + Strafe (mecanum)
  Right Stick X     = Rotate
  Right Stick Y     = Extra motors M5 + M6 (PID RPM-locked)
  B1 (Circle)       = EMERGENCY STOP toggle
  B4 (L1)           = Slow mode (hold)
  B3 (Square)       = Both servos → pos_a
  B0 (Cross/X)      = Both servos → pos_b
  Ctrl+C            = Exit

PROTOCOL TO ARDUINO:
  <M,LF,RF,LB,RB>               → Drive motor PWM (-255 to +255)
  <X,m5_pct,m6_pct>             → Extra motor speed % (-100 to +100)
  <XCFG,sync_strength_x100>     → Sync strength ×100
  <E>                            → Request drive encoder ticks
  <EX>                           → Request M5/M6 encoder ticks
  <S,id,pos>                     → Servo position (degrees)
  <SCFG,id,speed,min,max>        → Servo sweep config
"""

import pygame
import serial
import json
import time
import os
import threading


# ═══════════════════════════════════════════════════
# LOAD CONFIG
# ═══════════════════════════════════════════════════

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

with open(CONFIG_PATH, "r") as f:
    cfg = json.load(f)

# Serial
SERIAL_PORT     = cfg["serial"]["port"]
BAUD_RATE       = cfg["serial"]["baud_rate"]
SEND_INTERVAL   = cfg["serial"]["send_interval_ms"] / 1000.0
RECONNECT_DELAY = cfg["serial"]["reconnect_delay_s"]

# PS4 axes
DEADZONE        = cfg["ps4"]["deadzone"]
AXIS_LX         = cfg["ps4"]["axis_lx"]
AXIS_LY         = cfg["ps4"]["axis_ly"]
AXIS_RX         = cfg["ps4"]["axis_rx"]
AXIS_RY         = cfg["ps4"]["axis_ry"]
INVERT_LY       = cfg["ps4"]["invert_ly"]
INVERT_RY       = cfg["ps4"]["invert_ry"]

# PS4 buttons
KILL_BUTTON     = cfg["ps4"]["kill_button"]            # Circle
SLOW_BUTTON     = cfg["ps4"]["slow_mode_button"]       # L1
SERVO_A_BTN     = cfg["ps4"]["servo_pos_a_button"]     # Square  → pos_a
SERVO_B_BTN     = cfg["ps4"]["servo_pos_b_button"]     # Cross/X → pos_b

# Drive motors
MAX_PWM         = cfg["motors"]["max_pwm"]
SPEED_CAP       = cfg["motors"]["speed_cap"]
SLOW_FACTOR     = cfg["motors"]["slow_mode_factor"]

# Ramp
RAMP_ENABLED    = cfg["ramp"]["enabled"]
ACCEL_RATE      = cfg["ramp"]["accel_rate"]
DECEL_RATE      = cfg["ramp"]["decel_rate"]

# Mecanum inversion
INVERT_LF       = cfg["mecanum"]["invert_LF"]
INVERT_RF       = cfg["mecanum"]["invert_RF"]
INVERT_LB       = cfg["mecanum"]["invert_LB"]
INVERT_RB       = cfg["mecanum"]["invert_RB"]

# Encoders
ENC_ENABLED     = cfg["encoder"]["enabled"]
ENC_INTERVAL    = cfg["encoder"]["read_interval_ms"] / 1000.0

# Extra motors
EM_SPEED_CAP_M5   = cfg["extra_motors"]["speed_cap_m5"]
EM_SPEED_CAP_M6   = cfg["extra_motors"]["speed_cap_m6"]
INVERT_M5         = cfg["extra_motors"]["invert_M5"]
INVERT_M6         = cfg["extra_motors"]["invert_M6"]
EM_SYNC_STRENGTH  = cfg["extra_motors"]["sync_strength"]

# Servos
S1_DEFAULT  = cfg["servos"]["servo1"]["default_pos"]
S1_POS_A    = cfg["servos"]["servo1"]["pos_a"]
S1_POS_B    = cfg["servos"]["servo1"]["pos_b"]
S1_MIN      = cfg["servos"]["servo1"]["min_pos"]
S1_MAX      = cfg["servos"]["servo1"]["max_pos"]
S1_SPEED    = cfg["servos"]["servo1"]["speed"]

S2_DEFAULT  = cfg["servos"]["servo2"]["default_pos"]
S2_POS_A    = cfg["servos"]["servo2"]["pos_a"]
S2_POS_B    = cfg["servos"]["servo2"]["pos_b"]
S2_MIN      = cfg["servos"]["servo2"]["min_pos"]
S2_MAX      = cfg["servos"]["servo2"]["max_pos"]
S2_SPEED    = cfg["servos"]["servo2"]["speed"]


# ═══════════════════════════════════════════════════
# SERIAL CONNECTION WITH AUTO-RECONNECT
# ═══════════════════════════════════════════════════

class SerialConnection:
    """Safe serial wrapper — auto-reconnects on disconnect."""

    def __init__(self, port, baud):
        self.port = port
        self.baud = baud
        self.ser = None
        self.connected = False

    def connect(self):
        try:
            if self.ser:
                self.ser.close()
        except:
            pass
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
            time.sleep(2)
            self.connected = True
            print(f"[OK] Arduino on {self.port}")
            return True
        except serial.SerialException:
            self.connected = False
            return False

    def connect_blocking(self):
        while not self.connect():
            print(f"[WAIT] Arduino not found on {self.port}, retrying...")
            time.sleep(RECONNECT_DELAY)

    def write(self, data):
        if not self.connected:
            return False
        try:
            if isinstance(data, str):
                data = data.encode()
            self.ser.write(data)
            return True
        except (serial.SerialException, OSError):
            self.connected = False
            print("\n[ERROR] Serial disconnected!")
            return False

    def readline(self):
        if not self.connected:
            return ""
        try:
            if self.ser.in_waiting > 0:
                return self.ser.readline().decode().strip()
        except (serial.SerialException, OSError, UnicodeDecodeError):
            self.connected = False
        return ""

    def close(self):
        try:
            if self.ser:
                self.ser.close()
        except:
            pass
        self.connected = False


# ═══════════════════════════════════════════════════
# PS4 CONNECTION
# ═══════════════════════════════════════════════════

def connect_ps4():
    pygame.init()
    pygame.joystick.init()
    while pygame.joystick.get_count() == 0:
        print("[WAIT] No PS4 controller. Pair via Bluetooth first.")
        pygame.joystick.quit()
        time.sleep(2)
        pygame.joystick.init()
    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"[OK] Controller: {js.get_name()}")
    return js


# ═══════════════════════════════════════════════════
# DEADZONE
# ═══════════════════════════════════════════════════

def apply_deadzone(value, cap=None):
    if cap is None:
        cap = SPEED_CAP
    scaled = int(value * cap)
    return 0 if abs(scaled) < DEADZONE else scaled


# ═══════════════════════════════════════════════════
# MECANUM KINEMATICS
# ═══════════════════════════════════════════════════

def mecanum_drive(strafe, drive, rotate):
    lf = drive + strafe + rotate
    rf = drive - strafe - rotate
    lb = drive - strafe + rotate
    rb = drive + strafe - rotate

    max_val = max(abs(lf), abs(rf), abs(lb), abs(rb))
    if max_val > SPEED_CAP:
        lf = int(lf * SPEED_CAP / max_val)
        rf = int(rf * SPEED_CAP / max_val)
        lb = int(lb * SPEED_CAP / max_val)
        rb = int(rb * SPEED_CAP / max_val)

    if INVERT_LF: lf = -lf
    if INVERT_RF: rf = -rf
    if INVERT_LB: lb = -lb
    if INVERT_RB: rb = -rb

    def to_pwm(val):
        pwm = int(abs(val) * MAX_PWM / SPEED_CAP)
        pwm = min(pwm, MAX_PWM)
        return pwm if val >= 0 else -pwm

    return to_pwm(lf), to_pwm(rf), to_pwm(lb), to_pwm(rb)


# ═══════════════════════════════════════════════════
# ACCELERATION RAMP
# ═══════════════════════════════════════════════════

class AccelRamp:
    def __init__(self, accel, decel):
        self.accel = accel
        self.decel = decel
        self.current = [0, 0, 0, 0]

    def update(self, targets):
        result = []
        for i in range(4):
            target = targets[i]
            cur    = self.current[i]
            diff   = target - cur

            if abs(diff) <= 1:
                cur = target
            elif abs(target) >= abs(cur) or (target > 0 > cur) or (target < 0 < cur):
                cur = min(cur + self.accel, target) if diff > 0 else max(cur - self.accel, target)
            else:
                cur = min(cur + self.decel, target) if diff > 0 else max(cur - self.decel, target)

            self.current[i] = cur
            result.append(cur)
        return tuple(result)

    def reset(self):
        self.current = [0, 0, 0, 0]


# ═══════════════════════════════════════════════════
# SEND COMMANDS TO ARDUINO
# ═══════════════════════════════════════════════════

def send_motors(conn, lf, rf, lb, rb):
    return conn.write(f"<M,{lf},{rf},{lb},{rb}>\n")

def send_extra_motors(conn, m5_pct, m6_pct):
    return conn.write(f"<X,{m5_pct},{m6_pct}>\n")

def send_servo(conn, servo_id, position):
    return conn.write(f"<S,{servo_id},{position}>\n")

def send_extra_motor_sync_config(conn):
    """Send sync strength (×100 as integer) to Arduino."""
    sync_val = int(EM_SYNC_STRENGTH * 100)
    return conn.write(f"<XCFG,{sync_val}>\n")

def send_servo_config(conn, servo_id, speed, min_pos, max_pos):
    return conn.write(f"<SCFG,{servo_id},{speed},{min_pos},{max_pos}>\n")

def send_startup_config(conn):
    """Push all tunable config to Arduino right after connecting."""
    time.sleep(0.1)
    send_extra_motor_sync_config(conn);  time.sleep(0.05)
    send_servo_config(conn, 1, S1_SPEED, S1_MIN, S1_MAX); time.sleep(0.05)
    send_servo_config(conn, 2, S2_SPEED, S2_MIN, S2_MAX); time.sleep(0.05)
    send_servo(conn, 1, S1_DEFAULT); time.sleep(0.05)
    send_servo(conn, 2, S2_DEFAULT); time.sleep(0.05)
    print("[CFG] Sync + Servo config sent to Arduino")


# ═══════════════════════════════════════════════════
# BUTTON HELPERS
# ═══════════════════════════════════════════════════

class ButtonEdge:
    """Fires once on button press (rising edge), not a toggle."""
    def __init__(self):
        self.prev = False

    def pressed(self, current):
        fired     = current and not self.prev
        self.prev = current
        return fired


# ═══════════════════════════════════════════════════
# ENCODER READER (background thread)
# ═══════════════════════════════════════════════════

encoder_data = {"lf": 0, "rf": 0, "lb": 0, "rb": 0, "m5": 0, "m6": 0}
enc_lock     = threading.Lock()

def encoder_thread(conn):
    while True:
        time.sleep(ENC_INTERVAL)
        if not conn.connected:
            continue

        # ── Drive encoders ──
        conn.write("<E>\n")
        time.sleep(0.01)
        line = conn.readline()
        if line.startswith("E,"):
            parts = line.split(",")
            if len(parts) == 5:
                try:
                    with enc_lock:
                        encoder_data["lf"] = int(parts[1])
                        encoder_data["rf"] = int(parts[2])
                        encoder_data["lb"] = int(parts[3])
                        encoder_data["rb"] = int(parts[4])
                except ValueError:
                    pass

        # ── Extra motor encoders ──
        conn.write("<EX>\n")
        time.sleep(0.01)
        line = conn.readline()
        if line.startswith("EX,"):
            parts = line.split(",")
            if len(parts) == 3:
                try:
                    with enc_lock:
                        encoder_data["m5"] = int(parts[1])
                        encoder_data["m6"] = int(parts[2])
                except ValueError:
                    pass


# ═══════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════

def main():
    hz = int(1000 / cfg["serial"]["send_interval_ms"])
    print("╔══════════════════════════════════════════╗")
    print("║  R1 Controller — Robocon 2026            ║")
    print("╚══════════════════════════════════════════╝")
    print(f"[CFG] Port={SERIAL_PORT} Baud={BAUD_RATE} Rate={hz}Hz")
    print(f"      Deadzone={DEADZONE} MaxPWM={MAX_PWM} SpeedCap={SPEED_CAP}")
    print(f"      Axes: LX=A{AXIS_LX} LY=A{AXIS_LY} RX=A{AXIS_RX} RY=A{AXIS_RY}")
    print(f"      Ramp: {'ON' if RAMP_ENABLED else 'OFF'} (accel={ACCEL_RATE}, decel={DECEL_RATE})")
    print(f"      Inversions: LF={INVERT_LF} RF={INVERT_RF} LB={INVERT_LB} RB={INVERT_RB}")
    print(f"      Extra Motors: M5_cap={EM_SPEED_CAP_M5} M6_cap={EM_SPEED_CAP_M6} "
          f"inv_M5={INVERT_M5} inv_M6={INVERT_M6}")
    print(f"      Sync Strength: {EM_SYNC_STRENGTH}")
    print(f"      Servo1: default={S1_DEFAULT} A={S1_POS_A} B={S1_POS_B} spd={S1_SPEED}")
    print(f"      Servo2: default={S2_DEFAULT} A={S2_POS_A} B={S2_POS_B} spd={S2_SPEED}")
    print(f"      Encoders: {'ON' if ENC_ENABLED else 'OFF'}")

    # Connect hardware
    conn = SerialConnection(SERIAL_PORT, BAUD_RATE)
    conn.connect_blocking()
    send_startup_config(conn)   # push sync + servo config to Arduino

    js = connect_ps4()

    # Init systems
    ramp = AccelRamp(ACCEL_RATE, DECEL_RATE)

    # Servo edge detectors
    servo_a_edge    = ButtonEdge()
    servo_b_edge    = ButtonEdge()
    current_s1_pos  = S1_DEFAULT
    current_s2_pos  = S2_DEFAULT

    # Kill switch
    killed    = False
    kill_prev = False

    # Encoder thread
    if ENC_ENABLED:
        t = threading.Thread(target=encoder_thread, args=(conn,), daemon=True)
        t.start()
        print("[OK] Encoder thread started")

    last_send = 0

    print(f"\n[RUNNING] R1 Active")
    print(f"  Left Stick     = Drive + Strafe")
    print(f"  Right Stick X  = Rotate")
    print(f"  Right Stick Y  = Extra motors M5+M6 (PID RPM-sync)")
    print(f"  B{KILL_BUTTON} (Circle)  = KILL SWITCH (toggle)")
    print(f"  B{SLOW_BUTTON} (L1)      = Slow mode (hold)")
    print(f"  B{SERVO_A_BTN} (Square)  = Servos → pos_a ({S1_POS_A}°, {S2_POS_A}°)")
    print(f"  B{SERVO_B_BTN} (Cross)   = Servos → pos_b ({S1_POS_B}°, {S2_POS_B}°)")
    print(f"  Ctrl+C         = Exit\n")

    try:
        while True:
            pygame.event.pump()

            # Rate limiting
            now = time.time()
            if now - last_send < SEND_INTERVAL:
                time.sleep(0.001)
                continue
            last_send = now

            # ── Auto-reconnect ──
            if not conn.connected:
                print("\r[RECONNECT] Trying...", end='')
                ramp.reset()
                if conn.connect():
                    send_startup_config(conn)
                    send_servo(conn, 1, current_s1_pos)
                    send_servo(conn, 2, current_s2_pos)
                    print("\r[OK] Reconnected!                              ")
                else:
                    time.sleep(RECONNECT_DELAY)
                    continue

            # ── Kill switch (Circle) ──
            kill_now = js.get_button(KILL_BUTTON)
            if kill_now and not kill_prev:
                killed = not killed
                if killed:
                    ramp.reset()
                    send_motors(conn, 0, 0, 0, 0)
                    send_extra_motors(conn, 0, 0)
                    print(f"\r[!! KILLED !!] All stopped. Press Circle to resume.              ", end='')
                else:
                    print(f"\r[RESUMED] Control restored.                                       ", end='')
            kill_prev = kill_now

            if killed:
                send_motors(conn, 0, 0, 0, 0)
                send_extra_motors(conn, 0, 0)
                continue

            # ══════════════════════════════════════
            # SERVO CONTROLS
            # Square → pos_a | Cross → pos_b
            # ══════════════════════════════════════

            if servo_a_edge.pressed(js.get_button(SERVO_A_BTN)):
                current_s1_pos = S1_POS_A
                current_s2_pos = S2_POS_A
                send_servo(conn, 1, current_s1_pos)
                send_servo(conn, 2, current_s2_pos)

            if servo_b_edge.pressed(js.get_button(SERVO_B_BTN)):
                current_s1_pos = S1_POS_B
                current_s2_pos = S2_POS_B
                send_servo(conn, 1, current_s1_pos)
                send_servo(conn, 2, current_s2_pos)

            # ══════════════════════════════════════
            # DRIVING (mecanum)
            # ══════════════════════════════════════

            lx_raw  = js.get_axis(AXIS_LX)
            ly_raw  = js.get_axis(AXIS_LY)
            rx_raw  = js.get_axis(AXIS_RX)

            lx = apply_deadzone(lx_raw)
            ly = apply_deadzone(-ly_raw if INVERT_LY else ly_raw)
            rx = apply_deadzone(rx_raw)

            # Slow mode
            slow_mode = js.get_button(SLOW_BUTTON)
            if slow_mode:
                lx = int(lx * SLOW_FACTOR)
                ly = int(ly * SLOW_FACTOR)
                rx = int(rx * SLOW_FACTOR)

            target_lf, target_rf, target_lb, target_rb = mecanum_drive(lx, ly, rx)

            if RAMP_ENABLED:
                lf, rf, lb, rb = ramp.update((target_lf, target_rf, target_lb, target_rb))
            else:
                lf, rf, lb, rb = target_lf, target_rf, target_lb, target_rb

            send_motors(conn, int(lf), int(rf), int(lb), int(rb))

            # ══════════════════════════════════════
            # EXTRA MOTORS M5 + M6
            # Right joystick Y-axis only
            # ══════════════════════════════════════

            ry_raw = js.get_axis(AXIS_RY)
            if INVERT_RY:
                ry_raw = -ry_raw

            # Scale to [-100, +100] then apply per-motor caps
            ry_pct = apply_deadzone(ry_raw, cap=100)

            if slow_mode:
                ry_pct = int(ry_pct * SLOW_FACTOR)

            # Per-motor speed cap (scale from 100 down to cap)
            m5_pct = int(ry_pct * EM_SPEED_CAP_M5 / 100)
            m6_pct = int(ry_pct * EM_SPEED_CAP_M6 / 100)

            # Per-motor direction inversion
            if INVERT_M5: m5_pct = -m5_pct
            if INVERT_M6: m6_pct = -m6_pct

            # Convert percentage to direct PWM (0-255)
            m5_pwm = int(m5_pct * MAX_PWM / 100)
            m6_pwm = int(m6_pct * MAX_PWM / 100)

            send_extra_motors(conn, m5_pwm, m6_pwm)

            # ── Status display ──
            status = "SLOW" if slow_mode else " OK "
            s1_lbl = f"S1:{current_s1_pos:3d}"
            s2_lbl = f"S2:{current_s2_pos:3d}"

            enc_str = ""
            if ENC_ENABLED:
                with enc_lock:
                    enc_str = (
                        f" DRV[{encoder_data['lf']:+5d},{encoder_data['rf']:+5d},"
                        f"{encoder_data['lb']:+5d},{encoder_data['rb']:+5d}]"
                        f" EXT[M5:{encoder_data['m5']:+5d} M6:{encoder_data['m6']:+5d}]"
                    )

            print(
                f"\r[{status}] "
                f"L[{lx:+4d},{ly:+4d}] R[{rx:+4d},{ry_pct:+4d}] "
                f"PWM[{int(lf):+4d},{int(rf):+4d},{int(lb):+4d},{int(rb):+4d}] "
                f"EXT[{m5_pct:+4d},{m6_pct:+4d}] "
                f"{s1_lbl} {s2_lbl}{enc_str}    ",
                end=''
            )

    except KeyboardInterrupt:
        print("\n\n[STOP] Shutting down...")
        try:
            ramp.reset()
            send_motors(conn, 0, 0, 0, 0)
            send_extra_motors(conn, 0, 0)
            time.sleep(0.1)
        except:
            pass
    finally:
        try:
            conn.close()
        except:
            pass
        pygame.quit()
        print("[EXIT] Done.")


if __name__ == '__main__':
    main()