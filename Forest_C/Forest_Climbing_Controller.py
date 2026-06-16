#!/usr/bin/env python3
# ============================================================
#  R2 - Forest Climbing Controller (PYGAME)
#  Date: June 2026
#
#  Based on 15_june_v1.py (R2 Full Manual Controller)
#  Additions:
#    - Key H = Start homing/calibration sequence
#    - UI shows homing state, limit switch status, stepper positions
#    - All original controls preserved
#
#  PACKET: "LF,RF,LB,RB,LIFT,S1,S2,ARM,DCV_KFS,DCV_SH\n"
#
#  DRIVE:
#    W/S        -> Forward / Backward
#    A/D        -> Strafe Left / Right
#    Q/E        -> Rotate CCW / CW
#
#  LIFT:
#    UP/DOWN    -> Both lifts UP / DOWN
#    I/K        -> Back lift UP / DOWN
#    O/L        -> Front lift UP / DOWN
#    H          -> Start Homing/Calibration
#
#  SERVO1 (Spearhead gripper arm):
#    SPACE      -> Toggle 180 <-> 95 deg (ramped)
#
#  SERVO2 (KFS gripper arm, 270 deg):
#    Z          -> Home   (180 deg)
#    X          -> Forward(90  deg)
#    C          -> Back   (260 deg)
#
#  ARM STEPPER:
#    F          -> Extend  (hold)
#    G          -> Retract (hold)
#
#  DCVs (toggle on keydown):
#    V          -> Toggle KFS gripper pneumatic   (pin 46)
#    B          -> Toggle Spearhead gripper pneumatic (pin 44)
#
#  ESC -> Quit
# ============================================================

import serial
import threading
import time
import sys
import pygame

# ============================================================
#  CONFIG
# ============================================================
SERIAL_PORT      = 'COM8'
SERIAL_BAUD      = 115200
SERIAL_TIMEOUT   = 1.0
SEND_INTERVAL_MS = 20
DRIVE_SPEED      = 30

# Servo positions
SERVO1_POS_A     = 180
SERVO1_POS_B     = 95
SERVO2_HOME      = 180
SERVO2_FWD       = 90
SERVO2_BACK      = 260

WINDOW_W = 720
WINDOW_H = 640

BG_COLOR     = (20, 20, 30)
TEXT_COLOR   = (230, 230, 230)
ACTIVE_COLOR = (80, 220, 120)
STOP_COLOR   = (220, 70, 70)
IDLE_COLOR   = (90, 90, 100)
SERVO_COLOR  = (120, 180, 255)
DCV_COLOR    = (255, 160, 60)
ARM_COLOR    = (180, 255, 180)
HOMING_COLOR = (255, 220, 80)    # Yellow for homing status
LIMIT_OK     = (80, 220, 120)    # Green = switch OK (closed)
LIMIT_TRG    = (220, 70, 70)     # Red   = switch triggered (opened)

# ============================================================
#  GLOBAL STATE
# ============================================================
ser            = None
running        = True
last_feedback  = ""
feedback_lock  = threading.Lock()
packet_lock    = threading.Lock()

# Full packet state
pkt_drive      = (0, 0, 0, 0)
pkt_lift       = 'S'
pkt_s1         = SERVO1_POS_A
pkt_s2         = SERVO2_HOME
pkt_arm        = 0
pkt_dcv_kfs    = 0
pkt_dcv_sh     = 0

# Toggle states
servo1_at_a    = True

# DCV toggle states
send_lock      = threading.Lock()
dcv_kfs_state  = False
dcv_sh_state   = False

# Homing state (parsed from Arduino feedback)
homing_state   = "IDLE"
ls1_state      = "?"
ls2_state      = "?"
lift1_pos      = 0
lift2_pos      = 0

# ============================================================
#  SERIAL READER
# ============================================================
def serial_reader():
    global running, last_feedback
    global homing_state, ls1_state, ls2_state, lift1_pos, lift2_pos
    while running:
        try:
            if ser and ser.in_waiting:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    with feedback_lock:
                        last_feedback = line
                    # Parse homing-related fields from feedback
                    parse_feedback(line)
        except Exception as e:
            if running:
                print(f"[ERROR] Read: {e}")
        time.sleep(0.01)

