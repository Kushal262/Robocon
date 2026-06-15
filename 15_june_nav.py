#!/usr/bin/env python3
# ============================================================
#  R2 - Waypoint Navigation GUI
#  Date: June 2026
#
#  LEFT PANEL  : Field map (6m x 7.3m = Zone2 area)
#    Left-click : Add waypoint
#    Right-click: Remove last waypoint
#    Live bot position shown as blue dot
#
#  RIGHT PANEL : Controls + waypoint list
#    GO         : Execute waypoints in sequence
#    STOP       : Abort navigation
#    CLEAR      : Clear waypoint list
#    RESET ENC  : Reset encoder counts to 0
#    Manual keys still work while in IDLE
#
#  Manual keys (same as 15_june_v1.py):
#    W/S/A/D/Q/E  Drive
#    Arrows/I/K/O/L  Lift
#    SPACE/Z/X/C  Servos
#    F/G  Arm stepper
#    V/B  DCVs
# ============================================================

import serial, threading, time, sys, re, math
import pygame

# ============================================================
#  CONFIG
# ============================================================
SERIAL_PORT      = 'COM8'
SERIAL_BAUD      = 115200
SEND_INTERVAL_MS = 20
HEARTBEAT_MS     = 200
DRIVE_SPEED      = 30

PULSES_PER_METER = 2050.0   # calibrated

# Servo / DCV config (same as 15_june_v1)
SERVO1_POS_A = 180
SERVO1_POS_B = 95
SERVO2_HOME  = 180
SERVO2_FWD   = 90
SERVO2_BACK  = 260

# Field dimensions (meters) -- Zone 2 Meihua Forest area
FIELD_W_M = 6.0
FIELD_H_M = 7.3

# Nav speed sent to Arduino
NAV_SPEED = 60
# Window layout
MAP_W    = 500
MAP_H    = 650
PANEL_W  = 300
WIN_W    = MAP_W + PANEL_W
WIN_H    = MAP_H + 50

# Colors
BG          = (20, 20, 30)
MAP_BG      = (30, 35, 45)
GRID_COL    = (45, 50, 60)
BOT_COL     = (80, 180, 255)
WP_COL      = (255, 200, 60)
WP_DONE_COL = (80, 220, 120)
WP_ACT_COL  = (255, 100, 60)
PATH_COL    = (255, 200, 60)
TEXT_COL    = (230, 230, 230)
IDLE_COL    = (90, 90, 100)
ACTIVE_COL  = (80, 220, 120)
STOP_COL    = (220, 70, 70)
BTN_COL     = (50, 60, 80)
BTN_HOV     = (70, 85, 110)
BTN_GO      = (40, 130, 60)
BTN_STOP    = (130, 40, 40)

# ============================================================
#  GLOBAL STATE
# ============================================================
ser           = None
running       = True
feedback_lock  = threading.Lock()
packet_lock    = threading.Lock()
nav_lock       = threading.Lock()
waypoints_lock = threading.Lock()

# Encoder position (pulses, from Arduino)
enc_x = 0
enc_y = 0
nav_active  = False

# Waypoints: list of (x_pulses, y_pulses, x_m, y_m)
waypoints      = []
current_wp_idx = -1   # which waypoint is active (-1 = none)

# Manual packet state (same fields as 15_june_v1)
pkt_drive   = (0,0,0,0)
pkt_lift    = 'S'
pkt_s1      = SERVO1_POS_A
pkt_s2      = SERVO2_HOME
pkt_arm     = 0
dcv_kfs     = False
dcv_sh      = False
servo1_at_a = True

last_feedback = ""

# App state
app_mode = 'MANUAL'   # 'MANUAL' or 'NAV'

# ============================================================
#  COORDINATE HELPERS
# ============================================================
def pulses_to_meters(px, py):
    return px / PULSES_PER_METER, py / PULSES_PER_METER

