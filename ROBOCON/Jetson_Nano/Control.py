"""
╔══════════════════════════════════════════════════════════════╗
║  R1 - Raspberry Pi MASTER CONTROLLER                         ║
║  Robocon 2026 "Kung Fu Quest"                                ║
╚══════════════════════════════════════════════════════════════╝

CONTROLS:
  Left Stick      = Drive + Strafe
  Right Stick X   = Rotate
  B1 (Circle)     = EMERGENCY STOP toggle
  B4 (L1)         = Slow mode (hold)
  B2 (Triangle)   = Toggle BOTH pneumatics on/off
  B6 (L2)         = Toggle pneumatic 1 on/off
  B7 (R2)         = Toggle pneumatic 2 on/off
  Ctrl+C          = Exit

PROTOCOL TO ARDUINO:
  <M,LF,RF,LB,RB>   → Motor PWM (-255 to +255)
  <P,id,state>       → Pneumatic (id=1or2, state=0or1)
  <E>                → Request encoder ticks
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
AXIS_LX         = cfg["ps4"]["axis_lx"]       # 0
AXIS_LY         = cfg["ps4"]["axis_ly"]       # 1
AXIS_RX         = cfg["ps4"]["axis_rx"]       # 3
INVERT_LY       = cfg["ps4"]["invert_ly"]

# PS4 buttons
KILL_BUTTON     = cfg["ps4"]["kill_button"]            # B1 Circle
SLOW_BUTTON     = cfg["ps4"]["slow_mode_button"]       # B4 L1
PNEU_BOTH_BTN   = cfg["ps4"]["pneumatic_both_button"]  # B2 Triangle
PNEU_1_BTN      = cfg["ps4"]["pneumatic_1_button"]     # B6 L2
PNEU_2_BTN      = cfg["ps4"]["pneumatic_2_button"]     # B7 R2

# Motors
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

def apply_deadzone(value):
    scaled = int(value * SPEED_CAP)
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
            cur = self.current[i]
            diff = target - cur

            if abs(diff) <= 1:
                cur = target
            elif abs(target) >= abs(cur) or (target > 0 > cur) or (target < 0 < cur):
                if diff > 0:
                    cur = min(cur + self.accel, target)
                else:
                    cur = max(cur - self.accel, target)
            else:
                if diff > 0:
                    cur = min(cur + self.decel, target)
                else:
                    cur = max(cur - self.decel, target)

            self.current[i] = cur
            result.append(cur)
        return tuple(result)

    def reset(self):
        self.current = [0, 0, 0, 0]


# ═══════════════════════════════════════════════════
# SEND COMMANDS TO ARDUINO
# ═══════════════════════════════════════════════════

def send_motors(conn, lf, rf, lb, rb):
    """Send <M,LF,RF,LB,RB> to Arduino."""
    return conn.write(f"<M,{lf},{rf},{lb},{rb}>\n")

def send_pneumatic(conn, pneu_id, state):
    """
    Send <P,id,state> to Arduino.
    pneu_id: 1 or 2
    state: True/False → sent as 1/0
    """
    s = 1 if state else 0
    return conn.write(f"<P,{pneu_id},{s}>\n")


# ═══════════════════════════════════════════════════
# BUTTON TOGGLE HELPER
# ═══════════════════════════════════════════════════

class ButtonToggle:
    """
    Detects button press EDGE (not hold).
    Toggles a state on each press.
    
    Why edge detection?
      Without it: holding a button rapidly toggles on/off every cycle.
      With it: one press = one toggle, no matter how long you hold.
    """
    def __init__(self):
        self.prev = False    # Previous frame button state
        self.state = False   # Current toggle state (on/off)

    def update(self, pressed):
        """
        Call every cycle with current button state.
        Returns True only on the cycle when state actually changes.
        """
        changed = False
        if pressed and not self.prev:
            # Button just pressed (rising edge) — toggle
            self.state = not self.state
            changed = True
        self.prev = pressed
        return changed


# ═══════════════════════════════════════════════════
# ENCODER READER (background thread)
# ═══════════════════════════════════════════════════

encoder_data = {"lf": 0, "rf": 0, "lb": 0, "rb": 0}
enc_lock = threading.Lock()

def encoder_thread(conn):
    while True:
        time.sleep(ENC_INTERVAL)
        if not conn.connected:
            continue
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
    print(f"      Axes: LX=A{AXIS_LX} LY=A{AXIS_LY} RX=A{AXIS_RX}")
    print(f"      Ramp: {'ON' if RAMP_ENABLED else 'OFF'} (accel={ACCEL_RATE}, decel={DECEL_RATE})")
    print(f"      Inversions: LF={INVERT_LF} RF={INVERT_RF} LB={INVERT_LB} RB={INVERT_RB}")
    print(f"      Kill=B{KILL_BUTTON} Slow=B{SLOW_BUTTON}")
    print(f"      Pneumatics: Both=B{PNEU_BOTH_BTN} P1=B{PNEU_1_BTN} P2=B{PNEU_2_BTN}")
    print(f"      Encoders: {'ON' if ENC_ENABLED else 'OFF'}")

    # Connect hardware
    conn = SerialConnection(SERIAL_PORT, BAUD_RATE)
    conn.connect_blocking()
    js = connect_ps4()

    # Init systems
    ramp = AccelRamp(ACCEL_RATE, DECEL_RATE)

    # Pneumatic toggle states
    pneu1_toggle = ButtonToggle()   # L2 → pneumatic 1
    pneu2_toggle = ButtonToggle()   # R2 → pneumatic 2
    pneu_both_toggle = ButtonToggle()  # Triangle → both

    # Kill switch state
    killed = False
    kill_prev = False

    # Encoder thread
    if ENC_ENABLED:
        t = threading.Thread(target=encoder_thread, args=(conn,), daemon=True)
        t.start()
        print("[OK] Encoder thread started")

    last_send = 0

    print(f"\n[RUNNING] R1 Active")
    print(f"  Left Stick    = Drive + Strafe")
    print(f"  Right Stick X = Rotate")
    print(f"  B{KILL_BUTTON} (Circle)   = KILL SWITCH (toggle)")
    print(f"  B{SLOW_BUTTON} (L1)       = Slow mode (hold)")
    print(f"  B{PNEU_BOTH_BTN} (Triangle) = Both pneumatics toggle")
    print(f"  B{PNEU_1_BTN} (L2)       = Pneumatic 1 toggle")
    print(f"  B{PNEU_2_BTN} (R2)       = Pneumatic 2 toggle")
    print(f"  Ctrl+C        = Exit\n")

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
                    # Re-send current pneumatic states after reconnect
                    send_pneumatic(conn, 1, pneu1_toggle.state)
                    send_pneumatic(conn, 2, pneu2_toggle.state)
                    print("\r[OK] Reconnected!                              ")
                else:
                    time.sleep(RECONNECT_DELAY)
                    continue

            # ── Kill switch (Circle, toggle on press) ──
            kill_now = js.get_button(KILL_BUTTON)
            if kill_now and not kill_prev:
                killed = not killed
                if killed:
                    ramp.reset()
                    send_motors(conn, 0, 0, 0, 0)
                    # Turn off both pneumatics on kill
                    pneu1_toggle.state = False
                    pneu2_toggle.state = False
                    pneu_both_toggle.state = False
                    send_pneumatic(conn, 1, False)
                    send_pneumatic(conn, 2, False)
                    print(f"\r[!! KILLED !!] All stopped. Press Circle to resume.                    ", end='')
                else:
                    print(f"\r[RESUMED] Control restored.                                             ", end='')
            kill_prev = kill_now

            if killed:
                send_motors(conn, 0, 0, 0, 0)
                continue

            # ══════════════════════════════════════
            # PNEUMATIC CONTROLS
            # ══════════════════════════════════════

            # Triangle (B2) — toggle BOTH pneumatics together
            if pneu_both_toggle.update(js.get_button(PNEU_BOTH_BTN)):
                # Sync both individual states to match the "both" toggle
                pneu1_toggle.state = pneu_both_toggle.state
                pneu2_toggle.state = pneu_both_toggle.state
                send_pneumatic(conn, 1, pneu1_toggle.state)
                send_pneumatic(conn, 2, pneu2_toggle.state)

            # L2 (B6) — toggle pneumatic 1 individually
            if pneu1_toggle.update(js.get_button(PNEU_1_BTN)):
                send_pneumatic(conn, 1, pneu1_toggle.state)

            # R2 (B7) — toggle pneumatic 2 individually
            if pneu2_toggle.update(js.get_button(PNEU_2_BTN)):
                send_pneumatic(conn, 2, pneu2_toggle.state)

            # ══════════════════════════════════════
            # DRIVING
            # ══════════════════════════════════════

            # Read sticks
            lx = apply_deadzone(js.get_axis(AXIS_LX))
            ly_raw = js.get_axis(AXIS_LY)
            ly = apply_deadzone(-ly_raw if INVERT_LY else ly_raw)
            rx = apply_deadzone(js.get_axis(AXIS_RX))

            # Slow mode (hold L1)
            slow_mode = js.get_button(SLOW_BUTTON)
            if slow_mode:
                lx = int(lx * SLOW_FACTOR)
                ly = int(ly * SLOW_FACTOR)
                rx = int(rx * SLOW_FACTOR)

            # Mecanum math
            target_lf, target_rf, target_lb, target_rb = mecanum_drive(lx, ly, rx)

            # Acceleration ramp
            if RAMP_ENABLED:
                lf, rf, lb, rb = ramp.update((target_lf, target_rf, target_lb, target_rb))
            else:
                lf, rf, lb, rb = target_lf, target_rf, target_lb, target_rb

            # Send to Arduino
            send_motors(conn, int(lf), int(rf), int(lb), int(rb))

            # ── Status display ──
            status = "SLOW" if slow_mode else " OK "
            p1 = "ON " if pneu1_toggle.state else "OFF"
            p2 = "ON " if pneu2_toggle.state else "OFF"

            enc_str = ""
            if ENC_ENABLED:
                with enc_lock:
                    enc_str = f" ENC[{encoder_data['lf']:+5d},{encoder_data['rf']:+5d},{encoder_data['lb']:+5d},{encoder_data['rb']:+5d}]"

            print(f"\r[{status}] Stick[{lx:+4d},{ly:+4d},{rx:+4d}] PWM[{int(lf):+4d},{int(rf):+4d},{int(lb):+4d},{int(rb):+4d}] P1:{p1} P2:{p2}{enc_str}    ", end='')

    except KeyboardInterrupt:
        print("\n\n[STOP] Shutting down...")
        try:
            ramp.reset()
            send_motors(conn, 0, 0, 0, 0)
            send_pneumatic(conn, 1, False)
            send_pneumatic(conn, 2, False)
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