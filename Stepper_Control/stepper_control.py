"""
╔══════════════════════════════════════════════════════════════╗
║  STEPPER MOTOR CONTROL — Jetson Nano Master Controller      ║
║  PS4 Controller → Jetson Nano → Arduino Mega → T60S        ║
╚══════════════════════════════════════════════════════════════╝

CONTROLS:
  Left Stick Y       = Stepper speed + direction
                       (push forward = CW, pull back = CCW)
  B1 (Circle)        = EMERGENCY STOP toggle
  B4 (L1)            = Slow mode (hold)
  B3 (Square)        = Home / Reset position
  Ctrl+C             = Exit

PROTOCOL TO ARDUINO:
  <ST,speed,dir>     → Stepper command
                        speed = pulses per second (0 = stop)
                        dir   = 1 (CW) or 0 (CCW)
  <STOP>             → Emergency stop stepper
  <HOME>             → Return to home position

REQUIREMENTS:
  pip install pygame pyserial
"""

import pygame
import serial
import json
import time
import os
import sys


# ═══════════════════════════════════════════════════
# LOAD CONFIG
# ═══════════════════════════════════════════════════

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stepper_config.json")

try:
    with open(CONFIG_PATH, "r") as f:
        cfg = json.load(f)
    print(f"[OK] Config loaded from {CONFIG_PATH}")
except FileNotFoundError:
    print(f"[ERROR] Config file not found: {CONFIG_PATH}")
    sys.exit(1)

# Serial
SERIAL_PORT     = cfg["serial"]["port"]
BAUD_RATE       = cfg["serial"]["baud_rate"]
SEND_INTERVAL   = cfg["serial"]["send_interval_ms"] / 1000.0
RECONNECT_DELAY = cfg["serial"]["reconnect_delay_s"]

# PS4 axes
AXIS_LY         = cfg["ps4"]["axis_ly"]
DEADZONE        = cfg["ps4"]["deadzone"]
INVERT_LY       = cfg["ps4"]["invert_ly"]

# Stepper
MAX_SPEED_PPS   = cfg["stepper"]["max_speed_pps"]    # Max pulses per second
MIN_SPEED_PPS   = cfg["stepper"]["min_speed_pps"]    # Min pulses per second (below this = stop)
ACCEL_RATE      = cfg["stepper"]["accel_rate"]        # PPS increase per control cycle
DECEL_RATE      = cfg["stepper"]["decel_rate"]        # PPS decrease per control cycle

# Controls
KILL_BUTTON     = cfg["controls"]["kill_button"]      # Circle
SLOW_BUTTON     = cfg["controls"]["slow_mode_button"] # L1
SLOW_FACTOR     = cfg["controls"]["slow_factor"]
HOME_BUTTON     = cfg["controls"]["home_button"]      # Square


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
            time.sleep(2)  # Wait for Arduino to reset after serial connection
            self.connected = True
            # Flush any startup garbage
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            print(f"[OK] Arduino connected on {self.port}")
            return True
        except serial.SerialException as e:
            self.connected = False
            return False

    def connect_blocking(self):
        """Block until Arduino is connected."""
        while not self.connect():
            print(f"[WAIT] Arduino not found on {self.port}, retrying in {RECONNECT_DELAY}s...")
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
# PS4 CONTROLLER CONNECTION
# ═══════════════════════════════════════════════════

def connect_ps4():
    """Wait for PS4 controller to connect."""
    pygame.init()
    pygame.joystick.init()
    while pygame.joystick.get_count() == 0:
        print("[WAIT] No PS4 controller detected. Pair via Bluetooth first.")
        pygame.joystick.quit()
        time.sleep(2)
        pygame.joystick.init()
    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"[OK] Controller: {js.get_name()}")
    return js


# ═══════════════════════════════════════════════════
# JOYSTICK → STEPPER SPEED MAPPING
# ═══════════════════════════════════════════════════

