"""
PS4 → Raspberry Pi → Arduino Mega  |  R2 Normal Wheel Car
===========================================================
Reads PS4 controller via Bluetooth (pygame), computes arcade-drive
mixing, handles D-pad / pneumatic buttons, and sends serial packets
to Arduino Mega over USB cable.

The Mega uses ENCODER-BASED PID CONTROL to ensure all 4 wheels
run at the commanded RPM, regardless of load or battery level.

Packet format:
  <leftRPM,rightRPM,P1,P2>\n

  leftRPM    : -60 … +60   (left motors target RPM, post arcade-mix)
  rightRPM   : -60 … +60   (right motors target RPM, post arcade-mix)
  P1         : 0 or 1      (pneumatic 1 state)
  P2         : 0 or 1      (pneumatic 2 state)

Controls:
  Left Stick   → Arcade-drive mixing  (Y=fwd/bwd, X=turn)
  D-Pad        → Per-direction RPM (fwd/bwd/turn), priority over joystick
  Triangle (△) → Toggle BOTH pneumatics
  R1           → Toggle pneumatic 1 only
  L1           → Toggle pneumatic 2 only


cd /home/r1/Desktop/ROBOCON_pi && python3 r2_pi_ps4.py


Requirements (on Raspberry Pi):
  sudo apt install python3-pygame python3-serial
  OR:  pip3 install pygame pyserial

Usage:
  python3 r2_pi_ps4.py
"""

import pygame
import serial
import serial.tools.list_ports
import time
import sys
import math

# ═══════════════════════════════════════════════════════════════
#  CONFIG  — match these to your r2_mega_serial.ino settings
# ═══════════════════════════════════════════════════════════════
BAUD_RATE           = 250000     # Must match Arduino Serial.begin()
SEND_INTERVAL       = 0.01       # 100 Hz packet rate (ultra-responsive, safe for Pi CPU)

# — Joystick tuning ————————————————————————————————————————————
JOYSTICK_MAX_RPM    = 60         # Max RPM for joystick control
DPAD_FWD_RPM        = 30         # D-pad forward speed (RPM)
DPAD_BWD_RPM        = 20         # D-pad backward speed (RPM)
DPAD_TURN_RPM       = 15         # D-pad pure rotation speed (RPM)
STICK_DEADZONE      = 10         # Raw deadzone (out of 512 equivalent)
EXPO_FACTOR         = 0.5        # 0.0 = linear, 1.0 = full cubic

# — Pygame axis / button indices for PS4 (DualShock 4) ————————
AXIS_LX             = 0          # Left stick horizontal
AXIS_LY             = 1          # Left stick vertical

# PS4 button indices (pygame)
BTN_TRIANGLE        = 3          # △ — toggle both pneumatics
BTN_L1              = 4          # L1 — toggle pneumatic 2
BTN_R1              = 5          # R1 — toggle pneumatic 1

# PS4 D-Pad is HAT 0
HAT_INDEX           = 0


# ═══════════════════════════════════════════════════════════════
#  SERIAL HELPERS
# ═══════════════════════════════════════════════════════════════
def list_ports():
    """Return list of available serial port device names."""
    return [p.device for p in serial.tools.list_ports.comports()]


def choose_port():
    """Auto-select or prompt user for a serial port.
    Prefers /dev/ttyACM* (Arduino Mega on Raspberry Pi)."""
    ports = list_ports()
    if not ports:
        print("[ERROR] No serial port found. Is the Arduino Mega plugged in via USB?")
        sys.exit(1)
    if len(ports) == 1:
        print(f"[INFO]  Auto-selected: {ports[0]}")
        return ports[0]
    # Auto-prefer /dev/ttyACM* (typical Arduino Mega on Raspberry Pi)
    for p in ports:
        if 'ttyACM' in p:
            print(f"[INFO]  Auto-selected Arduino port: {p}")
            return p
    print("\nAvailable serial ports:")
    for i, p in enumerate(ports):
        print(f"  [{i}] {p}")
    try:
        idx = int(input("Select port number: "))
        return ports[idx]
    except (ValueError, IndexError):
        print("[ERROR] Invalid selection.")
        sys.exit(1)


