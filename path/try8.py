import pygame
import sys
import math
import time
import tkinter as tk
from tkinter import messagebox

# ────────── CONFIG ──────────
# Arena exact Figma dimensions
ARENA_W, ARENA_H = 600, 1210
GRID = 20                        # 20px cells → 30 cols × 60 rows

COLS = ARENA_W // GRID           # 30
ROWS = ARENA_H // GRID           # 60 (actually 60.5 but we use 60)

LINEAR_SPEED = 80
ANGULAR_SPEED = 3.0
MAX_KFS = 4

# ── Window: fixed sidebar + arena, no awkward scaling ──
SIDEBAR_W = 200
TERMINAL_W = 260
WIN_W = SIDEBAR_W + ARENA_W + TERMINAL_W   # 200+600+260 = 1060
WIN_H = ARENA_H + 20                        # slight padding

# Colors from Figma CSS
C_BG            = (12, 14, 20)
C_BORDER        = (0, 0, 0)
C_ZONE1         = (128, 199, 226)   # #80c7e2
C_START_BLUE    = (50, 0, 255)      # #3200ff
C_RACK_BROWN    = (155, 95, 0)      # #9b5f00
C_PATH_CYAN     = (128, 191, 209)   # #80bfd1
C_FOREST_DARK   = (42, 113, 56)     # #2a7138
C_FOREST_DARKER = (41, 82, 16)      # #295210
C_FOREST_LIGHT  = (152, 166, 80)    # #98a650
C_ZONE3         = (129, 210, 214)   # #81d2d6
C_RAMP_SAND     = (192, 189, 182)   # #c0bdb6
C_TTT_RACK      = (113, 113, 113)   # #717171
C_WEAPON_YELLOW = (255, 225, 0)     # #ffe100

# UI Colors
C_CYAN   = (0, 200, 255)
C_AMBER  = (255, 180, 0)
C_GREEN  = (0, 255, 140)
C_TEAL   = (0, 240, 220)
C_RED    = (255, 60, 60)
C_WHITE  = (230, 240, 255)
C_TERM   = (0, 255, 180)
C_PANEL  = (18, 22, 30)
C_GRID   = (40, 60, 70, 60)        # semi-transparent grid lines

# ────────── INIT ──────────
pygame.init()
screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
pygame.display.set_caption("Team Panchjanya R2 — Control Unit")

font_sm  = pygame.font.SysFont("consolas", 15)
font_med = pygame.font.SysFont("consolas", 18)
font_lrg = pygame.font.SysFont("consolas", 22, bold=True)
font_ttl = pygame.font.SysFont("consolas", 26, bold=True)
clock = pygame.time.Clock()

root = tk.Tk(); root.withdraw()

# ────────── STATE ──────────
mode = 0          # 0=idle 1=setStart 2=placePath 3=run 4=placeKFS
start_cell = None
path_cells  = []
kfs_cells   = []
robot_x = robot_y = 0.0
theta = -math.pi / 2
target_index = 0
logs = []
pause_until  = 0
run_start_time = None
task_done    = False

# ────────── ARENA RECT (fixed, no scaling) ──────────
def arena_rect():
    """
    Arena is always placed right after the sidebar.
    Top-padded by 10px to give visual breathing room.
    """
    return pygame.Rect(SIDEBAR_W, 10, ARENA_W, ARENA_H)

