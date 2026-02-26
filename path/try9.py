import pygame
import sys
import math
import time
import tkinter as tk
from tkinter import messagebox

# ────────── CONFIG ──────────
ARENA_W, ARENA_H = 600, 1210
GRID = 20
COLS = ARENA_W // GRID       # 30
ROWS = ARENA_H // GRID       # 60

LINEAR_SPEED  = 80
ANGULAR_SPEED = 3.0
MAX_KFS       = 4
SCROLL_SPEED  = 30

SIDEBAR_W  = 200
TERMINAL_W = 260
WIN_W = SIDEBAR_W + ARENA_W + TERMINAL_W   # 1060

# Colors (Figma exact)
C_BG             = (12, 14, 20)
C_BORDER         = (0, 0, 0)
C_ZONE1          = (128, 199, 226)
C_START_BLUE     = (50, 0, 255)
C_RACK_BROWN     = (155, 95, 0)
C_PATH_CYAN      = (128, 191, 209)
C_FOREST_DARK    = (42, 113, 56)
C_FOREST_DARKER  = (41, 82, 16)
C_FOREST_LIGHT   = (152, 166, 80)
C_ZONE3          = (129, 210, 214)
C_RAMP_SAND      = (192, 189, 182)
C_TTT_RACK       = (113, 113, 113)
C_WEAPON_YELLOW  = (255, 225, 0)
C_CYAN   = (0, 200, 255)
C_AMBER  = (255, 180, 0)
C_GREEN  = (0, 255, 140)
C_TEAL   = (0, 240, 220)
C_RED    = (255, 60, 60)
C_WHITE  = (230, 240, 255)
C_TERM   = (0, 255, 180)
C_PANEL  = (18, 22, 30)

# ────────── INIT ──────────
pygame.init()
screen = pygame.display.set_mode((WIN_W, 900), pygame.RESIZABLE)
pygame.display.set_caption("Team Panchjanya R2 — Control Unit")

font_sm  = pygame.font.SysFont("consolas", 15)
font_med = pygame.font.SysFont("consolas", 18)
font_lrg = pygame.font.SysFont("consolas", 22, bold=True)
font_ttl = pygame.font.SysFont("consolas", 24, bold=True)
clock = pygame.time.Clock()

root = tk.Tk(); root.withdraw()

# ────────── STATE ──────────
scroll_y      = 0
mode          = 0
start_cell    = None
path_cells    = []
kfs_cells     = []
# robot stored in ARENA coordinates (pixels, not screen)
robot_ax      = 0.0
robot_ay      = 0.0
theta         = -math.pi / 2
target_index  = 0
logs          = []
pause_until   = 0
run_start_time = None
task_done     = False

# ────────── HELPERS ──────────
def get_viewport_h():
    return screen.get_size()[1]

def clamp_scroll():
    global scroll_y
    vh = get_viewport_h()
    scroll_y = max(0, min(scroll_y, ARENA_H - vh))

def arena_x():
    """Left edge of arena on screen."""
    return SIDEBAR_W

def arena_to_screen(ax, ay):
    """Arena pixel coords → screen pixel coords."""
    return SIDEBAR_W + ax, ay - scroll_y

def screen_to_arena(sx, sy):
    """Screen pixel coords → arena pixel coords."""
    return sx - SIDEBAR_W, sy + scroll_y