def ping_arduino(ser):
    """Send PING, wait for PONG to confirm connection."""
    print("[INFO]  Sending PING to Arduino...")
    ser.reset_input_buffer()
    ser.write(b"PING\n")
    time.sleep(0.5)
    response = ""
    while ser.in_waiting:
        response += ser.read(ser.in_waiting).decode("ascii", errors="ignore")
    if "PONG" in response:
        print("[OK]    Arduino responded with PONG!")
        return True
    else:
        print("[WARN]  No PONG received. Arduino may still be booting.")
        print("        (Will continue anyway — data will flow once ready)")
        return False


# ═══════════════════════════════════════════════════════════════
#  JOYSTICK PROCESSING  (replicated from r2_esp32_ota.ino)
# ═══════════════════════════════════════════════════════════════
def map_axis(raw_float):
    """
    Convert pygame axis float (-1.0 … +1.0) to target RPM
    with deadzone + expo curve, matching ESP32 mapAxis().

    pygame gives -1.0 to +1.0; ESP32 gave -512 to +512.
    We normalize to the same 0…1 range after deadzone.
    """
    # Convert to ESP32-equivalent scale (0…512)
    raw = raw_float * 512.0

    # Deadzone
    if abs(raw) < STICK_DEADZONE:
        return 0

    # Rescale [deadzone..512] → [0.0..1.0]
    sign = 1.0 if raw > 0 else -1.0
    abs_norm = (abs(raw) - STICK_DEADZONE) / (512.0 - STICK_DEADZONE)
    abs_norm = max(0.0, min(1.0, abs_norm))

    # RC-style expo curve: blend linear + cubic
    curved = (1.0 - EXPO_FACTOR) * abs_norm + EXPO_FACTOR * abs_norm ** 3

    # Scale to max RPM
    return int(sign * curved * JOYSTICK_MAX_RPM)


def arcade_mix(joy_x, joy_y, max_rpm):
    """
    Arcade-drive mixing (differential steering).
    Returns (leftRPM, rightRPM) clamped to ±max_rpm.
    """
    joy_x = max(-max_rpm, min(max_rpm, joy_x))
    joy_y = max(-max_rpm, min(max_rpm, joy_y))

    left  = max(-max_rpm, min(max_rpm, joy_y + joy_x))
    right = max(-max_rpm, min(max_rpm, joy_y - joy_x))
    return left, right


# ═══════════════════════════════════════════════════════════════
#  BUILD PACKET
# ═══════════════════════════════════════════════════════════════
def build_packet(left_speed, right_speed, p1, p2):
    """Build <leftSpeed,rightSpeed,P1,P2>\\n packet."""
    return f"<{left_speed},{right_speed},{p1},{p2}>\n".encode("ascii")