def parse_feedback(line):
    """Parse Arduino feedback to extract homing state and limit switch info."""
    global homing_state, ls1_state, ls2_state, lift1_pos, lift2_pos
    try:
        parts = line.split()
        for part in parts:
            if part.startswith("HOM:"):
                homing_state = part[4:]
            elif part.startswith("LS1:"):
                ls1_state = part[4:]
            elif part.startswith("LS2:"):
                ls2_state = part[4:]
            elif part.startswith("P1:"):
                lift1_pos = int(part[3:])
            elif part.startswith("P2:"):
                lift2_pos = int(part[3:])
    except:
        pass  # Ignore malformed feedback

# ============================================================
#  COMMAND SENDER
# ============================================================
def command_sender():
    global running
    last_packet = ""
    last_send_time = 0
    HEARTBEAT_MS = 200

    while running:
        with packet_lock:
            lf, rf, lb, rb = pkt_drive
            lift   = pkt_lift
            s1     = pkt_s1
            s2     = pkt_s2
            arm    = pkt_arm
            dkfs   = 1 if dcv_kfs_state else 0
            dsh    = 1 if dcv_sh_state  else 0

        packet = f"{lf},{rf},{lb},{rb},{lift},{s1},{s2},{arm},{dkfs},{dsh}\n"

        now_ms = time.time() * 1000.0
        changed = (packet != last_packet)
        heartbeat_due = (now_ms - last_send_time) >= HEARTBEAT_MS

        if changed or heartbeat_due:
            try:
                if ser and ser.is_open:
                    ser.write(packet.encode())
                    last_packet = packet
                    last_send_time = now_ms
            except Exception as e:
                if running:
                    print(f"[ERROR] Write: {e}")

        time.sleep(SEND_INTERVAL_MS / 1000.0)

# ============================================================
#  MECANUM MIXING
# ============================================================
def decide_drive(keys):
    y = (1 if keys[pygame.K_w] else 0) - (1 if keys[pygame.K_s] else 0)
    x = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
    r = (1 if keys[pygame.K_e] else 0) - (1 if keys[pygame.K_q] else 0)
    lf = y + x + r
    rf = y - x - r
    lb = y - x + r
    rb = y + x - r
    m  = max(abs(lf), abs(rf), abs(lb), abs(rb), 1)
    sc = DRIVE_SPEED / m
    return (int(lf*sc), int(rf*sc), int(lb*sc), int(rb*sc))

# ============================================================
#  LIFT (with homing key H)
# ============================================================
def decide_lift(keys, homing_requested):
    """Returns the lift command character."""
    if homing_requested:
        return 'C'  # Calibrate command

    if keys[pygame.K_UP] and keys[pygame.K_DOWN]: return 'S'
    if keys[pygame.K_UP]:   return 'N'
    if keys[pygame.K_DOWN]: return 'M'
    if keys[pygame.K_i] and keys[pygame.K_k]: return 'S'
    if keys[pygame.K_o] and keys[pygame.K_l]: return 'S'
    if keys[pygame.K_i]: return 'H'
    if keys[pygame.K_k]: return 'J'
    if keys[pygame.K_o]: return 'K'
    if keys[pygame.K_l]: return 'L'
    return 'S'