def cell_from_mouse(pos):
    ax, ay = screen_to_arena(pos[0], pos[1])
    if 0 <= ax < ARENA_W and 0 <= ay < ARENA_H:
        col = min(int(ax // GRID), COLS - 1)
        row = min(int(ay // GRID), ROWS - 1)
        return (row, col)
    return None

def cell_arena_center(cell):
    """Center of cell in arena pixel coords."""
    row, col = cell
    return col * GRID + GRID // 2, row * GRID + GRID // 2

def log(t):
    logs.append(t)
    if len(logs) > 500:
        logs.pop(0)

def reset_all():
    global start_cell, path_cells, kfs_cells, robot_ax, robot_ay
    global theta, target_index, logs, task_done, mode, pause_until, run_start_time, scroll_y
    start_cell = None
    path_cells.clear()
    kfs_cells.clear()
    robot_ax = robot_ay = 0.0
    theta = -math.pi / 2
    target_index = 0
    logs.clear()
    task_done = False
    mode = 0
    pause_until = 0
    run_start_time = None
    scroll_y = 0

# ────────── BUILD ARENA SURFACE ──────────
def build_arena_surface():
    surf = pygame.Surface((ARENA_W, ARENA_H))
    surf.fill((255, 255, 255))

    def dr(color, x, y, w, h):
        pygame.draw.rect(surf, color, (round(x), round(y), round(w), round(h)))
        pygame.draw.rect(surf, C_BORDER, (round(x), round(y), round(w), round(h)), 1)

    # Zone 1
    dr(C_ZONE1,        2.5,   5, 600, 197)
    dr(C_START_BLUE, 502.5,   5, 100, 100)
    dr(C_RACK_BROWN, 302.5,   5,  80,  30)
    dr(C_RACK_BROWN,  -15,   35,  30, 120)
    dr(C_START_BLUE, 102.5,   5,  80,  80)
    # Pathways
    dr(C_PATH_CYAN,    2.5, 205, 120, 745)
    dr(C_PATH_CYAN,  482.5, 205, 120, 597)
    dr(C_PATH_CYAN,  125.5, 205, 354, 120)
    dr(C_PATH_CYAN,  125.5, 805, 477, 145)
    # Forest
    for fx, fy, col in [
        (122.5,325,C_FOREST_DARK),(242.5,325,C_FOREST_DARKER),(362.5,325,C_FOREST_DARK),
        (122.5,445,C_FOREST_LIGHT),(242.5,445,C_FOREST_DARK),(362.5,445,C_FOREST_DARKER),
        (122.5,565,C_FOREST_DARK),(242.5,565,C_FOREST_LIGHT),(362.5,565,C_FOREST_DARK),
        (122.5,685,C_FOREST_DARKER),(242.5,685,C_FOREST_DARK),(362.5,685,C_FOREST_DARKER),
    ]:
        dr(col, fx, fy, 120, 120)
    # Zone 3
    dr(C_ZONE3,          2.5,  955, 600, 250)
    dr(C_RAMP_SAND,    452.5,  935, 150, 150)
    dr(C_TTT_RACK,       -15,  999,  30, 162)
    dr(C_START_BLUE,     503, 1105, 100, 100)
    dr(C_WEAPON_YELLOW, 101.5, 955, 150,  30)
    # Arena border
    pygame.draw.rect(surf, (129, 129, 129), surf.get_rect(), 1)

    # Grid
    for c in range(COLS + 1):
        pygame.draw.line(surf, (0, 90, 110), (c * GRID, 0), (c * GRID, ARENA_H))
    for r in range(ROWS + 1):
        pygame.draw.line(surf, (0, 90, 110), (0, r * GRID), (ARENA_W, r * GRID))

    return surf

# ────────── DRAW OVERLAYS ON ARENA SURFACE ──────────
def draw_overlays(surf):
    # Path
    for i, cell in enumerate(path_cells):
        row, col = cell
        t = i / max(len(path_cells) - 1, 1)
        s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
        s.fill((255, int(210 - 80*t), 0, 170))
        surf.blit(s, (col * GRID, row * GRID))
        num = font_sm.render(str(i+1), True, (0,0,0))
        surf.blit(num, (col*GRID + GRID//2 - num.get_width()//2,
                        row*GRID + GRID//2 - num.get_height()//2))
    # Path line
    if len(path_cells) > 1:
        pts = [(col*GRID+GRID//2, row*GRID+GRID//2) for row,col in path_cells]
        pygame.draw.lines(surf, (255,140,0), False, pts, 2)
    # KFS
    for cell in kfs_cells:
        row, col = cell
        s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
        s.fill((0, 255, 220, 190))
        surf.blit(s, (col*GRID, row*GRID))
        k = font_sm.render("K", True, (0,60,60))
        surf.blit(k, (col*GRID+GRID//2 - k.get_width()//2,
                      row*GRID+GRID//2 - k.get_height()//2))
    # Robot
    if start_cell:
        ax, ay = robot_ax, robot_ay
        size = 12
        pts = [
            (ax + size*math.cos(theta),     ay + size*math.sin(theta)),
            (ax + size*math.cos(theta+2.5), ay + size*math.sin(theta+2.5)),
            (ax + size*math.cos(theta-2.5), ay + size*math.sin(theta-2.5)),
        ]
        pygame.draw.polygon(surf, (240,240,255), pts)
        pygame.draw.polygon(surf, (0,200,255), pts, 2)
        pygame.draw.circle(surf, (0,180,255), (int(ax), int(ay)), 4)
        pygame.draw.line(surf, (255,255,100), (int(ax),int(ay)),
                         (int(ax+size*math.cos(theta)), int(ay+size*math.sin(theta))), 2)
    # Hover
    hover = cell_from_mouse(pygame.mouse.get_pos())
    if hover and mode in (1, 2, 4):
        row, col = hover
        s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
        s.fill((255, 255, 255, 80))
        surf.blit(s, (col*GRID, row*GRID))

# ────────── SIDEBAR ──────────
BTNS = [
    (pygame.Rect(20, 120, 160, 42), "Set Start",  1, C_CYAN),
    (pygame.Rect(20, 172, 160, 42), "Path Mode",  2, C_AMBER),
    (pygame.Rect(20, 224, 160, 42), "Place KFS",  4, C_TEAL),
    (pygame.Rect(20, 276, 160, 42), "▶  RUN",     3, C_GREEN),
    (pygame.Rect(20, 342, 160, 42), "RESET",     -1, C_RED),
]

def draw_sidebar():
    h = get_viewport_h()
    pygame.draw.rect(screen, C_PANEL, (0, 0, SIDEBAR_W, h))
    pygame.draw.rect(screen, (30,40,55), (0, 0, SIDEBAR_W, h), 1)

    t1 = font_ttl.render("PANCHJANYA", True, C_TERM)
    t2 = font_sm.render("R2 Control Unit", True, (120,200,180))
    screen.blit(t1, (SIDEBAR_W//2 - t1.get_width()//2, 14))
    screen.blit(t2, (SIDEBAR_W//2 - t2.get_width()//2, 46))
    pygame.draw.line(screen, (30,80,60), (10,68), (SIDEBAR_W-10,68), 1)

    mode_names = {0:"IDLE",1:"SET START",2:"PATH MODE",3:"RUNNING",4:"KFS MODE"}
    mc = C_GREEN if mode==3 else C_AMBER if mode in (1,2,4) else (100,120,130)
    ml = font_sm.render(f"MODE: {mode_names.get(mode,'IDLE')}", True, mc)
    screen.blit(ml, (SIDEBAR_W//2 - ml.get_width()//2, 78))

    for rect, label, m, color in BTNS:
        active = (mode == m)
        gs = pygame.Surface((rect.w+20, rect.h+20), pygame.SRCALPHA)
        pygame.draw.rect(gs, (*color, 100 if active else 20), gs.get_rect(), border_radius=14)
        screen.blit(gs, (rect.x-10, rect.y-10))
        pygame.draw.rect(screen, color if active else (35,42,55), rect, border_radius=10)
        pygame.draw.rect(screen, (*color, 180 if active else 50), rect, 2, border_radius=10)
        txt = font_med.render(label, True, C_WHITE)
        screen.blit(txt, (rect.x+rect.w//2-txt.get_width()//2,
                          rect.y+rect.h//2-txt.get_height()//2))

    sy = 400
    pygame.draw.line(screen, (30,60,50), (10,sy-10), (SIDEBAR_W-10,sy-10), 1)
    def stat(lbl, val, col=(180,200,210)):
        nonlocal sy
        screen.blit(font_sm.render(lbl, True, (90,110,130)), (20, sy))
        screen.blit(font_sm.render(str(val), True, col), (30, sy+16))
        sy += 36
    stat("Waypoints:", len(path_cells), C_AMBER)
    stat("KFS placed:", f"{len(kfs_cells)}/{MAX_KFS}", C_TEAL)
    if start_cell:
        stat("Start:", f"R{start_cell[0]} C{start_cell[1]}", C_CYAN)
    if mode == 3 and run_start_time:
        stat("Time:", f"{time.time()-run_start_time:.1f}s", C_GREEN)
        stat("WP:", f"{target_index}/{len(path_cells)}", C_GREEN)

    # Scroll info at bottom
    bottom = h - 110
    pygame.draw.line(screen, (30,60,50), (10, bottom), (SIDEBAR_W-10, bottom), 1)
    screen.blit(font_sm.render("── SCROLL ──", True, (50,90,80)), (20, bottom+8))
    for i, hint in enumerate(["Mousewheel ↕", "↑ ↓  Arrow keys", "PgUp / PgDn", "Home=Top End=Bot"]):
        screen.blit(font_sm.render(hint, True, (70,100,90)), (20, bottom+26+i*17))

    # Mini map / position bar
    bar = pygame.Rect(20, h-12, SIDEBAR_W-40, 8)
    pygame.draw.rect(screen, (25,40,35), bar, border_radius=4)
    vh = get_viewport_h()
    if ARENA_H > vh:
        fw = max(10, int(bar.w * vh / ARENA_H))
        fx = bar.x + int((bar.w - fw) * scroll_y / max(1, ARENA_H - vh))
        pygame.draw.rect(screen, C_TERM, (fx, bar.y, fw, 8), border_radius=4)

def draw_terminal():
    w, h = screen.get_size()
    tx = SIDEBAR_W + ARENA_W
    tw = w - tx
    if tw <= 0: return
    pygame.draw.rect(screen, C_PANEL, (tx, 0, tw, h))
    pygame.draw.rect(screen, (25,40,35), (tx, 0, tw, h), 1)
    screen.blit(font_lrg.render("TERMINAL", True, C_TERM), (tx+14, 14))
    pygame.draw.line(screen, (0,120,80), (tx+8,42), (tx+tw-8,42), 1)
    max_lines = (h - 60) // 19
    y = 52
    for entry in logs[-max_lines:]:
        col = (100,255,150) if entry.endswith("] W") else \
              (255,200,80)  if entry.endswith("] A") or entry.endswith("] D") else \
              (0,255,220)   if "KFS" in entry else \
              (255,100,100) if "✓" in entry else C_TERM
        char_limit = max(1, (tw-20) // 9)
        txt = font_sm.render(entry[:char_limit], True, col)
        screen.blit(txt, (tx+10, y))
        y += 19

def draw_scrollbar():
    vh = get_viewport_h()
    if ARENA_H <= vh: return
    bx = SIDEBAR_W + ARENA_W - 8
    pygame.draw.rect(screen, (25,35,45), (bx, 0, 8, vh))
    th = max(24, int(vh * vh / ARENA_H))
    ty = int((scroll_y / (ARENA_H - vh)) * (vh - th))
    pygame.draw.rect(screen, (0,180,120), (bx, ty, 8, th), border_radius=4)

# ────────── MOTION ──────────
def move_robot(dt):
    global robot_ax, robot_ay, theta, target_index, pause_until, task_done, mode, scroll_y

    if task_done: return
    now = time.time()
    if now < pause_until: return

    if target_index >= len(path_cells):
        log("✓ Task Completed!")
        task_done = True
        mode = 0
        messagebox.showinfo("Task Completed",
            f"All waypoints reached!\nTime: {now - run_start_time:.2f}s")
        return

    target_cell = path_cells[target_index]
    if target_cell in kfs_cells:
        log(f"★ KFS R{target_cell[0]}C{target_cell[1]}")
        pause_until = now + 5
        kfs_cells.remove(target_cell)
        return

    # Everything in ARENA coords now
    tx, ty = cell_arena_center(target_cell)
    dx = tx - robot_ax
    dy = ty - robot_ay
    target_angle = math.atan2(dy, dx)
    diff = (target_angle - theta + math.pi) % (2 * math.pi) - math.pi

    if abs(diff) > 0.12:
        turn_dir = 1 if diff > 0 else -1
        theta += ANGULAR_SPEED * dt * turn_dir
        log("D" if turn_dir > 0 else "A")
    else:
        dist = math.hypot(dx, dy)
        if dist > 5:
            robot_ax += LINEAR_SPEED * dt * math.cos(theta)
            robot_ay += LINEAR_SPEED * dt * math.sin(theta)
            log("W")
        else:
            log(f"→ WP{target_index+1} R{target_cell[0]}C{target_cell[1]}")
            target_index += 1

    # Auto-scroll: keep robot in center third of viewport
    vh = get_viewport_h()
    screen_robot_y = robot_ay - scroll_y
    margin = vh // 3
    if screen_robot_y < margin:
        scroll_y = max(0, robot_ay - margin)
    elif screen_robot_y > vh - margin:
        scroll_y = min(ARENA_H - vh, robot_ay - (vh - margin))
    clamp_scroll()

# ────────── MAIN LOOP ──────────
running = True
while running:
    dt = min(clock.tick(60) / 1000.0, 0.05)
    w, h = screen.get_size()
    clamp_scroll()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.VIDEORESIZE:
            clamp_scroll()
        if event.type == pygame.MOUSEWHEEL:
            scroll_y -= event.y * SCROLL_SPEED
            clamp_scroll()
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_r:
                reset_all()
            elif event.key == pygame.K_SPACE:
                if mode != 3 and start_cell and path_cells:
                    mode = 3; target_index = 0; task_done = False
                    pause_until = 0; run_start_time = time.time(); logs.clear()
            elif event.key in (pygame.K_DOWN,):
                scroll_y += SCROLL_SPEED * 3; clamp_scroll()
            elif event.key in (pygame.K_UP,):
                scroll_y -= SCROLL_SPEED * 3; clamp_scroll()
            elif event.key == pygame.K_PAGEDOWN:
                scroll_y += h - 60; clamp_scroll()
            elif event.key == pygame.K_PAGEUP:
                scroll_y -= h - 60; clamp_scroll()
            elif event.key == pygame.K_HOME:
                scroll_y = 0
            elif event.key == pygame.K_END:
                scroll_y = max(0, ARENA_H - h)

        if event.type == pygame.MOUSEBUTTONDOWN:
            pos = event.pos
            ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL
            clicked_btn = False
            for rect, label, m, color in BTNS:
                if rect.collidepoint(pos):
                    clicked_btn = True
                    if m == -1:
                        reset_all()
                    elif m == 3:
                        if start_cell and path_cells:
                            mode = 3; target_index = 0; task_done = False
                            pause_until = 0; run_start_time = time.time(); logs.clear()
                    else:
                        mode = m
                    break
            if not clicked_btn:
                cell = cell_from_mouse(pos)
                if cell:
                    row, col = cell
                    if mode == 1:
                        start_cell = cell
                        robot_ax, robot_ay = cell_arena_center(cell)
                        theta = -math.pi / 2
                        log(f"Start: R{row} C{col}")
                    elif mode == 2:
                        if ctrl:
                            if cell in path_cells: path_cells.remove(cell)
                        else:
                            if cell not in path_cells:
                                path_cells.append(cell)
                                log(f"WP{len(path_cells)}: R{row}C{col}")
                    elif mode == 4:
                        if ctrl:
                            if cell in kfs_cells: kfs_cells.remove(cell)
                        else:
                            if len(kfs_cells) < MAX_KFS and cell not in kfs_cells:
                                kfs_cells.append(cell)
                                log(f"KFS: R{row}C{col}")

    if mode == 3:
        move_robot(dt)

    # Build full arena surface, draw overlays, then blit only the visible slice
    arena_surf = build_arena_surface()
    draw_overlays(arena_surf)

    screen.fill(C_BG)
    # Blit only the visible vertical strip of the 1210px arena
    vh = get_viewport_h()
    src_rect = pygame.Rect(0, scroll_y, ARENA_W, min(vh, ARENA_H - scroll_y))
    screen.blit(arena_surf, (SIDEBAR_W, 0), src_rect)

    draw_scrollbar()
    draw_sidebar()
    draw_terminal()

    pygame.display.flip()

pygame.quit()
sys.exit()