# ═══════════════════════════════════════════════════════════════
#  MODE LABEL (for display)
# ═══════════════════════════════════════════════════════════════
def get_mode_label(jx, jy):
    if jx == 0 and jy == 0:
        return "STOP"
    elif jx == 0:
        return "FORWARD" if jy > 0 else "BACKWARD"
    elif jy == 0:
        return "ROTATE CW" if jx > 0 else "ROTATE CCW"
    elif jy > 0:
        return "FWD+RIGHT" if jx > 0 else "FWD+LEFT"
    else:
        return "BWD+RIGHT" if jx > 0 else "BWD+LEFT"


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    print("=" * 56)
    print("  R2 NORMAL WHEEL CAR  —  Raspberry Pi 4 + PS4")
    print("  Encoder PID | Arcade-Drive | D-Pad | Pneumatics")
    print("=" * 56)
    print(f"  JOYSTICK_MAX_RPM   = {JOYSTICK_MAX_RPM}")
    print(f"  DPAD_FWD_RPM       = {DPAD_FWD_RPM}")
    print(f"  DPAD_BWD_RPM       = {DPAD_BWD_RPM}")
    print(f"  DPAD_TURN_RPM      = {DPAD_TURN_RPM}")
    print(f"  DEADZONE           = {STICK_DEADZONE}")
    print(f"  EXPO_FACTOR        = {EXPO_FACTOR}")
    print(f"  SEND_INTERVAL      = {SEND_INTERVAL}s ({int(1/SEND_INTERVAL)} Hz)")
    print("-" * 56)

    # ── Serial setup ──────────────────────────────────────────
    port = choose_port()
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        time.sleep(1)  # Wait for Arduino to reset after USB connection
        print(f"[OK]    Serial on {port} @ {BAUD_RATE} baud")
    except serial.SerialException as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    ping_arduino(ser)

    # ── Pygame + controller setup ─────────────────────────────
    pygame.init()
    pygame.joystick.init()

    # ── Wait for PS4 controller (retry loop for service mode) ──
    #    When running as a systemd service at boot, the controller
    #    may not be connected yet. Retry for up to 60 seconds.
    MAX_CONTROLLER_WAIT = 60  # seconds
    RETRY_INTERVAL      = 2   # seconds between retries

    js = None
    if pygame.joystick.get_count() == 0:
        print(f"[INFO]  No controller yet. Waiting up to {MAX_CONTROLLER_WAIT}s...")
        wait_start = time.time()
        while time.time() - wait_start < MAX_CONTROLLER_WAIT:
            time.sleep(RETRY_INTERVAL)
            pygame.event.pump()           # Keep pygame event loop alive
            pygame.joystick.quit()        # Re-scan for joysticks
            pygame.joystick.init()
            if pygame.joystick.get_count() > 0:
                break
            remaining = int(MAX_CONTROLLER_WAIT - (time.time() - wait_start))
            print(f"[INFO]  Still waiting for controller... ({remaining}s left)")

    if pygame.joystick.get_count() == 0:
        print("[ERROR] No controller detected after waiting.")
        print("        Pair PS4 controller via Bluetooth first:")
        print("        Hold SHARE + PS buttons until light blinks fast,")
        print("        then connect from Raspberry Pi Bluetooth settings.")
        ser.close()
        sys.exit(1)

    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"[OK]    Controller: {js.get_name()}")
    print(f"        Axes: {js.get_numaxes()}  Buttons: {js.get_numbuttons()}  Hats: {js.get_numhats()}")
    print()
    print("  Controls:")
    print("    Left Stick     → Arcade-drive (fwd/bwd + turn blended)")
    print(f"    D-Pad ↑        → Forward  ({DPAD_FWD_RPM} RPM)")
    print(f"    D-Pad ↓        → Backward ({DPAD_BWD_RPM} RPM)")
    print(f"    D-Pad ←→       → Rotate   ({DPAD_TURN_RPM} RPM)")
    print("    Triangle (△)   → Toggle BOTH pneumatics")
    print("    R1             → Toggle pneumatic 1")
    print("    L1             → Toggle pneumatic 2")
    print("    Ctrl+C         → Quit")
    print("=" * 56)

    # ── State ─────────────────────────────────────────────────
    pneu1 = 0          # Pneumatic 1 state (0=closed, 1=expanded)
    pneu2 = 0          # Pneumatic 2 state

    prev_triangle = False
    prev_r1 = False
    prev_l1 = False

    last_send = 0.0
    print_count = 0
    PRINT_EVERY_N = 20  # Only print every 20th packet (~10 Hz display)

    # ── Main loop ─────────────────────────────────────────────
    try:
        while True:
            pygame.event.get()  # Drain entire event queue (faster than pump)

            # ─── D-PAD (HAT) ─────────────────────────────────
            dpad_x, dpad_y = 0, 0
            if js.get_numhats() > HAT_INDEX:
                hat = js.get_hat(HAT_INDEX)
                dpad_x = hat[0]  # -1=left, 0=center, +1=right
                dpad_y = hat[1]  # -1=down, 0=center, +1=up

            dpad_active = (dpad_x != 0 or dpad_y != 0)

            if dpad_active:
                # D-pad: per-direction fixed RPM, takes priority over joystick
                if dpad_y > 0:
                    dy = DPAD_FWD_RPM
                elif dpad_y < 0:
                    dy = -DPAD_BWD_RPM
                else:
                    dy = 0

                if dpad_x != 0:
                    dx = dpad_x * DPAD_TURN_RPM
                else:
                    dx = 0

                max_dpad = max(DPAD_FWD_RPM, DPAD_BWD_RPM, DPAD_TURN_RPM)
                left_speed, right_speed = arcade_mix(dx, dy, max_dpad)
                source = "DPAD"
            else:
                # Joystick: proportional with expo curve
                lx_raw = js.get_axis(AXIS_LX)
                ly_raw = js.get_axis(AXIS_LY)

                jx = map_axis(lx_raw)
                jy = map_axis(-ly_raw)  # Flip: push-up = positive

                left_speed, right_speed = arcade_mix(jx, jy, JOYSTICK_MAX_RPM)
                source = "JOY"

            # ─── PNEUMATIC BUTTON TOGGLES (edge detection) ───
            # Triangle → toggle both
            tri_now = js.get_button(BTN_TRIANGLE) if js.get_numbuttons() > BTN_TRIANGLE else False
            if tri_now and not prev_triangle:
                # Rising edge — toggle both, sync to same state
                pneu1 = 1 - pneu1
                pneu2 = pneu1  # Sync both to same state
                state_str = "EXPANDED" if pneu1 else "CLOSED"
                print(f"\n[PNEU] △ Triangle → BOTH {state_str}")
            prev_triangle = tri_now

            # R1 → toggle pneumatic 1 only
            r1_now = js.get_button(BTN_R1) if js.get_numbuttons() > BTN_R1 else False
            if r1_now and not prev_r1:
                pneu1 = 1 - pneu1
                state_str = "EXPANDED" if pneu1 else "CLOSED"
                print(f"\n[PNEU] R1 → Pneumatic 1 {state_str}")
            prev_r1 = r1_now

            # L1 → toggle pneumatic 2 only
            l1_now = js.get_button(BTN_L1) if js.get_numbuttons() > BTN_L1 else False
            if l1_now and not prev_l1:
                pneu2 = 1 - pneu2
                state_str = "EXPANDED" if pneu2 else "CLOSED"
                print(f"\n[PNEU] L1 → Pneumatic 2 {state_str}")
            prev_l1 = l1_now

            # ─── SEND PACKET at 50 Hz ────────────────────────
            now = time.time()
            if now - last_send >= SEND_INTERVAL:
                last_send = now
                packet = build_packet(left_speed, right_speed, pneu1, pneu2)
                try:
                    ser.write(packet)
                except serial.SerialException as e:
                    print(f"\n[ERROR] Serial write failed: {e}")
                    break

                # Throttled display — print every Nth packet to avoid
                # blocking terminal I/O stalling the control loop
                print_count += 1
                if print_count >= PRINT_EVERY_N:
                    print_count = 0
                    mode = get_mode_label(
                        dpad_x * DPAD_TURN_RPM if dpad_active else map_axis(js.get_axis(AXIS_LX)),
                        dpad_y * DPAD_FWD_RPM if dpad_active else map_axis(-js.get_axis(AXIS_LY))
                    )
                    pneu_str = f"P1:{'ON' if pneu1 else '--'} P2:{'ON' if pneu2 else '--'}"
                    print(
                        f"\r  [{source:4s}] L:{left_speed:+4d}rpm R:{right_speed:+4d}rpm"
                        f"  {mode:<11s}  {pneu_str}   ",
                        end="", flush=True
                    )

            # Sleep to yield CPU — prevents Pi 4 overheating
            # 2 ms gives ~500 Hz poll rate (5× the send rate), drops CPU ~100% → ~30%
            time.sleep(0.002)

    except KeyboardInterrupt:
        print("\n\n[INFO] Quit by user.")
    finally:
        # Send stop command before exiting
        try:
            ser.write(build_packet(0, 0, 0, 0))
            time.sleep(0.05)
            ser.write(build_packet(0, 0, 0, 0))  # Send twice for safety
        except Exception:
            pass
        ser.close()
        pygame.quit()
        print("[INFO] Motors stopped, pneumatics closed. Goodbye!")


if __name__ == "__main__":
    main()