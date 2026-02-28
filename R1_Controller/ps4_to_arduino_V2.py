"""
PS4 → Arduino Mega  |  Mecanum Wheel Car + Pneumatics
=====================================================
Sends raw joystick axes + button states to Arduino at 50 Hz.

Left  Stick : Forward / Backward / Strafe L-R / All diagonals
Right Stick : Rotate CW / CCW
L1 / R1     : Pneumatic actuators (active while held)

Packet format:
  <LX,LY,RX,L1,R1>\n
  LX : left  stick X   -255 … +255   (+ve = right)
  LY : left  stick Y   -255 … +255   (+ve = forward, already flipped)
  RX : right stick X   -255 … +255   (+ve = clockwise)
  L1 : left  bumper    0 or 1
  R1 : right bumper    0 or 1

Requirements:  pip install pygame pyserial
"""

import pygame
import serial
import serial.tools.list_ports
import time
import sys

# ─── CONFIG ────────────────────────────────────────────────
BAUD_RATE     = 115200
SEND_INTERVAL = 0.02      # 50 Hz — matches Arduino 20 ms loop

# Pygame axis indices for PS4 controller
AXIS_LX = 0   # Left  stick horizontal
AXIS_LY = 1   # Left  stick vertical
AXIS_RX = 2   # Right stick horizontal

# Pygame button indices for PS4 controller (Bluetooth / DS4Windows)
BTN_L1  = 9   # Left  bumper (L1)
BTN_R1  = 10  # Right bumper (R1)
# ────────────────────────────────────────────────────────────

def list_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

def choose_port():
    ports = list_ports()
    if not ports:
        print("[ERROR] No serial port found. Is the Arduino plugged in?")
        sys.exit(1)
    if len(ports) == 1:
        print(f"[INFO]  Auto-selected: {ports[0]}")
        return ports[0]
    print("\nAvailable serial ports:")
    for i, p in enumerate(ports):
        print(f"  [{i}] {p}")
    return ports[int(input("Select port number: "))]

def scale_axis(raw):
    """Map pygame float (-1.0 … +1.0) → integer (-255 … +255)."""
    return int(raw * 255)

def build_packet(lx, ly, rx, l1=0, r1=0):
    """Build <LX,LY,RX,L1,R1>\n packet."""
    return f"<{lx},{ly},{rx},{l1},{r1}>\n".encode("ascii")

def main():
    print("=" * 50)
    print("  PS4 → Arduino Mega  |  Mecanum Car")
    print("=" * 50)

    # ── Serial ───────────────────────────────────────────────
    port = choose_port()
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        time.sleep(2)           # wait for Arduino to reset
        print(f"[OK]   Serial on {port} @ {BAUD_RATE} baud")
    except serial.SerialException as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # ── Pygame ───────────────────────────────────────────────
    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("[ERROR] No controller detected.")
        print("        Connect PS4 via USB or Bluetooth first.")
        ser.close()
        sys.exit(1)

    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"[OK]   Controller : {js.get_name()}")
    print()
    print("  Left  Stick  →  Forward / Backward / Strafe / Diagonal")
    print("  Right Stick  →  Rotate CW / CCW")
    print("  L1 / R1      →  Pneumatic Actuators (hold to activate)")
    print("  Ctrl+C       →  Quit")
    print()

    # ── Main loop ────────────────────────────────────────────
    last_send = 0

    try:
        while True:
            pygame.event.pump()

            # Read raw axes (-1.0 … +1.0)
            lx_raw = js.get_axis(AXIS_LX)
            ly_raw = js.get_axis(AXIS_LY)
            rx_raw = js.get_axis(AXIS_RX)

            # Read bumper buttons (0 or 1)
            l1 = js.get_button(BTN_L1)
            r1 = js.get_button(BTN_R1)

            # Scale to integers (-255 … +255)
            # Flip LY so pushing stick forward gives +ve value
            lx = scale_axis( lx_raw)
            ly = scale_axis(-ly_raw)
            rx = scale_axis( rx_raw)

            # Send at 50 Hz
            now = time.time()
            if now - last_send >= SEND_INTERVAL:
                last_send = now
                packet = build_packet(lx, ly, rx, l1, r1)
                try:
                    ser.write(packet)
                except serial.SerialException as e:
                    print(f"\n[ERROR] Serial write failed: {e}")
                    break

                # Live display
                l1_tag = "ON " if l1 else "off"
                r1_tag = "ON " if r1 else "off"
                print(
                    f"\r  LX:{lx:+4d}  LY:{ly:+4d}  RX:{rx:+4d}"
                    f"  L1:{l1_tag}  R1:{r1_tag}   ",
                    end="", flush=True
                )

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\n[INFO] Quit by user.")
    finally:
        try:
            ser.write(build_packet(0, 0, 0))
        except Exception:
            pass
        ser.close()
        pygame.quit()
        print("[INFO] Motors stopped. Goodbye!")

if __name__ == "__main__":
    main()