# ============================================================
#  DRAW UI
# ============================================================
def draw_ui(screen, font, big_font, state, fb):
    screen.fill(BG_COLOR)
    screen.blit(big_font.render("R2 Forest Climbing Controller", True, TEXT_COLOR), (20, 12))

    lf,rf,lb,rb = state['drive']
    lift   = state['lift']
    s1     = state['s1']
    s2     = state['s2']
    arm    = state['arm']
    dkfs   = state['dcv_kfs']
    dsh    = state['dcv_sh']

    y_pos = 52

    # === HOMING STATUS (prominent at top) ===
    hom_label = {
        'IDLE':   'NOT CALIBRATED',
        'H_UP':   'HOMING: Moving UP (1.5 rev)',
        'H_DN':   'HOMING: Moving DOWN (finding switches)',
        'H_ZRO':  'HOMING: Setting Zero',
        'H_SAFE': 'HOMING: Moving to Safe Height',
        'READY':  'CALIBRATED & READY',
    }
    hom_text = hom_label.get(homing_state, f'HOMING: {homing_state}')
    hom_col = ACTIVE_COLOR if homing_state == 'READY' else (HOMING_COLOR if homing_state != 'IDLE' else STOP_COLOR)
    screen.blit(big_font.render(f"STATUS: {hom_text}", True, hom_col), (20, y_pos))
    y_pos += 30

    # Limit Switches
    ls1_col = LIMIT_OK if ls1_state == 'OK' else LIMIT_TRG
    ls2_col = LIMIT_OK if ls2_state == 'OK' else LIMIT_TRG
    ls1_txt = "CLOSED" if ls1_state == 'OK' else "TRIGGERED"
    ls2_txt = "CLOSED" if ls2_state == 'OK' else "TRIGGERED"
    screen.blit(font.render(f"LIMIT SW1(Back): {ls1_txt}", True, ls1_col), (20, y_pos))
    screen.blit(font.render(f"LIMIT SW2(Front): {ls2_txt}", True, ls2_col), (360, y_pos))
    y_pos += 24

    # Stepper positions
    screen.blit(font.render(f"Lift1 Pos: {lift1_pos} pulses ({lift1_pos/800:.2f} rev)", True, TEXT_COLOR), (20, y_pos))
    screen.blit(font.render(f"Lift2 Pos: {lift2_pos} pulses ({lift2_pos/800:.2f} rev)", True, TEXT_COLOR), (360, y_pos))
    y_pos += 28

    # Divider
    pygame.draw.line(screen, HOMING_COLOR, (20, y_pos), (700, y_pos), 2)
    y_pos += 8

    # Drive
    dc = ACTIVE_COLOR if any((lf,rf,lb,rb)) else STOP_COLOR
    screen.blit(big_font.render(f"DRIVE LF:{lf:4d} RF:{rf:4d} LB:{lb:4d} RB:{rb:4d}", True, dc), (20, y_pos))
    y_pos += 32

    # Lift
    lift_names = {'N':'BOTH UP','M':'BOTH DOWN','H':'BACK UP','J':'BACK DN',
                  'K':'FRONT UP','L':'FRONT DN','S':'STOP','C':'CALIBRATING'}
    lc = HOMING_COLOR if lift=='C' else (STOP_COLOR if lift=='S' else ACTIVE_COLOR)
    screen.blit(big_font.render(f"LIFT: {lift_names.get(lift,lift)}", True, lc), (20, y_pos))
    y_pos += 32

    # Servos
    screen.blit(big_font.render(f"SERVO1(SH arm): {s1:3d}°   SERVO2(KFS arm): {s2:3d}°", True, SERVO_COLOR), (20, y_pos))
    y_pos += 32

    # Arm stepper
    arm_txt = "EXTEND" if arm==1 else ("RETRACT" if arm==2 else "STOP")
    arm_col = ARM_COLOR if arm != 0 else IDLE_COLOR
    screen.blit(big_font.render(f"ARM STEPPER: {arm_txt}", True, arm_col), (20, y_pos))
    y_pos += 32

    # DCVs
    kfs_txt = "CLOSED" if dkfs else "OPEN"
    sh_txt  = "CLOSED" if dsh  else "OPEN"
    screen.blit(big_font.render(f"KFS GRIPPER: {kfs_txt}    SH GRIPPER: {sh_txt}", True, DCV_COLOR), (20, y_pos))
    y_pos += 32

    # Divider
    pygame.draw.line(screen, IDLE_COLOR, (20, y_pos), (700, y_pos), 1)
    y_pos += 8

    # Key map
    rows = [
        ("DRIVE",    "W/S=Fwd/Bk  A/D=Strafe  Q/E=Rotate"),
        ("LIFT",     "↑/↓=Both    I/K=Back    O/L=Front"),
        ("HOME",     "H = Start Homing/Calibration"),
        ("SERVO1",   "SPACE = Toggle 180°↔95° (spearhead arm)"),
        ("SERVO2",   "Z=Home(180)  X=Fwd(90)  C=Back(260)"),
        ("ARM STEP", "F=Extend(hold)   G=Retract(hold)"),
        ("DCVs",     "V=Toggle KFS gripper   B=Toggle SH gripper"),
        ("",         "ESC = Quit"),
    ]
    for label, desc in rows:
        if label:
            screen.blit(font.render(f"{label:<10}", True, IDLE_COLOR), (20, y_pos))
            screen.blit(font.render(desc, True, TEXT_COLOR), (130, y_pos))
        else:
            screen.blit(font.render(desc, True, TEXT_COLOR), (20, y_pos))
        y_pos += 24

    # Feedback
    y_pos += 4
    pygame.draw.line(screen, IDLE_COLOR, (20, y_pos), (700, y_pos), 1)
    y_pos += 8
    screen.blit(font.render("Arduino: " + fb[:80], True, ACTIVE_COLOR), (20, y_pos))

    pygame.display.flip()