def joystick_to_velocity(axis_value, slow_mode=False):
    """
    Convert joystick axis value (-1.0 to +1.0) to stepper velocity.
    
    Returns:
        target_velocity (negative for CCW, positive for CW)
    """
    # Apply inversion (so pushing forward = positive)
    if INVERT_LY:
        axis_value = -axis_value

    # Apply deadzone
    if abs(axis_value) < DEADZONE:
        return 0

    # Remove deadzone from range for smooth response
    # Map [DEADZONE, 1.0] → [0.0, 1.0]
    sign = 1 if axis_value > 0 else -1
    magnitude = (abs(axis_value) - DEADZONE) / (1.0 - DEADZONE)
    magnitude = min(magnitude, 1.0)  # Clamp

    # Apply slow mode
    if slow_mode:
        magnitude *= SLOW_FACTOR

    # Map to speed range
    speed_pps = int(magnitude * MAX_SPEED_PPS)

    # Below minimum threshold = stop
    if speed_pps < MIN_SPEED_PPS:
        return 0

    return speed_pps * sign


# ═══════════════════════════════════════════════════
# ACCELERATION RAMP (for smooth speed transitions)
# ═══════════════════════════════════════════════════

class StepperRamp:
    """Smoothly ramps stepper speed to prevent missed steps."""

    def __init__(self, accel_rate, decel_rate):
        self.accel_rate = accel_rate
        self.decel_rate = decel_rate
        self.current_velocity = 0

    def update(self, target_velocity):
        """Move current_velocity toward target_velocity at configured rate."""
        if self.current_velocity == target_velocity:
            return self.current_velocity

        # Accelerating if magnitude increases in the same direction
        if (target_velocity > 0 and self.current_velocity >= 0 and target_velocity > self.current_velocity) or \
           (target_velocity < 0 and self.current_velocity <= 0 and target_velocity < self.current_velocity):
            rate = self.accel_rate
        else:
            # Decelerating (or reversing direction)
            rate = self.decel_rate

        if target_velocity > self.current_velocity:
            self.current_velocity += rate
            if self.current_velocity > target_velocity:
                self.current_velocity = target_velocity
        else:
            self.current_velocity -= rate
            if self.current_velocity < target_velocity:
                self.current_velocity = target_velocity

        return self.current_velocity

    def reset(self):
        self.current_velocity = 0


# ═══════════════════════════════════════════════════
# SEND COMMANDS TO ARDUINO
# ═══════════════════════════════════════════════════

def send_stepper(conn, speed_pps, direction):
    """Send stepper speed command: <ST,speed,dir>"""
    return conn.write(f"<ST,{speed_pps},{direction}>\n")

def send_stop(conn):
    """Send emergency stop command."""
    return conn.write("<STOP>\n")

def send_home(conn):
    """Send home/reset position command."""
    return conn.write("<HOME>\n")


# ═══════════════════════════════════════════════════
# BUTTON EDGE DETECTOR
# ═══════════════════════════════════════════════════

class ButtonEdge:
    """Fires once on button press (rising edge)."""
    def __init__(self):
        self.prev = False

    def pressed(self, current):
        fired = current and not self.prev
        self.prev = current
        return fired


# ═══════════════════════════════════════════════════
# READ ARDUINO FEEDBACK
# ═══════════════════════════════════════════════════

def read_arduino_feedback(conn):
    """Read and display any feedback from Arduino."""
    line = conn.readline()
    if line:
        if line.startswith("["):
            # Status/debug message from Arduino
            pass  # Suppress to keep display clean
        elif line.startswith("POS,"):
            # Position feedback: POS,step_count
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    return int(parts[1])
                except ValueError:
                    pass
    return None


# ═══════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════