def meters_to_pulses(mx, my):
    return int(mx * PULSES_PER_METER), int(my * PULSES_PER_METER)

def map_to_screen(mx, my):
    """Field coords (meters) -> screen pixel on map"""
    sx = int(mx / FIELD_W_M * MAP_W)
    sy = MAP_H - int(my / FIELD_H_M * MAP_H)   # Y flipped (0 at bottom)
    return sx, sy

def screen_to_map(sx, sy):
    """Screen pixel on map -> field coords (meters)"""
    mx = sx / MAP_W * FIELD_W_M
    my = (MAP_H - sy) / MAP_H * FIELD_H_M
    return mx, my

# ============================================================
#  SERIAL READER
# ============================================================
FB_RE = re.compile(r'EX:(-?\d+)\s+EY:(-?\d+)\s+MODE:([MN])\s+NV:([01])')

def serial_reader():
    global running, enc_x, enc_y, nav_active, last_feedback
    global current_wp_idx, app_mode
    while running:
        try:
            if ser and ser.in_waiting:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    with feedback_lock:
                        last_feedback = line
                    m = FB_RE.search(line)
                    if m:
                        with nav_lock:
                            enc_x      = int(m.group(1))
                            enc_y      = int(m.group(2))
                            nav_active = m.group(4) == '1'
                    if 'NAV_DONE' in line:
                        with nav_lock:
                            nav_active = False
                            # Advance to next waypoint
                            if current_wp_idx >= 0:
                                current_wp_idx += 1
                                with waypoints_lock:
                                    at_end = current_wp_idx >= len(waypoints)
                                if not at_end:
                                    _send_next_waypoint()
                                else:
                                    current_wp_idx = -1
                                    app_mode = 'MANUAL'
        except Exception as e:
            if running: print(f"[ERROR] Read: {e}")
        time.sleep(0.01)

def _send_next_waypoint():
    global current_wp_idx
    with waypoints_lock:
        if not (0 <= current_wp_idx < len(waypoints)):
            return
        tx, ty, _, _ = waypoints[current_wp_idx]
    cmd = f"N,{tx},{ty},{NAV_SPEED}\n"
    try:
        if ser and ser.is_open:
            ser.write(cmd.encode())
    except Exception as e:
        print(f"[ERROR] Nav send: {e}")

# ============================================================
#  COMMAND SENDER
# ============================================================
def command_sender():
    global running
    last_pkt  = ""
    last_time = 0.0
    while running:
        # Use app_mode (set instantly on GO click) not nav_active
        # (which depends on feedback roundtrip) to prevent manual packets
        # from canceling nav before the first NV:1 feedback arrives.
        with nav_lock:
            is_nav = (app_mode == 'NAV')

        if not is_nav:
            with packet_lock:
                lf,rf,lb,rb = pkt_drive
                lift = pkt_lift
                s1   = pkt_s1
                s2   = pkt_s2
                arm  = pkt_arm
                dk   = 1 if dcv_kfs else 0
                ds   = 1 if dcv_sh  else 0
            pkt = f"M,{lf},{rf},{lb},{rb},{lift},{s1},{s2},{arm},{dk},{ds}\n"
            now = time.time()*1000
            if pkt != last_pkt or (now-last_time) >= HEARTBEAT_MS:
                try:
                    if ser and ser.is_open:
                        ser.write(pkt.encode())
                        last_pkt  = pkt
                        last_time = now
                except Exception as e:
                    if running: print(f"[ERROR] Write: {e}")
        time.sleep(SEND_INTERVAL_MS/1000.0)

