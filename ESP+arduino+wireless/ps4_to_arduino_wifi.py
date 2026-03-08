"""
PS4 → WiFi → ESP32 → Arduino Mega  |  Mecanum Wheel Car + Pneumatics
=====================================================================
Sends raw joystick axes + button states to ESP32 via WiFi UDP at 50 Hz.
The ESP32 transparently forwards the packets to Arduino Mega over Serial.

Left  Stick : Forward / Backward / Strafe L-R / All diagonals
Right Stick : Rotate CW / CCW
L1 / R1     : Pneumatic actuators (active while held)

Packet format (identical to wired version):
  <LX,LY,RX,L1,R1>\n
  LX : left  stick X   -255 … +255   (+ve = right)
  LY : left  stick Y   -255 … +255   (+ve = forward, already flipped)
  RX : right stick X   -255 … +255   (+ve = clockwise)
  L1 : left  bumper    0 or 1
  R1 : right bumper    0 or 1

Requirements:  pip install pygame
               (No pyserial needed! Uses built-in socket library)
"""

import pygame
import socket
import time
import sys

# ─── CONFIG ────────────────────────────────────────────────
# ⚠️  SET THIS TO YOUR ESP32's IP ADDRESS  ⚠️
# The ESP32 prints its IP to Serial Monitor on boot.
# Example: "192.168.43.105"
ESP32_IP      = "10.46.62.188"    # ← CHANGE THIS to your ESP32's IP
ESP32_PORT    = 4210                # must match ESP32 sketch

SEND_INTERVAL = 0.02      # 50 Hz — matches Arduino 20 ms loop

# Pygame axis indices for PS4 controller
AXIS_LX = 0   # Left  stick horizontal
AXIS_LY = 1   # Left  stick vertical
AXIS_RX = 2   # Right stick horizontal

# Pygame button indices for PS4 controller (Bluetooth / DS4Windows)
BTN_L1  = 9   # Left  bumper (L1)
BTN_R1  = 10  # Right bumper (R1)
# ────────────────────────────────────────────────────────────

def scale_axis(raw):
    """Map pygame float (-1.0 … +1.0) → integer (-255 … +255)."""
    return int(raw * 255)

def build_packet(lx, ly, rx, l1=0, r1=0):
    """Build <LX,LY,RX,L1,R1>\n packet (identical to wired version)."""
    return f"<{lx},{ly},{rx},{l1},{r1}>\n".encode("ascii")

def main():
    print("=" * 55)
    print("  PS4 → WiFi → ESP32 → Arduino Mega  |  Mecanum Car")
    print("=" * 55)

    # ── UDP Socket ──────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Set a short timeout so we don't block if something goes wrong
    sock.settimeout(0.1)
    print(f"[OK]   UDP target: {ESP32_IP}:{ESP32_PORT}")

    # Quick connectivity test — send a dummy packet
    try:
        test_pkt = build_packet(0, 0, 0)
        sock.sendto(test_pkt, (ESP32_IP, ESP32_PORT))
        print("[OK]   Test packet sent (check ESP32 Serial Monitor)")
    except Exception as e:
        print(f"[WARN] Could not send test packet: {e}")
        print("       Make sure ESP32 is powered and connected to WiFi.")

    # ── Pygame ──────────────────────────────────────────────
    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("[ERROR] No controller detected.")
        print("        Connect PS4 via USB or Bluetooth first.")
        sock.close()
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
    print(f"  Sending to ESP32 at {ESP32_IP}:{ESP32_PORT} over WiFi")
    print()

    # ── Main loop ───────────────────────────────────────────
    last_send = 0
    packets_sent = 0
    errors = 0

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
                    sock.sendto(packet, (ESP32_IP, ESP32_PORT))
                    packets_sent += 1
                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"\n[ERROR] UDP send failed: {e}")
                    elif errors == 6:
                        print("\n[ERROR] Suppressing further error messages...")

                # Live display
                l1_tag = "ON " if l1 else "off"
                r1_tag = "ON " if r1 else "off"
                print(
                    f"\r  LX:{lx:+4d}  LY:{ly:+4d}  RX:{rx:+4d}"
                    f"  L1:{l1_tag}  R1:{r1_tag}"
                    f"  pkts:{packets_sent}   ",
                    end="", flush=True
                )

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\n[INFO] Quit by user.")
    finally:
        # Send zero (stop) packet before quitting
        try:
            sock.sendto(build_packet(0, 0, 0), (ESP32_IP, ESP32_PORT))
        except Exception:
            pass
        sock.close()
        pygame.quit()
        print("[INFO] Stop packet sent. Motors will stop. Goodbye!")

if __name__ == "__main__":
    main()