def main():
    hz = int(1000 / cfg["serial"]["send_interval_ms"])

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  STEPPER MOTOR CONTROLLER — Robocon 2026                    ║")
    print("║  PS4 → Jetson Nano → Arduino Mega → T60S → Stepper          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"[CFG] Port={SERIAL_PORT} Baud={BAUD_RATE} Rate={hz}Hz")
    print(f"      Max Speed={MAX_SPEED_PPS} PPS  Min Speed={MIN_SPEED_PPS} PPS")
    print(f"      Accel={ACCEL_RATE} PPS/cycle  Decel={DECEL_RATE} PPS/cycle")
    print(f"      Deadzone={DEADZONE}  Slow Factor={SLOW_FACTOR}")

    # ── Connect hardware ──
    conn = SerialConnection(SERIAL_PORT, BAUD_RATE)
    conn.connect_blocking()

    js = connect_ps4()

    # ── Init systems ──
    ramp = StepperRamp(ACCEL_RATE, DECEL_RATE)

    # Button edge detectors
    kill_edge = ButtonEdge()
    home_edge = ButtonEdge()

    killed = False
    step_position = 0
    last_send = 0

    print(f"\n[RUNNING] Stepper Controller Active")
    print(f"  Left Stick Y   = Speed + Direction")
    print(f"  B{KILL_BUTTON} (Circle)  = EMERGENCY STOP (toggle)")
    print(f"  B{SLOW_BUTTON} (L1)      = Slow mode (hold)")
    print(f"  B{HOME_BUTTON} (Square)  = Home position")
    print(f"  Ctrl+C         = Exit\n")

    try:
        while True:
            pygame.event.pump()

            # ── Rate limiting ──
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
                    print("\r[OK] Reconnected!                              ")
                else:
                    time.sleep(RECONNECT_DELAY)
                    continue

            # ── Read Arduino feedback ──
            pos = read_arduino_feedback(conn)
            if pos is not None:
                step_position = pos

            # ── Kill switch (Circle) ──
            if kill_edge.pressed(js.get_button(KILL_BUTTON)):
                killed = not killed
                if killed:
                    ramp.reset()
                    send_stop(conn)
                    print(f"\r[!! EMERGENCY STOP !!] Press Circle to resume.                  ", end='')
                else:
                    print(f"\r[RESUMED] Control restored.                                     ", end='')

            if killed:
                send_stop(conn)
                continue

            # ── Home button (Square) ──
            if home_edge.pressed(js.get_button(HOME_BUTTON)):
                ramp.reset()
                send_home(conn)
                step_position = 0
                print(f"\r[HOME] Returning to home position...                             ", end='')

            # ── Read joystick ──
            ly_raw = js.get_axis(AXIS_LY)
            slow_mode = js.get_button(SLOW_BUTTON)

            # Map joystick to target velocity
            target_velocity = joystick_to_velocity(ly_raw, slow_mode)

            # Apply acceleration ramp
            ramped_velocity = ramp.update(target_velocity)
            
            # Extract speed and direction
            ramped_speed = abs(ramped_velocity)
            direction = 1 if ramped_velocity >= 0 else 0

            # Always send command every cycle (keeps Arduino safety timeout alive)
            send_stepper(conn, ramped_speed, direction)

            # ── Status display ──
            bar_len = 20
            bar_fill = int((ramped_speed / MAX_SPEED_PPS) * bar_len) if MAX_SPEED_PPS > 0 else 0
            bar = "█" * bar_fill + "░" * (bar_len - bar_fill)

            dir_str = "CW ↻" if direction == 1 else "CCW ↺"
            mode_str = "SLOW" if slow_mode else " OK "

            print(
                f"\r[{mode_str}] "
                f"Joy:{ly_raw:+.2f} → "
                f"SPD:{ramped_speed:5d}/{MAX_SPEED_PPS} PPS "
                f"[{bar}] "
                f"{dir_str} "
                f"POS:{step_position:+8d}    ",
                end=''
            )

    except KeyboardInterrupt:
        print("\n\n[STOP] Shutting down...")
        try:
            ramp.reset()
            send_stop(conn)
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