# ============================================================
#  MANUAL INPUT
# ============================================================
def decide_drive(keys):
    y = (1 if keys[pygame.K_w] else 0)-(1 if keys[pygame.K_s] else 0)
    x = (1 if keys[pygame.K_d] else 0)-(1 if keys[pygame.K_a] else 0)
    r = (1 if keys[pygame.K_e] else 0)-(1 if keys[pygame.K_q] else 0)
    lf=y+x+r; rf=y-x-r; lb=y-x+r; rb=y+x-r
    m=max(abs(lf),abs(rf),abs(lb),abs(rb),1)
    sc=DRIVE_SPEED/m
    return(int(lf*sc),int(rf*sc),int(lb*sc),int(rb*sc))

def decide_lift(keys):
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
#  DRAW HELPERS
# ============================================================
def draw_button(screen, font, rect, label, color=BTN_COL, hover=False, text_col=TEXT_COL):
    c = BTN_HOV if hover else color
    pygame.draw.rect(screen, c, rect, border_radius=6)
    pygame.draw.rect(screen, (100,110,130), rect, 1, border_radius=6)
    txt = font.render(label, True, text_col)
    screen.blit(txt, txt.get_rect(center=rect.center))
    return rect

def draw_map(screen, font_sm):
    # Background
    pygame.draw.rect(screen, MAP_BG, (0, 0, MAP_W, MAP_H))

    # Grid (1m spacing)
    for i in range(int(FIELD_W_M)+1):
        sx,_ = map_to_screen(i,0); _,sy0=map_to_screen(0,0); _,sy1=map_to_screen(0,FIELD_H_M)
        pygame.draw.line(screen, GRID_COL, (sx,sy1),(sx,sy0))
        lbl=font_sm.render(f"{i}m",True,IDLE_COL)
        screen.blit(lbl,(sx+2,MAP_H-14))
    for j in range(int(FIELD_H_M)+1):
        _,sy=map_to_screen(0,j); sx0,_=map_to_screen(0,j); sx1,_=map_to_screen(FIELD_W_M,j)
        pygame.draw.line(screen, GRID_COL,(sx0,sy),(sx1,sy))
        lbl=font_sm.render(f"{j}m",True,IDLE_COL)
        screen.blit(lbl,(2,sy-10))

    # Waypoint path lines
    if len(waypoints) > 1:
        pts = [map_to_screen(mx,my) for _,_,mx,my in waypoints]
        pygame.draw.lines(screen, PATH_COL, False, pts, 2)

    # Waypoints
    for i,(tx,ty,mx,my) in enumerate(waypoints):
        sx,sy = map_to_screen(mx,my)
        if i < current_wp_idx:
            col = WP_DONE_COL
        elif i == current_wp_idx:
            col = WP_ACT_COL
        else:
            col = WP_COL
        pygame.draw.circle(screen, col, (sx,sy), 8)
        pygame.draw.circle(screen, TEXT_COL, (sx,sy), 8, 2)
        lbl = font_sm.render(str(i+1), True, BG)
        screen.blit(lbl, lbl.get_rect(center=(sx,sy)))

    # Bot position
    with nav_lock:
        bx,by = enc_x, enc_y
    bxm,bym = pulses_to_meters(bx,by)
    bsx,bsy = map_to_screen(bxm,bym)
    # Clamp to map
    bsx=max(8,min(MAP_W-8,bsx)); bsy=max(8,min(MAP_H-8,bsy))
    pygame.draw.circle(screen, BOT_COL,(bsx,bsy),10)
    pygame.draw.circle(screen, (255,255,255),(bsx,bsy),10,2)
    lbl=font_sm.render("R2",True,BG)
    screen.blit(lbl,lbl.get_rect(center=(bsx,bsy)))

    # Border
    pygame.draw.rect(screen,(80,90,110),(0,0,MAP_W,MAP_H),2)

