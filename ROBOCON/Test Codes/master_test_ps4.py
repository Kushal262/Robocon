"""
PS4 DualShock 4 — MASTER TEST SCRIPT
======================================
Comprehensive diagnostic for every controller input:
  1. All Buttons       2. D-Pad (HAT)
  3. Joysticks         4. Triggers (L2/R2)
  5. Touchpad          6. Rumble / Haptic
  7. Latency Test      8. Full Live Monitor

Requirements:  pip install pygame   (>= 2.0.1 for rumble)
"""

import pygame
import time
import sys
import os

# Force SDL2 to use native HIDAPI for PS4 controllers (enables rumble on Windows without DS4Windows)
os.environ["SDL_JOYSTICK_HIDAPI_PS4"] = "1"
os.environ["SDL_JOYSTICK_HIDAPI_PS4_RUMBLE"] = "1"

# ─── PS4 DualShock 4 Button Map ─────────────────────────────
# Pygame index → human-readable name (DS4 over USB/BT on Windows)
DS4_BUTTONS = {
    0:  "Cross (X)",
    1:  "Circle (O)",
    2:  "Square (□)",
    3:  "Triangle (△)",
    4:  "Share",
    5:  "PS Button",
    6:  "Options",
    7:  "L3 (Left Stick Click)",
    8:  "R3 (Right Stick Click)",
    9:  "L1",
    10: "R1",
    11: "D-Pad Up",
    12: "D-Pad Down",
    13: "D-Pad Left",
    14: "D-Pad Right",
    15: "Touchpad Click",
}

# Axis indices
AXIS_LX = 0   # Left  stick horizontal
AXIS_LY = 1   # Left  stick vertical
AXIS_RX = 2   # Right stick horizontal
AXIS_RY = 3   # Right stick vertical
AXIS_L2 = 4   # L2 trigger
AXIS_R2 = 5   # R2 trigger

DEADZONE = 0.08   # Ignore stick drift below this


# ─── UTILITY ────────────────────────────────────────────────

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def button_name(index):
    return DS4_BUTTONS.get(index, f"Button {index}")

def apply_deadzone(val):
    return val if abs(val) > DEADZONE else 0.0

def scale(val):
    """Map -1.0…+1.0  →  -255…+255 integer."""
    return int(apply_deadzone(val) * 255)

def trigger_scale(val):
    """Map -1.0…+1.0 trigger axis  →  0…255 (trigger rests at -1.0)."""
    return int(((val + 1.0) / 2.0) * 255)

def init_controller():
    """Initialize pygame + return Joystick object or exit."""
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("\n  [ERROR] No controller detected!")
        print("          Connect your PS4 controller via USB or Bluetooth first.\n")
        sys.exit(1)
    js = pygame.joystick.Joystick(0)
    js.init()
    return js

def header(title):
    clear()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)

def pause_msg():
    print("\n  Press Ctrl+C to return to menu.")


# ─── TEST 1 : ALL BUTTONS ──────────────────────────────────

def test_buttons(js):
    header("TEST 1 — ALL BUTTONS")
    num = js.get_numbuttons()
    print(f"\n  Controller : {js.get_name()}")
    print(f"  Buttons    : {num}")
    pause_msg()
    print()

    try:
        while True:
            pygame.event.pump()
            lines = []
            for i in range(num):
                state = js.get_button(i)
                marker = "██ PRESSED" if state else "          "
                lines.append(f"    [{i:2d}] {button_name(i):<28s} {marker}")
            # Overwrite in-place
            sys.stdout.write(f"\033[{num}A")  # move cursor up
            for line in lines:
                print(line)
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass


# ─── TEST 2 : D-PAD (HAT) ──────────────────────────────────

def test_dpad(js):
    header("TEST 2 — D-PAD (HAT SWITCH)")
    num_hats = js.get_numhats()
    print(f"\n  HAT switches detected: {num_hats}")
    if num_hats == 0:
        print("  No HAT switch found. D-Pad may be mapped as buttons (see Test 1).")
        print("  Press Enter to go back.")
        input()
        return
    pause_msg()
    print("\n\n")  # spacing for overwrite

    DIRS = {
        ( 0,  0): "  NEUTRAL  ",
        ( 0,  1): "    UP     ",
        ( 0, -1): "   DOWN    ",
        (-1,  0): "   LEFT    ",
        ( 1,  0): "   RIGHT   ",
        (-1,  1): " UP-LEFT   ",
        ( 1,  1): " UP-RIGHT  ",
        (-1, -1): "DOWN-LEFT  ",
        ( 1, -1): "DOWN-RIGHT ",
    }

    try:
        while True:
            pygame.event.pump()
            hat = js.get_hat(0)
            label = DIRS.get(hat, str(hat))
            sys.stdout.write(f"\r    HAT →  {label}  raw={hat}          ")
            sys.stdout.flush()
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass


# ─── TEST 3 : JOYSTICKS ────────────────────────────────────

def test_joysticks(js):
    header("TEST 3 — JOYSTICKS (Left & Right Sticks)")
    print(f"\n  Axes detected: {js.get_numaxes()}")
    pause_msg()
    print("\n\n\n\n\n\n")  # pre-space for overwrite

    try:
        while True:
            pygame.event.pump()

            lx = js.get_axis(AXIS_LX)
            ly = js.get_axis(AXIS_LY)
            rx = js.get_axis(AXIS_RX)
            ry = js.get_axis(AXIS_RY)

            lx_s, ly_s = scale(lx), scale(-ly)
            rx_s, ry_s = scale(rx), scale(-ry)

            sys.stdout.write("\033[6A")  # move up 6 lines
            print(f"    ┌─ LEFT STICK ──────────────────────────────────┐")
            print(f"    │  X: {lx:+6.3f}  → {lx_s:+4d}    Y: {ly:+6.3f}  → {ly_s:+4d}   │")
            print(f"    └──────────────────────────────────────────────-┘")
            print(f"    ┌─ RIGHT STICK ─────────────────────────────────┐")
            print(f"    │  X: {rx:+6.3f}  → {rx_s:+4d}    Y: {ry:+6.3f}  → {ry_s:+4d}   │")
            print(f"    └───────────────────────────────────────────────┘")
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass


# ─── TEST 4 : TRIGGERS (L2 / R2) ───────────────────────────