# ────────── GRID HELPERS ──────────
def cell_from_mouse(pos):
    rect = arena_rect()
    x = pos[0] - rect.x
    y = pos[1] - rect.y
    if 0 <= x < ARENA_W and 0 <= y < ARENA_H:
        col = int(x // GRID)
        row = int(y // GRID)
        col = min(col, COLS - 1)
        row = min(row, ROWS - 1)
        return (row, col)
    return None

def cell_center(cell):
    """Pixel center of a cell in screen coordinates."""
    rect = arena_rect()
    row, col = cell
    return (rect.x + col * GRID + GRID // 2,
            rect.y + row * GRID + GRID // 2)

def cell_rect(cell):
    """pygame.Rect of a cell in screen coordinates."""
    rect = arena_rect()
    row, col = cell
    return pygame.Rect(rect.x + col * GRID, rect.y + row * GRID, GRID, GRID)

# ────────── ARENA DRAWING (pixel-perfect from Figma) ──────────
def draw_arena():
    rect = arena_rect()
    ox, oy = rect.x, rect.y   # origin offsets

    def dr(color, x, y, w, h, border=True):
        rx = ox + round(x)
        ry = oy + round(y)
        rw = round(w); rh = round(h)
        pygame.draw.rect(screen, color, (rx, ry, rw, rh))
        if border:
            pygame.draw.rect(screen, C_BORDER, (rx, ry, rw, rh), 1)

    # ── White background ──
    pygame.draw.rect(screen, (255, 255, 255), rect)
    pygame.draw.rect(screen, (129, 129, 129), rect, 1)

    # ── Zone 1 (top) ──
    dr(C_ZONE1,        2.5,   5, 600, 197)
    dr(C_START_BLUE, 502.5,   5, 100, 100)   # R1 start zone
    dr(C_RACK_BROWN, 302.5,   5,  80,  30)   # staff rack
    dr(C_RACK_BROWN,  -15,   35,  30, 120)   # spearhead rack (partially outside)
    dr(C_START_BLUE, 102.5,   5,  80,  80)   # R2 start zone

    # ── Pathways ──
    dr(C_PATH_CYAN,    2.5, 205, 120, 745)   # left corridor
    dr(C_PATH_CYAN,  482.5, 205, 120, 597)   # right corridor
    dr(C_PATH_CYAN,  125.5, 205, 354, 120)   # top cross-path
    dr(C_PATH_CYAN,  125.5, 805, 477, 145)   # bottom cross-path

    # ── Forest blocks (12, all 120×120) ──
    forest = [
        # row 1 (top=325)
        (122.5, 325, C_FOREST_DARK),
        (242.5, 325, C_FOREST_DARKER),
        (362.5, 325, C_FOREST_DARK),
        # row 2 (top=445)
        (122.5, 445, C_FOREST_LIGHT),
        (242.5, 445, C_FOREST_DARK),
        (362.5, 445, C_FOREST_DARKER),
        # row 3 (top=565)
        (122.5, 565, C_FOREST_DARK),
        (242.5, 565, C_FOREST_LIGHT),
        (362.5, 565, C_FOREST_DARK),
        # row 4 (top=685)
        (122.5, 685, C_FOREST_DARKER),
        (242.5, 685, C_FOREST_DARK),
        (362.5, 685, C_FOREST_DARKER),
    ]
    for fx, fy, col in forest:
        dr(col, fx, fy, 120, 120)

    # ── Zone 3 (bottom) ──
    dr(C_ZONE3,       2.5,  955, 600, 250)
    dr(C_RAMP_SAND, 452.5,  935, 150, 150)
    dr(C_TTT_RACK,    -15,  999,  30, 162)
    dr(C_START_BLUE,  503, 1105, 100, 100)   # retry blue
    dr(C_WEAPON_YELLOW, 101.5, 955, 150, 30) # weapon rack yellow

# ────────── GRID OVERLAY ──────────
def draw_grid():
    rect = arena_rect()
    grid_surf = pygame.Surface((ARENA_W, ARENA_H), pygame.SRCALPHA)

    # Vertical lines
    for c in range(COLS + 1):
        x = c * GRID
        pygame.draw.line(grid_surf, (0, 80, 100, 45), (x, 0), (x, ARENA_H))

    # Horizontal lines
    for r in range(ROWS + 1):
        y = r * GRID
        pygame.draw.line(grid_surf, (0, 80, 100, 45), (0, y), (ARENA_W, y))

    screen.blit(grid_surf, (rect.x, rect.y))

# ────────── PATH / KFS OVERLAYS ──────────
def draw_path():
    s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
    for i, cell in enumerate(path_cells):
        r, c = cell
        # Gradient from yellow to orange along path
        t = i / max(len(path_cells) - 1, 1)
        col = (255, int(210 - 80 * t), 0, 160)
        s.fill(col)
        screen.blit(s, cell_rect(cell).topleft)
        # Draw path index
        num = font_sm.render(str(i + 1), True, (0, 0, 0))
        cx, cy = cell_center(cell)
        screen.blit(num, (cx - num.get_width() // 2, cy - num.get_height() // 2))

def draw_path_line():
    """Draw connecting line between path waypoints."""
    if len(path_cells) > 1:
        pts = [cell_center(c) for c in path_cells]
        pygame.draw.lines(screen, (255, 140, 0, 200), False, pts, 2)

def draw_kfs():
    for cell in kfs_cells:
        s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
        s.fill((0, 255, 220, 190))
        screen.blit(s, cell_rect(cell).topleft)
        # Draw K marker
        k = font_sm.render("K", True, (0, 60, 60))
        cx, cy = cell_center(cell)
        screen.blit(k, (cx - k.get_width() // 2, cy - k.get_height() // 2))

# ────────── ROBOT ──────────
def draw_robot():
    size = 12
    pts = [
        (robot_x + size * math.cos(theta),
         robot_y + size * math.sin(theta)),
        (robot_x + size * math.cos(theta + 2.5),
         robot_y + size * math.sin(theta + 2.5)),
        (robot_x + size * math.cos(theta - 2.5),
         robot_y + size * math.sin(theta - 2.5)),
    ]
    pygame.draw.polygon(screen, (240, 240, 255), pts)
    pygame.draw.polygon(screen, (0, 200, 255), pts, 2)
    pygame.draw.circle(screen, (0, 180, 255), (int(robot_x), int(robot_y)), 4)

    # Direction arrow
    ex = robot_x + size * math.cos(theta)
    ey = robot_y + size * math.sin(theta)
    pygame.draw.line(screen, (255, 255, 100), (int(robot_x), int(robot_y)), (int(ex), int(ey)), 2)

# ────────── SIDEBAR ──────────
BTN_X = 20
BTN_W = SIDEBAR_W - 40
BTN_H = 42
BTNS = [
    (pygame.Rect(BTN_X, 120, BTN_W, BTN_H), "Set Start",    1, C_CYAN),
    (pygame.Rect(BTN_X, 172, BTN_W, BTN_H), "Path Mode",    2, C_AMBER),
    (pygame.Rect(BTN_X, 224, BTN_W, BTN_H), "Place KFS",    4, C_TEAL),
    (pygame.Rect(BTN_X, 276, BTN_W, BTN_H), "▶  RUN",       3, C_GREEN),
    (pygame.Rect(BTN_X, 342, BTN_W, BTN_H), "RESET",        -1, C_RED),
]

def draw_sidebar():
    # Background panel
    pygame.draw.rect(screen, C_PANEL, (0, 0, SIDEBAR_W, WIN_H))
    pygame.draw.rect(screen, (30, 40, 55), (0, 0, SIDEBAR_W, WIN_H), 1)

    # Title
    t1 = font_ttl.render("PANCHJANYA", True, C_TERM)
    t2 = font_sm.render("R2 Control Unit", True, (120, 200, 180))
    screen.blit(t1, (SIDEBAR_W // 2 - t1.get_width() // 2, 18))
    screen.blit(t2, (SIDEBAR_W // 2 - t2.get_width() // 2, 50))

    # Separator
    pygame.draw.line(screen, (30, 80, 60), (10, 72), (SIDEBAR_W - 10, 72), 1)

    # Mode labels
    mode_names = {0: "IDLE", 1: "SET START", 2: "PATH MODE", 3: "RUNNING", 4: "KFS MODE"}
    mname = mode_names.get(mode, "IDLE")
    mc = C_GREEN if mode == 3 else C_AMBER if mode in (1, 2, 4) else (100, 120, 130)
    ml = font_sm.render(f"MODE: {mname}", True, mc)
    screen.blit(ml, (SIDEBAR_W // 2 - ml.get_width() // 2, 82))

    # Buttons
    for rect, label, m, color in BTNS:
        active = (mode == m)
        # Glow
        gsurf = pygame.Surface((rect.w + 20, rect.h + 20), pygame.SRCALPHA)
        pygame.draw.rect(gsurf, (*color, 100 if active else 25),
                         gsurf.get_rect(), border_radius=14)
        screen.blit(gsurf, (rect.x - 10, rect.y - 10))
        # Button
        bg = color if active else (35, 42, 55)
        pygame.draw.rect(screen, bg, rect, border_radius=10)
        pygame.draw.rect(screen, (*color, 180 if active else 60), rect, 2, border_radius=10)
        txt = font_med.render(label, True, C_WHITE)
        screen.blit(txt, (rect.x + rect.w // 2 - txt.get_width() // 2,
                          rect.y + rect.h // 2 - txt.get_height() // 2))

    # Stats
    sy = 400
    def stat(label, val, color=(180, 200, 210)):
        nonlocal sy
        screen.blit(font_sm.render(label, True, (90, 110, 130)), (BTN_X, sy))
        screen.blit(font_sm.render(str(val), True, color), (BTN_X + 10, sy + 16))
        sy += 38

    pygame.draw.line(screen, (30, 60, 50), (10, sy - 8), (SIDEBAR_W - 10, sy - 8), 1)
    stat("Waypoints:", len(path_cells), C_AMBER)
    stat("KFS placed:", f"{len(kfs_cells)}/{MAX_KFS}", C_TEAL)
    if start_cell:
        stat("Start cell:", f"R{start_cell[0]} C{start_cell[1]}", C_CYAN)
    if mode == 3 and not task_done and run_start_time:
        elapsed = time.time() - run_start_time
        stat("Elapsed:", f"{elapsed:.1f}s", C_GREEN)
        stat("WP index:", f"{target_index}/{len(path_cells)}", C_GREEN)

    # Controls hint
    hint_y = WIN_H - 120
    pygame.draw.line(screen, (30, 60, 50), (10, hint_y - 8), (SIDEBAR_W - 10, hint_y - 8), 1)
    hints = ["[Click] Add cell", "[Ctrl+Clk] Remove", "", "Path cells: ordered", "KFS: 5s pause"]
    for i, h in enumerate(hints):
        col = (60, 80, 90) if not h else (90, 110, 120)
        screen.blit(font_sm.render(h, True, col), (BTN_X, hint_y + i * 18))

# ────────── TERMINAL ──────────
def draw_terminal():
    tx = SIDEBAR_W + ARENA_W
    tw = WIN_W - tx
    pygame.draw.rect(screen, C_PANEL, (tx, 0, tw, WIN_H))
    pygame.draw.rect(screen, (25, 40, 35), (tx, 0, tw, WIN_H), 1)

    screen.blit(font_lrg.render("TERMINAL", True, C_TERM), (tx + 18, 18))
    pygame.draw.line(screen, (0, 120, 80), (tx + 10, 46), (tx + tw - 10, 46), 1)

    # Scrolling log
    y = 58
    for entry in logs[-38:]:
        # Color-code commands
        if entry.startswith("W"):
            col = (100, 255, 150)
        elif entry.startswith("A") or entry.startswith("D"):
            col = (255, 200, 80)
        elif "KFS" in entry:
            col = (0, 255, 220)
        elif "Task" in entry:
            col = (255, 100, 100)
        else:
            col = C_TERM
        txt = font_sm.render(entry, True, col)
        screen.blit(txt, (tx + 14, y))
        y += 19
        if y > WIN_H - 20:
            break

# ────────── LOG ──────────
def log(t):
    ts = f"{time.time() - (run_start_time or time.time()):.1f}s"
    logs.append(f"[{ts}] {t}")
    if len(logs) > 200:
        logs.pop(0)

# ────────── RESET ──────────
def reset_all():
    global start_cell, path_cells, kfs_cells, robot_x, robot_y
    global theta, target_index, logs, task_done, mode, pause_until, run_start_time
    start_cell = None
    path_cells.clear()
    kfs_cells.clear()
    robot_x = robot_y = 0.0
    theta = -math.pi / 2
    target_index = 0
    logs.clear()
    task_done = False
    mode = 0
    pause_until = 0
    run_start_time = None

# ────────── MOTION ──────────
def move_robot(dt):
    global robot_x, robot_y, theta, target_index, pause_until, task_done, mode

    if task_done:
        return

    now = time.time()
    if now < pause_until:
        log(f"KFS pause {pause_until - now:.1f}s")
        return

    if target_index >= len(path_cells):
        log("✓ Task Completed")
        task_done = True
        mode = 0
        elapsed = now - run_start_time
        messagebox.showinfo("Task Completed",
                            f"All waypoints reached!\nTime: {elapsed:.2f}s")
        return

    target_cell = path_cells[target_index]
    tx, ty = cell_center(target_cell)

    # KFS check
    if target_cell in kfs_cells:
        log(f"★ KFS collected at R{target_cell[0]}C{target_cell[1]}")
        pause_until = now + 5
        kfs_cells.remove(target_cell)
        return

    dx = tx - robot_x
    dy = ty - robot_y
    target_angle = math.atan2(dy, dx)
    diff = (target_angle - theta + math.pi) % (2 * math.pi) - math.pi

    if abs(diff) > 0.12:
        # positive diff → target is to the right → turn right (D)
        # negative diff → target is to the left  → turn left  (A)
        turn_dir = 1 if diff > 0 else -1
        theta += ANGULAR_SPEED * dt * turn_dir
        log("D" if turn_dir > 0 else "A")
    else:
        dist = math.hypot(dx, dy)
        if dist > 5:
            robot_x += LINEAR_SPEED * dt * math.cos(theta)
            robot_y += LINEAR_SPEED * dt * math.sin(theta)
            log("W")
        else:
            log(f"→ WP {target_index + 1} reached (R{target_cell[0]}C{target_cell[1]})")
            target_index += 1

# ────────── MAIN LOOP ──────────
running = True
while running:
    dt = min(clock.tick(60) / 1000.0, 0.05)  # cap dt to avoid physics jumps

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_r:
                reset_all()
            elif event.key == pygame.K_SPACE and mode != 3:
                if start_cell and path_cells:
                    mode = 3
                    target_index = 0
                    task_done = False
                    pause_until = 0
                    run_start_time = time.time()
                    logs.clear()

        if event.type == pygame.MOUSEBUTTONDOWN:
            pos = event.pos
            ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL

            # Sidebar buttons
            for rect, label, m, color in BTNS:
                if rect.collidepoint(pos):
                    if m == -1:
                        reset_all()
                    elif m == 3:
                        if start_cell and path_cells:
                            mode = 3
                            target_index = 0
                            task_done = False
                            pause_until = 0
                            run_start_time = time.time()
                            logs.clear()
                    else:
                        mode = m
                    break

            # Arena clicks
            cell = cell_from_mouse(pos)
            if cell:
                if mode == 1:
                    start_cell = cell
                    robot_x, robot_y = cell_center(cell)
                    theta = -math.pi / 2
                    log(f"Start set: R{cell[0]} C{cell[1]}")

                elif mode == 2:
                    if ctrl:
                        if cell in path_cells:
                            path_cells.remove(cell)
                            log(f"WP removed: R{cell[0]}C{cell[1]}")
                    else:
                        if cell not in path_cells:
                            path_cells.append(cell)
                            log(f"WP {len(path_cells)}: R{cell[0]}C{cell[1]}")

                elif mode == 4:
                    if ctrl:
                        if cell in kfs_cells:
                            kfs_cells.remove(cell)
                            log(f"KFS removed: R{cell[0]}C{cell[1]}")
                    else:
                        if len(kfs_cells) < MAX_KFS and cell not in kfs_cells:
                            kfs_cells.append(cell)
                            log(f"KFS placed: R{cell[0]}C{cell[1]}")

    # ── DRAW ──
    screen.fill(C_BG)

    draw_arena()
    draw_grid()
    draw_path_line()
    draw_path()
    draw_kfs()

    if start_cell:
        draw_robot()

    # Highlight hovered cell
    if mode in (1, 2, 4):
        hover = cell_from_mouse(pygame.mouse.get_pos())
        if hover:
            hs = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
            hs.fill((255, 255, 255, 60))
            screen.blit(hs, cell_rect(hover).topleft)

    if mode == 3:
        move_robot(dt)

    draw_sidebar()
    draw_terminal()

    pygame.display.flip()

pygame.quit()
sys.exit()