# ============================================================
#  MAIN
# ============================================================
def main():
    global ser, running, app_mode, current_wp_idx
    global pkt_drive, pkt_lift, pkt_s1, pkt_s2, pkt_arm
    global dcv_kfs, dcv_sh, servo1_at_a, waypoints

    print("="*55)
    print("  R2 Waypoint Navigation GUI")
    print("="*55)
    try:
        ser = serial.Serial(port=SERIAL_PORT, baudrate=SERIAL_BAUD, timeout=1.0)
        time.sleep(2.0)
        print(f"[INFO] Connected to {SERIAL_PORT}")
    except Exception as e:
        print(f"[ERROR] {e}"); sys.exit(1)

    threading.Thread(target=serial_reader, daemon=True).start()
    threading.Thread(target=command_sender, daemon=True).start()

    pygame.init()
    screen   = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("R2 Waypoint Nav")
    font     = pygame.font.SysFont("consolas", 18)
    font_sm  = pygame.font.SysFont("consolas", 14)
    font_big = pygame.font.SysFont("consolas", 22, bold=True)
    clock    = pygame.time.Clock()

    # Button rects (in right panel, offset by MAP_W)
    PX = MAP_W + 10
    btn_go    = pygame.Rect(PX,     10, 135, 42)
    btn_stop  = pygame.Rect(PX+145, 10, 135, 42)
    btn_clear = pygame.Rect(PX,     62, 135, 36)
    btn_reset = pygame.Rect(PX+145, 62, 135, 36)
    btn_addwp = pygame.Rect(PX,    108, 280, 32)

    # Input boxes for manual waypoint entry
    inp_x_str = "0.0"
    inp_y_str = "0.0"
    inp_active = None  # 'x' or 'y'
    inp_x_rect = pygame.Rect(PX+55,  148, 90, 28)
    inp_y_rect = pygame.Rect(PX+190, 148, 90, 28)

    mouse_pos = (0,0)

    try:
        while running:
            mouse_pos = pygame.mouse.get_pos()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx,my = event.pos

                    # Map clicks = add/remove waypoints
                    if mx < MAP_W and my < MAP_H and app_mode == 'MANUAL':
                        fm_x, fm_y = screen_to_map(mx, my)
                        fm_x = max(0.0, min(FIELD_W_M, fm_x))
                        fm_y = max(0.0, min(FIELD_H_M, fm_y))
                        if event.button == 1:
                            tx,ty = meters_to_pulses(fm_x,fm_y)
                            with waypoints_lock:
                                waypoints.append((tx,ty,fm_x,fm_y))
                        elif event.button == 3 and waypoints:
                            with waypoints_lock:
                                waypoints.pop()

                    # Button clicks
                    if btn_go.collidepoint(event.pos) and waypoints and app_mode=='MANUAL':
                        app_mode       = 'NAV'
                        current_wp_idx = 0
                        _send_next_waypoint()

                    elif btn_stop.collidepoint(event.pos):
                        try:
                            if ser and ser.is_open: ser.write(b'A\n')
                        except: pass
                        app_mode       = 'MANUAL'
                        current_wp_idx = -1

                    elif btn_clear.collidepoint(event.pos) and app_mode=='MANUAL':
                        with waypoints_lock:
                            waypoints.clear()
                        current_wp_idx = -1

                    elif btn_reset.collidepoint(event.pos):
                        try:
                            if ser and ser.is_open: ser.write(b'R\n')
                        except: pass

                    elif btn_addwp.collidepoint(event.pos) and app_mode=='MANUAL':
                        try:
                            fm_x=float(inp_x_str); fm_y=float(inp_y_str)
                            fm_x=max(0.0,min(FIELD_W_M,fm_x))
                            fm_y=max(0.0,min(FIELD_H_M,fm_y))
                            tx,ty=meters_to_pulses(fm_x,fm_y)
                            with waypoints_lock:
                                waypoints.append((tx,ty,fm_x,fm_y))
                        except: pass

                    elif inp_x_rect.collidepoint(event.pos): inp_active='x'
                    elif inp_y_rect.collidepoint(event.pos): inp_active='y'
                    else: inp_active=None

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

                    elif inp_active:
                        # Text input for waypoint coords
                        if event.key == pygame.K_BACKSPACE:
                            if inp_active=='x': inp_x_str=inp_x_str[:-1]
                            else:               inp_y_str=inp_y_str[:-1]
                        elif event.key == pygame.K_TAB:
                            inp_active = 'y' if inp_active=='x' else 'x'
                        elif event.unicode in '0123456789.-':
                            if inp_active=='x': inp_x_str+=event.unicode
                            else:               inp_y_str+=event.unicode

                    else:
                        # Manual control keys
                        if event.key == pygame.K_SPACE:
                            servo1_at_a = not servo1_at_a
                            with packet_lock: pkt_s1=SERVO1_POS_A if servo1_at_a else SERVO1_POS_B
                        elif event.key == pygame.K_z:
                            with packet_lock: pkt_s2=SERVO2_HOME
                        elif event.key == pygame.K_x:
                            with packet_lock: pkt_s2=SERVO2_FWD
                        elif event.key == pygame.K_c:
                            with packet_lock: pkt_s2=SERVO2_BACK
                        elif event.key == pygame.K_v:
                            with packet_lock: dcv_kfs = not dcv_kfs
                        elif event.key == pygame.K_b:
                            with packet_lock: dcv_sh = not dcv_sh

            # Held keys (manual drive -- only when not navigating)
            if app_mode == 'MANUAL' and not inp_active:
                keys = pygame.key.get_pressed()
                with packet_lock:
                    pkt_drive = decide_drive(keys)
                    pkt_lift  = decide_lift(keys)
                    pkt_arm   = 1 if (keys[pygame.K_f] and not keys[pygame.K_g]) else \
                                2 if (keys[pygame.K_g] and not keys[pygame.K_f]) else 0
            elif app_mode == 'NAV':
                with packet_lock:
                    pkt_drive=(0,0,0,0); pkt_lift='S'; pkt_arm=0

            # ── DRAW ──
            screen.fill(BG)
            draw_map(screen, font_sm)

            # Right panel background
            pygame.draw.rect(screen,(25,28,38),(MAP_W,0,PANEL_W,WIN_H))
            pygame.draw.line(screen,(70,80,100),(MAP_W,0),(MAP_W,WIN_H),2)

            # Buttons
            is_nav = app_mode=='NAV'
            draw_button(screen,font,btn_go,  "▶  GO",    BTN_GO,  btn_go.collidepoint(mouse_pos) and not is_nav)
            draw_button(screen,font,btn_stop, "■  STOP",  BTN_STOP,btn_stop.collidepoint(mouse_pos))
            draw_button(screen,font_sm,btn_clear,"CLEAR WPs", BTN_COL, btn_clear.collidepoint(mouse_pos))
            draw_button(screen,font_sm,btn_reset,"RESET ENC", BTN_COL, btn_reset.collidepoint(mouse_pos))
            draw_button(screen,font_sm,btn_addwp,"+ ADD WAYPOINT (X,Y)", BTN_COL, btn_addwp.collidepoint(mouse_pos))

            # X/Y input boxes
            screen.blit(font_sm.render("X:",True,TEXT_COL),(PX,152))
            pygame.draw.rect(screen,(40,45,55) if inp_active=='x' else (30,33,43), inp_x_rect, border_radius=4)
            pygame.draw.rect(screen,(120,140,180) if inp_active=='x' else (60,65,80), inp_x_rect,1,border_radius=4)
            screen.blit(font_sm.render(inp_x_str,True,TEXT_COL),(inp_x_rect.x+4,inp_x_rect.y+6))
            screen.blit(font_sm.render("Y:",True,TEXT_COL),(PX+135,152))
            pygame.draw.rect(screen,(40,45,55) if inp_active=='y' else (30,33,43), inp_y_rect, border_radius=4)
            pygame.draw.rect(screen,(120,140,180) if inp_active=='y' else (60,65,80), inp_y_rect,1,border_radius=4)
            screen.blit(font_sm.render(inp_y_str,True,TEXT_COL),(inp_y_rect.x+4,inp_y_rect.y+6))
            screen.blit(font_sm.render("(meters)",True,IDLE_COL),(PX,180))

            # Divider
            pygame.draw.line(screen,(60,65,80),(MAP_W+5,200),(WIN_W-5,200))

            # Position display
            with nav_lock:
                bx,by = enc_x,enc_y
            bxm,bym = pulses_to_meters(bx,by)
            screen.blit(font_big.render("POSITION",True,TEXT_COL),(PX,208))
            screen.blit(font.render(f"X: {bxm:.3f} m  ({bx} p)",True,BOT_COL),(PX,232))
            screen.blit(font.render(f"Y: {bym:.3f} m  ({by} p)",True,BOT_COL),(PX,254))

            # Nav status
            pygame.draw.line(screen,(60,65,80),(MAP_W+5,278),(WIN_W-5,278))
            mode_col = WP_ACT_COL if is_nav else ACTIVE_COL
            screen.blit(font_big.render(f"MODE: {app_mode}",True,mode_col),(PX,284))
            if is_nav and 0<=current_wp_idx<len(waypoints):
                _,_,wmx,wmy = waypoints[current_wp_idx]
                screen.blit(font.render(f"WP {current_wp_idx+1}/{len(waypoints)}:",True,WP_ACT_COL),(PX,308))
                screen.blit(font.render(f"  → ({wmx:.2f}, {wmy:.2f}) m",True,WP_COL),(PX,328))

            # Waypoint list
            pygame.draw.line(screen,(60,65,80),(MAP_W+5,355),(WIN_W-5,355))
            screen.blit(font_big.render(f"WAYPOINTS ({len(waypoints)})",True,TEXT_COL),(PX,360))
            screen.blit(font_sm.render("Left-click map to add",True,IDLE_COL),(PX,382))
            screen.blit(font_sm.render("Right-click map to remove last",True,IDLE_COL),(PX,398))
            y_off = 418
            for i,(_,_,wmx,wmy) in enumerate(waypoints):
                if y_off > WIN_H-30: break
                if i < current_wp_idx: col=WP_DONE_COL
                elif i==current_wp_idx: col=WP_ACT_COL
                else: col=WP_COL
                marker="✓" if i<current_wp_idx else ("▶" if i==current_wp_idx else f"{i+1}.")
                screen.blit(font_sm.render(f"{marker} ({wmx:.2f}, {wmy:.2f}) m",True,col),(PX,y_off))
                y_off+=20

            # Bottom feedback
            pygame.draw.line(screen,(60,65,80),(MAP_W+5,WIN_H-40),(WIN_W-5,WIN_H-40))
            with feedback_lock: fb=last_feedback
            screen.blit(font_sm.render(fb[:38],True,ACTIVE_COL),(PX,WIN_H-32))

            # Status bar bottom of map
            pygame.draw.rect(screen,(25,28,38),(0,MAP_H,MAP_W,50))
            screen.blit(font_sm.render("Left-click: add WP   Right-click: remove last   Manual keys: WASD/arrows",True,IDLE_COL),(8,MAP_H+8))
            screen.blit(font_sm.render("SPACE=S1  Z/X/C=S2  F/G=ARM  V=KFS  B=SH",True,IDLE_COL),(8,MAP_H+26))

            pygame.display.flip()
            clock.tick(60)

    finally:
        running=False
        time.sleep(0.3)
        try:
            if ser and ser.is_open:
                ser.write(b'A\n')
                time.sleep(0.05)
                ser.write(b'M,0,0,0,0,S,180,180,0,0,0\n')
                time.sleep(0.1)
                ser.close()
        except: pass
        pygame.quit()
        print("[INFO] Exited.")

if __name__ == '__main__':
    main()