def test_triggers(js):
    header("TEST 4 — ANALOG TRIGGERS (L2 / R2)")
    num_axes = js.get_numaxes()
    print(f"\n  Axes detected: {num_axes}")
    if num_axes < 6:
        print("  [WARNING] Less than 6 axes — your triggers may not be analog.")
        print("            They might appear as buttons instead (see Test 1).")
    pause_msg()
    print("\n\n\n")

    try:
        while True:
            pygame.event.pump()

            if num_axes >= 5:
                l2_raw = js.get_axis(AXIS_L2)
                l2_val = trigger_scale(l2_raw)
            else:
                l2_raw, l2_val = 0.0, 0

            if num_axes >= 6:
                r2_raw = js.get_axis(AXIS_R2)
                r2_val = trigger_scale(r2_raw)
            else:
                r2_raw, r2_val = 0.0, 0

            # Visual bar (50 chars max)
            l2_bar = "█" * (l2_val * 40 // 255) + "░" * (40 - l2_val * 40 // 255)
            r2_bar = "█" * (r2_val * 40 // 255) + "░" * (40 - r2_val * 40 // 255)

            sys.stdout.write("\033[3A")
            print(f"    L2: {l2_raw:+6.3f} → {l2_val:3d}/255  [{l2_bar}]")
            print(f"    R2: {r2_raw:+6.3f} → {r2_val:3d}/255  [{r2_bar}]")
            print(f"    (Press triggers fully to see 255)             ")
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass


# ─── TEST 5 : TOUCHPAD ─────────────────────────────────────

def test_touchpad(js):
    header("TEST 5 — TOUCHPAD")
    num_buttons = js.get_numbuttons()
    print(f"\n  Buttons detected: {num_buttons}")
    print("  Touchpad click is typically button 13 or 15 on DS4.")
    print("  All button presses will be shown below — tap the touchpad!")
    pause_msg()
    print("\n\n")

    try:
        while True:
            pygame.event.pump()
            pressed = []
            for i in range(num_buttons):
                if js.get_button(i):
                    pressed.append(f"{i}={button_name(i)}")

            # Also check for FINGERDOWN / FINGERUP touch events
            touch_events = []
            for event in pygame.event.get():
                if event.type == pygame.FINGERDOWN:
                    touch_events.append(f"TOUCH DOWN  x={event.x:.3f} y={event.y:.3f}")
                elif event.type == pygame.FINGERUP:
                    touch_events.append("TOUCH UP")
                elif event.type == pygame.FINGERMOTION:
                    touch_events.append(f"TOUCH MOVE  x={event.x:.3f} y={event.y:.3f}")

            sys.stdout.write("\033[2A")
            if pressed:
                print(f"    Buttons: {', '.join(pressed):<70s}")
            else:
                print(f"    Buttons: (none)                                                        ")
            if touch_events:
                print(f"    Touch:   {touch_events[-1]:<60s}")
            else:
                print(f"    Touch:   Waiting...                                                    ")
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass


# ─── TEST 6 : RUMBLE / HAPTIC ──────────────────────────────

def test_rumble(js):
    header("TEST 6 — RUMBLE / HAPTIC FEEDBACK")
    print(f"""
  Control rumble with your controller buttons:

    [X / Cross]     →  Light tap         (low motor, gentle)
    [O / Circle]    →  Heavy rumble      (low motor, strong)
    [△ / Triangle]  →  Buzzy vibration   (high motor)
    [□ / Square]    →  FULL BLAST both   (both motors max)
    [L1]            →  Pulsing pattern   (3 quick bursts)
    [R1]            →  Intensity by R2   (hold R2 to control strength)

  NOTE: Rumble requires pygame >= 2.0.1.
         If nothing happens, check your pygame version.
    """)
    pause_msg()

    has_rumble = hasattr(js, "rumble")
    if not has_rumble:
        print("\n  [ERROR] js.rumble() not available. Upgrade pygame:")
        print("          pip install pygame --upgrade")
        input("\n  Press Enter to go back.")
        return

    last_pulse = 0
    pulse_count = 0

    try:
        while True:
            pygame.event.pump()
            now = time.time()

            # Cross — light tap
            if js.get_button(0):
                js.rumble(0.25, 0.0, 200)
                time.sleep(0.25)

            # Circle — heavy
            elif js.get_button(1):
                js.rumble(1.0, 0.0, 400)
                time.sleep(0.45)

            # Square — full blast
            elif js.get_button(2):
                js.rumble(1.0, 1.0, 500)
                time.sleep(0.55)

            # Triangle — buzzy
            elif js.get_button(3):
                js.rumble(0.0, 1.0, 300)
                time.sleep(0.35)

            # L1 — pulse pattern (3 quick bursts)
            elif js.get_button(9):
                for _ in range(3):
                    js.rumble(0.8, 0.8, 100)
                    time.sleep(0.15)
                    js.rumble(0.0, 0.0, 50)
                    time.sleep(0.1)
                time.sleep(0.3)

            # R1 — intensity controlled by R2 trigger
            elif js.get_button(10):
                if js.get_numaxes() >= 6:
                    r2_raw = js.get_axis(AXIS_R2)
                    intensity = (r2_raw + 1.0) / 2.0   # 0.0 → 1.0
                else:
                    intensity = 0.5
                js.rumble(intensity, intensity, 100)
                print(f"\r    R1+R2 intensity: {intensity:.2f}              ", end="", flush=True)
                time.sleep(0.12)

            else:
                time.sleep(0.03)

    except KeyboardInterrupt:
        # Stop any ongoing rumble
        try:
            js.rumble(0, 0, 0)
        except Exception:
            pass


# ─── TEST 7 : LATENCY TEST ─────────────────────────────────

def test_latency(js):
    header("TEST 7 — INPUT LATENCY TEST")
    ROUNDS = 5
    print(f"""
  This test measures the time between a prompt and your button press.
  You will be asked to press Cross (X) as fast as possible.
  
  Rounds: {ROUNDS}
    """)
    input("  Press Enter when ready...")

    latencies = []

    for r in range(1, ROUNDS + 1):
        # Random delay before prompting (1–3 seconds)
        import random
        wait = random.uniform(1.5, 3.5)
        print(f"\n  Round {r}/{ROUNDS} — Get ready...")
        time.sleep(wait)

        # Drain any existing presses
        pygame.event.pump()
        _ = js.get_button(0)

        print("  >>> PRESS [X] NOW! <<<")
        t_start = time.perf_counter()

        # Wait for press
        while True:
            pygame.event.pump()
            if js.get_button(0):
                t_end = time.perf_counter()
                latency_ms = (t_end - t_start) * 1000
                latencies.append(latency_ms)
                print(f"  → {latency_ms:.1f} ms")
                # Wait for release
                while js.get_button(0):
                    pygame.event.pump()
                    time.sleep(0.01)
                break
            time.sleep(0.001)

    # Results
    print("\n" + "─" * 40)
    print(f"  Results ({ROUNDS} rounds):")
    print(f"    Min     : {min(latencies):.1f} ms")
    print(f"    Max     : {max(latencies):.1f} ms")
    print(f"    Average : {sum(latencies)/len(latencies):.1f} ms")
    print("─" * 40)

    # Rating
    avg = sum(latencies) / len(latencies)
    if avg < 50:
        print("  Rating: ⚡ EXCELLENT — Nearly instant!")
    elif avg < 100:
        print("  Rating: ✅ GOOD — Very responsive")
    elif avg < 200:
        print("  Rating: 🆗 OKAY — Acceptable for most uses")
    else:
        print("  Rating: ⚠️  SLOW — You may experience lag")

    print("\n  NOTE: This includes YOUR reaction time + controller latency.")
    print("        True controller latency is typically 2-10 ms (USB) or 5-20 ms (BT).")
    input("\n  Press Enter to return to menu...")


# ─── TEST 8 : FULL LIVE MONITOR ────────────────────────────

def test_live_monitor(js):
    header("TEST 8 — FULL LIVE MONITOR")
    num_buttons = js.get_numbuttons()
    num_axes = js.get_numaxes()
    num_hats = js.get_numhats()
    print(f"  Controller : {js.get_name()}")
    print(f"  Buttons: {num_buttons}  |  Axes: {num_axes}  |  HATs: {num_hats}")
    pause_msg()

    # Pre-allocate display lines
    DISPLAY_LINES = 16
    print("\n" * DISPLAY_LINES)

    try:
        while True:
            pygame.event.pump()

            # Gather data
            lx = scale(js.get_axis(AXIS_LX)) if num_axes > 0 else 0
            ly = scale(-js.get_axis(AXIS_LY)) if num_axes > 1 else 0
            rx = scale(js.get_axis(AXIS_RX)) if num_axes > 2 else 0
            ry = scale(-js.get_axis(AXIS_RY)) if num_axes > 3 else 0
            l2 = trigger_scale(js.get_axis(AXIS_L2)) if num_axes > 4 else 0
            r2 = trigger_scale(js.get_axis(AXIS_R2)) if num_axes > 5 else 0

            hat = js.get_hat(0) if num_hats > 0 else (0, 0)

            pressed_btns = []
            for i in range(num_buttons):
                if js.get_button(i):
                    pressed_btns.append(button_name(i))

            # Draw
            sys.stdout.write(f"\033[{DISPLAY_LINES}A")

            print(f"  ┌─────────────────────────────────────────────────────┐")
            print(f"  │  LEFT STICK   X:{lx:+4d}   Y:{ly:+4d}                      │")
            print(f"  │  RIGHT STICK  X:{rx:+4d}   Y:{ry:+4d}                      │")
            print(f"  │                                                     │")
            print(f"  │  L2: {l2:3d}/255   R2: {r2:3d}/255                         │")
            print(f"  │                                                     │")
            print(f"  │  D-PAD: {str(hat):<12s}                                │")
            print(f"  │                                                     │")

            # Show up to 4 lines of pressed buttons
            if pressed_btns:
                btn_str = ", ".join(pressed_btns)
                # Wrap to fit
                chunks = [btn_str[i:i+47] for i in range(0, len(btn_str), 47)]
            else:
                chunks = ["(none)"]

            for idx in range(4):
                if idx < len(chunks):
                    print(f"  │  BTN: {chunks[idx]:<47s}│")
                else:
                    print(f"  │                                                     │")

            print(f"  │                                                     │")
            print(f"  │  Time: {time.strftime('%H:%M:%S'):<20s}                        │")
            print(f"  └─────────────────────────────────────────────────────┘")
            print(f"                                                         ")

            time.sleep(0.03)
    except KeyboardInterrupt:
        pass


# ─── MAIN MENU ──────────────────────────────────────────────

def main():
    js = init_controller()

    print(f"\n  ✅ Controller connected: {js.get_name()}")
    print(f"     Buttons: {js.get_numbuttons()}")
    print(f"     Axes:    {js.get_numaxes()}")
    print(f"     HATs:    {js.get_numhats()}")
    time.sleep(1)

    while True:
        clear()
        print("=" * 60)
        print("   PS4 DualShock 4 — MASTER TEST SUITE")
        print("=" * 60)
        print(f"   Controller: {js.get_name()}")
        print("─" * 60)
        print("""
   [1]  All Buttons          — detect & name every button
   [2]  D-Pad (HAT)          — directional hat switch
   [3]  Joysticks            — left & right stick axes
   [4]  Triggers (L2/R2)     — analog trigger range
   [5]  Touchpad             — tap & motion detection
   [6]  Rumble / Haptic      — vibration patterns via buttons
   [7]  Latency Test         — reaction-time measurement
   [8]  Full Live Monitor    — all inputs in real-time
   [0]  Quit
        """)

        choice = input("   Select test [0-8]: ").strip()

        if   choice == "1":  test_buttons(js)
        elif choice == "2":  test_dpad(js)
        elif choice == "3":  test_joysticks(js)
        elif choice == "4":  test_triggers(js)
        elif choice == "5":  test_touchpad(js)
        elif choice == "6":  test_rumble(js)
        elif choice == "7":  test_latency(js)
        elif choice == "8":  test_live_monitor(js)
        elif choice == "0":
            print("\n   Goodbye! 👋\n")
            break
        else:
            print("   Invalid choice. Try again.")
            time.sleep(1)

    pygame.quit()


if __name__ == "__main__":
    main()