# ============================================================
#  MAIN
# ============================================================
def main():
    global ser, running
    global pkt_drive, pkt_lift, pkt_s1, pkt_s2, pkt_arm
    global servo1_at_a, dcv_kfs_state, dcv_sh_state

    print("=" * 55)
    print("  R2 Forest Climbing Controller")
    print("=" * 55)

    try:
        ser = serial.Serial(port=SERIAL_PORT, baudrate=SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
        time.sleep(2.0)
        print(f"[INFO] Connected to {SERIAL_PORT}")
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    t_reader = threading.Thread(target=serial_reader, daemon=True)
    t_sender = threading.Thread(target=command_sender, daemon=True)
    t_reader.start()
    t_sender.start()

    pygame.init()
    screen   = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("R2 Forest Climbing Controller")
    font     = pygame.font.SysFont("consolas", 19)
    big_font = pygame.font.SysFont("consolas", 23, bold=True)
    clock    = pygame.time.Clock()

    homing_requested = False  # One-shot flag for 'H' key

    try:
        while running:
            homing_requested = False  # Reset each frame

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

                    # Homing key (H) — only send 'C' once on keydown
                    elif event.key == pygame.K_h:
                        homing_requested = True

                    # Servo1 toggle (SPACE)
                    elif event.key == pygame.K_SPACE:
                        servo1_at_a = not servo1_at_a
                        with packet_lock:
                            pkt_s1 = SERVO1_POS_A if servo1_at_a else SERVO1_POS_B

                    # Servo2 positions
                    elif event.key == pygame.K_z:
                        with packet_lock: pkt_s2 = SERVO2_HOME
                    elif event.key == pygame.K_x:
                        with packet_lock: pkt_s2 = SERVO2_FWD
                    elif event.key == pygame.K_c:
                        with packet_lock: pkt_s2 = SERVO2_BACK

                    # DCV toggles
                    elif event.key == pygame.K_v:
                        dcv_kfs_state = not dcv_kfs_state
                    elif event.key == pygame.K_b:
                        dcv_sh_state = not dcv_sh_state

            # Held keys
            keys = pygame.key.get_pressed()

            with packet_lock:
                pkt_drive = decide_drive(keys)
                pkt_lift  = decide_lift(keys, homing_requested)
                # Arm stepper (hold)
                if keys[pygame.K_f] and not keys[pygame.K_g]:
                    pkt_arm = 1
                elif keys[pygame.K_g] and not keys[pygame.K_f]:
                    pkt_arm = 2
                else:
                    pkt_arm = 0

            with feedback_lock:
                fb = last_feedback

            state = {
                'drive':   pkt_drive,
                'lift':    pkt_lift,
                's1':      pkt_s1,
                's2':      pkt_s2,
                'arm':     pkt_arm,
                'dcv_kfs': dcv_kfs_state,
                'dcv_sh':  dcv_sh_state,
            }
            draw_ui(screen, font, big_font, state, fb)
            clock.tick(60)

    finally:
        running = False
        time.sleep(0.3)
        try:
            if ser and ser.is_open:
                ser.write(b'0,0,0,0,S,180,180,0,0,0\n')
                time.sleep(0.1)
                ser.close()
        except:
            pass
        pygame.quit()
        print("[INFO] Exited cleanly.")

if __name__ == '__main__':
    main()
