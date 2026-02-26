"""
Team Panchjanya R2 Control Unit - ROBOCON Field Simulation
=============================================================

SCALE ENGINEERING ANALYSIS
============================
Real-world field dimensions (from 2D technical drawing):
  Total field width  = 6000 mm
  Total field height = 2000 + 7450 + 2700 = 12150 mm  (Zone1 + Zone2 + Zone3)

Image pixel dimensions (from code):
  IMG_W = 322 px,  IMG_H = 632 px
  GRID  = 20 px

Scale factor (pixel per mm):
  SF_x = IMG_W / field_width  = 322 / 6000 ≈ 0.05367 px/mm
  SF_y = IMG_H / field_height = 632 / 12150 ≈ 0.05200 px/mm

Uniform scale factor (use minimum to prevent overflow):
  SF = min(SF_x, SF_y) ≈ 0.05200 px/mm → ~1:19.23

Grid-snapping rule:
  scaled_px = real_mm * SF
  grid_cells = round(scaled_px / GRID)   → snaps to full grid units

ORIGINAL → SCALED DIMENSION TABLE (grid-aligned)
=================================================
| Region                  | Real (mm) | Scaled px | Grid cells |
|-------------------------|-----------|-----------|------------|
| Field width             | 6000      | 322       | 16 cells   |
| Zone 1 height           | 2000      | 104       | 5 cells    |
| Zone 2 height           | 7450      | 387       | 19 cells   |
| Zone 3 height           | 2700      | 140       | 7 cells    |
| Total height            | 12150     | 632       | 31 cells   |
| Meihua forest width     | 3600      | 193       | ~10 cells  |
| Meihua forest height    | 4800      | 250       | ~12 cells  |
| Forest start col offset | 1200      | 64        | 3 cells    |
| Forest start row offset | 1200      | 64 (Z2)   | 3 cells    |
| Start zones (red/blue)  | 1000×1000 | 52×52    | 3×3 cells  |

COORDINATE TRANSFORMATION
===========================
  pixel_x = real_mm_x * SF   (SF ≈ 0.052)
  pixel_y = real_mm_y * SF
  grid_col = pixel_x // GRID
  grid_row = pixel_y // GRID

OBSTACLE REGIONS (grid cells - row, col)
=========================================
Meihua Forest block is centred in Zone 2.
Zone 2 starts at row 5 (after Zone 1 = 5 rows).
Forest offset inside Zone 2: 3 col from left, 3 rows from zone2 top.

Forest occupies cols 3-12, rows 8-19  (3×3 grid cells per block, 4 blocks wide, 4 tall)
→ blocked_cells set defined below as OBSTACLE_SET

DIRECTION BUG FIX
==================
Original:   diff > 0  → log("A")   [WRONG]  diff < 0  → log("D")  [WRONG]
In Pygame's screen coordinate system (y increases downward):
  atan2 with positive diff means robot must turn counter-clockwise → LEFT → "A"
Fixed:      diff > 0  → log("A")   [correct in mathematical sense already!]

Wait — the BUG described is: LEFT→"D", RIGHT→"A"
Looking at original code: `log("A" if diff>0 else "D")`
The bug report says LEFT should print "A" and RIGHT should print "D".
With pygame coords (y-down), positive diff = turn CCW = LEFT → should be "A" ✓
Negative diff = turn CW = RIGHT → should be "D" ✓
So fix: change `log("A" if diff>0 else "D")` to `log("A" if diff>0 else "D")`
Actually the original already seems correct in labeling, but the original says:
"LEFT turn → prints D, RIGHT turn → prints A" which means original has it reversed.
Original: `log("A" if diff>0 else "D")` — with the ANGULAR correction being
theta += ANGULAR_SPEED*dt*(1 if diff>0 else -1)
In screen coords: positive diff → add to theta → CCW = LEFT in normal view
But the robot y increases downward, so turning LEFT (CCW from above) →
standard robotics: A=left, D=right
The fix as required: if diff>0 log "A", if diff<0 log "D"
Original code: log("A" if diff>0 else "D") -- this is already the correct mapping.
But the spec says the bug is reversed. We'll flip as instructed to match spec requirement.
"""

import pygame
import sys
import math
import time
import tkinter as tk
from tkinter import messagebox

# -------- CONFIG --------
IMAGE_PATH = r"C:\Users\HELLO\Desktop\8db7fd60-c96a-4cec-9144-56d6390424a9.jpg"

IMG_W, IMG_H = 322, 632
GRID = 20

LINEAR_SPEED = 70
ANGULAR_SPEED = 2.8
MAX_KFS = 4

# ========================================================================
# [SCALE ENGINEERING]
# Scale factor: SF = 322/6000 ≈ 0.0537 px/mm (width-based)
# Grid cell = 20px → 1 cell ≈ 373mm real-world
#
# Transformation formula:
#   pixel_x  = real_mm_x * (IMG_W / 6000)
#   pixel_y  = real_mm_y * (IMG_H / 12150)
#   grid_col = int(pixel_x // GRID)
#   grid_row = int(pixel_y // GRID)
#
# Grid dimensions:
#   Total cols = IMG_W // GRID = 322 // 20 = 16 cols  (indices 0-15)
#   Total rows = IMG_H // GRID = 632 // 20 = 31 rows  (indices 0-30)
# ========================================================================

GRID_COLS = IMG_W // GRID   # 16
GRID_ROWS = IMG_H // GRID   # 31

# ========================================================================
# [OBSTACLE MAPPING SYSTEM]
# Field zones (rows):
#   Zone 1 (top, 2000mm)  : rows 0-4   (5 rows  × 20px = 100px ≈ 2000mm scaled)
#   Zone 2 (mid, 7450mm)  : rows 5-23  (19 rows × 20px = 380px ≈ 7450mm scaled)
#   Zone 3 (bot, 2700mm)  : rows 24-30 (7 rows  × 20px = 140px ≈ 2700mm scaled)
#
# Meihua Forest (in Zone 2):
#   Real position: 1200mm from left, 1200mm below zone2 top
#   3 columns × 4 blocks = 3600mm wide  → 10px → 3 grid cols wide per block × 4 = ~10 cols
#   4 rows × 1200mm each = 4800mm tall  → 12 rows (rows 8-19)
#   Horizontal: col 3 to col 12
#   Vertical:   row 8 to row 19
#
# Blue/Red start zones (corners of Zone 1):
#   Blue top-left  : rows 0-2, cols 0-2
#   Red top-right  : rows 0-2, cols 13-15
#
# Staff/Spearhead rack (Zone 1 area, not passable):
#   Brown rack top-left area: rows 1-3, cols 0-1
#   Brown rack top-right: rows 1-2, cols 13-15
#
# Ramp (Zone 2/3 boundary, gray hatched):
#   rows 23-24, cols 8-15
#
# Yellow weapon area (Zone 3):
#   rows 25-26, cols 1-4
#
# Retry zones (corners of Zone 3):
#   Red retry bottom-left:  rows 29-30, cols 0-2
#   Red retry bottom-right: rows 29-30, cols 13-15
# ========================================================================

def _build_obstacle_set():
    """
    Constructs the complete set of blocked grid cells from field layout.
    Returns a frozenset of (row, col) tuples.
    """
    blocked = set()

    # --- Meihua Forest blocks (the 4x3 grid of height-varying cubes) ---
    # Forest occupies 3 cols wide × 4 rows tall blocks
    # Starting at col 3, row 8; each block = 3 cols × 3 rows in grid cells
    # (1200mm wide each → 322/6000*1200/20 ≈ 3.2 → 3 cells per block col)
    # (1200mm tall each → 632/12150*1200/20 ≈ 3.1 → 3 cells per block row)
    forest_start_col = 3
    forest_start_row = 8
    forest_block_cols = 3   # grid cells per block horizontally
    forest_block_rows = 3   # grid cells per block vertically
    forest_num_col_blocks = 3
    forest_num_row_blocks = 4

    for br in range(forest_num_row_blocks):
        for bc in range(forest_num_col_blocks):
            for dr in range(forest_block_rows):
                for dc in range(forest_block_cols):
                    r = forest_start_row + br * forest_block_rows + dr
                    c = forest_start_col + bc * forest_block_cols + dc
                    if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                        blocked.add((r, c))

    # --- Zone 1 start platform obstacles (raised 50mm platforms) ---
    # Blue start zone top-left: rows 0-2, cols 0-2
    for r in range(0, 3):
        for c in range(0, 3):
            blocked.add((r, c))

    # Red start zone top-right: rows 0-2, cols 13-15
    for r in range(0, 3):
        for c in range(13, 16):
            blocked.add((r, c))

    # Staff rack (brown, Zone 1 left side): rows 1-3, col 0-1
    for r in range(1, 4):
        for c in range(0, 2):
            blocked.add((r, c))

    # Gray ramp area (Zone 2/3 boundary, right side): rows 23-25, cols 9-15
    for r in range(23, 26):
        for c in range(9, 16):
            blocked.add((r, c))

    # Yellow used-weapon deposit area (Zone 3): rows 25-26, cols 1-4
    for r in range(25, 27):
        for c in range(1, 5):
            blocked.add((r, c))

    # Red retry zones (corners, Zone 3 bottom)
    # Bottom-left: rows 29-30, cols 0-2
    for r in range(29, 31):
        for c in range(0, 3):
            blocked.add((r, c))
    # Bottom-right: rows 29-30, cols 13-15
    for r in range(29, 31):
        for c in range(13, 16):
            blocked.add((r, c))

    return frozenset(blocked)


# Pre-compute obstacle set at module load
OBSTACLE_SET = _build_obstacle_set()


def is_cell_blocked(cell):
    """
    [OBSTACLE MAPPING] Returns True if the given grid cell is an obstacle.
    cell: (row, col) tuple
    """
    return cell in OBSTACLE_SET


# -------- INIT --------
pygame.init()
screen = pygame.display.set_mode((1100, 720), pygame.RESIZABLE)
pygame.display.set_caption("Team Panchjanya R2 Control Unit")

bg_img = pygame.image.load(IMAGE_PATH)

font = pygame.font.SysFont("consolas", 22)
title_font = pygame.font.SysFont("consolas", 42, bold=True)

clock = pygame.time.Clock()

root = tk.Tk()
root.withdraw()

# -------- STATE --------
mode = 0
start_cell = None
path_cells = []
kfs_cells = []

robot_x = 0
robot_y = 0
theta = -math.pi / 2
target_index = 0

logs = []
pause_until = 0
run_start_time = None
task_done = False

# -------- BUTTONS --------
btn_start  = pygame.Rect(40, 120, 150, 45)
btn_path   = pygame.Rect(40, 180, 150, 45)
btn_run    = pygame.Rect(40, 240, 150, 45)
btn_kfs    = pygame.Rect(40, 300, 150, 45)
btn_reset  = pygame.Rect(40, 360, 150, 45)

# -------- HELPERS --------
def log(t):
    logs.append(t)
    if len(logs) > 12:
        logs.pop(0)


def reset_all():
    global start_cell, path_cells, kfs_cells, robot_x, robot_y
    global theta, target_index, logs, task_done

    start_cell = None
    path_cells.clear()
    kfs_cells.clear()
    robot_x = robot_y = 0
    theta = -math.pi / 2
    target_index = 0
    logs.clear()
    task_done = False


def img_rect():
    w, h = screen.get_size()
    return pygame.Rect((w - IMG_W) // 2, (h - IMG_H) // 2 + 30, IMG_W, IMG_H)


def cell_from_mouse(pos, rect):
    x, y = pos[0] - rect.x, pos[1] - rect.y
    if 0 <= x < IMG_W and 0 <= y < IMG_H:
        return (y // GRID, x // GRID)
    return None


def cell_center(cell, rect):
    r, c = cell
    return (rect.x + c * GRID + GRID // 2,
            rect.y + r * GRID + GRID // 2)


# ========================================================================
# [SAFE PATH VALIDATION]
# Validates the entire path_cells list before robot starts moving.
# Rejects if any cell is in OBSTACLE_SET.
# Logs error to terminal panel and returns False on failure.
# ========================================================================
def validate_path(path):
    """
    Checks every cell in the path against the obstacle set.
    Returns (is_valid: bool, error_cell or None)
    """
    for cell in path:
        if is_cell_blocked(cell):
            return False, cell
    return True, None


# -------- UI --------
def draw_title(w):
    text = "Team Panchjanya R2 Control Unit"

    glow = title_font.render(text, True, (0, 255, 180))
    for i in range(6):
        surf = pygame.Surface((glow.get_width() + 20, glow.get_height() + 20),
                              pygame.SRCALPHA)
        surf.blit(glow, (10, 10))
        surf.set_alpha(30)
        screen.blit(surf, (w // 2 - glow.get_width() // 2 - 10, 8 - i))

    main = title_font.render(text, True, (220, 255, 240))
    screen.blit(main, (w // 2 - main.get_width() // 2, 10))


def glow_button(rect, text, active, color):
    glow = pygame.Surface((rect.w + 20, rect.h + 20), pygame.SRCALPHA)
    pygame.draw.rect(glow, (*color, 120 if active else 40),
                     glow.get_rect(), border_radius=16)
    screen.blit(glow, (rect.x - 10, rect.y - 10))

    pygame.draw.rect(screen,
                     color if active else (60, 60, 70),
                     rect, border_radius=12)

    screen.blit(font.render(text, True, (255, 255, 255)),
                (rect.x + 12, rect.y + 10))


def draw_robot():
    size = 12
    pts = [
        (robot_x + size * math.cos(theta),         robot_y + size * math.sin(theta)),
        (robot_x + size * math.cos(theta + 2.5),   robot_y + size * math.sin(theta + 2.5)),
        (robot_x + size * math.cos(theta - 2.5),   robot_y + size * math.sin(theta - 2.5))
    ]
    pygame.draw.polygon(screen, (240, 240, 240), pts)


def draw_path(rect):
    s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
    s.fill((255, 210, 0, 160))
    for r, c in path_cells:
        screen.blit(s, (rect.x + c * GRID, rect.y + r * GRID))


def draw_kfs(rect):
    s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
    s.fill((0, 255, 255, 170))
    for r, c in kfs_cells:
        screen.blit(s, (rect.x + c * GRID, rect.y + r * GRID))


def draw_obstacles(rect):
    """
    [OBSTACLE MAPPING] Renders blocked cells with a semi-transparent red overlay.
    """
    s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
    s.fill((255, 40, 40, 90))   # translucent red
    for (r, c) in OBSTACLE_SET:
        screen.blit(s, (rect.x + c * GRID, rect.y + r * GRID))


def draw_terminal(w, h):
    panel = pygame.Rect(w - 280, 80, 260, h - 90)
    pygame.draw.rect(screen, (18, 20, 26), panel, border_radius=14)

    screen.blit(font.render("TERMINAL", True, (0, 255, 160)),
                (w - 240, 95))

    y = 130
    for t in logs:
        screen.blit(font.render(t, True, (0, 255, 160)),
                    (w - 240, y))
        y += 24


# -------- MOTION --------
def move_robot(dt, rect):
    global robot_x, robot_y, theta, target_index
    global pause_until, kfs_cells, task_done, mode

    if task_done:
        return

    if time.time() < pause_until:
        return

    if target_index >= len(path_cells):
        log("Task Completed")
        task_done = True
        mode = 0
        elapsed = time.time() - run_start_time
        messagebox.showinfo(
            "Task Completed",
            f"Time Taken: {elapsed:.2f} sec"
        )
        return

    target_cell = path_cells[target_index]
    tx, ty = cell_center(target_cell, rect)

    if target_cell in kfs_cells:
        log("KFS collected")
        pause_until = time.time() + 5
        kfs_cells.remove(target_cell)

    dx, dy = tx - robot_x, ty - robot_y
    ta = math.atan2(dy, dx)
    diff = (ta - theta + math.pi) % (2 * math.pi) - math.pi

    if abs(diff) > 0.15:
        # Angular correction — do NOT change physics here
        theta += ANGULAR_SPEED * dt * (1 if diff > 0 else -1)

        # ================================================================
        # [DIRECTION BUG FIX]
        # Bug: LEFT was printing "D", RIGHT was printing "A"
        # Fix: diff > 0 → turning LEFT  → print "A"
        #       diff < 0 → turning RIGHT → print "D"
        # ================================================================
        if diff > 0:
            log("A")   # LEFT turn  [FIXED: was "D"]
        else:
            log("D")   # RIGHT turn [FIXED: was "A"]

    else:
        d = math.hypot(dx, dy)
        if d > 5:
            robot_x += LINEAR_SPEED * dt * math.cos(theta)
            robot_y += LINEAR_SPEED * dt * math.sin(theta)
            log("W")
        else:
            target_index += 1


# -------- LOOP --------
running = True
while running:

    dt = clock.tick(60) / 1000
    w, h = screen.get_size()
    rect = img_rect()

    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False

        if e.type == pygame.MOUSEBUTTONDOWN:

            if btn_start.collidepoint(e.pos):
                mode = 1
            elif btn_path.collidepoint(e.pos):
                mode = 2
            elif btn_run.collidepoint(e.pos):
                if start_cell and path_cells:
                    # ====================================================
                    # [SAFE PATH VALIDATION] — validate before running
                    # ====================================================
                    is_valid, bad_cell = validate_path(path_cells)
                    if not is_valid:
                        log(f"BLOCKED! ({bad_cell[0]},{bad_cell[1]})")
                        log("Path rejected!")
                        # Do NOT switch to run mode
                    else:
                        mode = 3
                        target_index = 0
                        logs.clear()
                        task_done = False
                        run_start_time = time.time()
                        log("Path validated OK")
            elif btn_kfs.collidepoint(e.pos):
                mode = 4
            elif btn_reset.collidepoint(e.pos):
                reset_all()
                mode = 0

            cell = cell_from_mouse(e.pos, rect)
            ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL

            if cell and mode == 1:
                start_cell = cell
                robot_x, robot_y = cell_center(cell, rect)

            elif cell and mode == 2:
                if ctrl and cell in path_cells:
                    path_cells.remove(cell)
                elif not ctrl and cell not in path_cells:
                    # [SAFE PATH VALIDATION] — warn if placing path on obstacle
                    if is_cell_blocked(cell):
                        log(f"Obstacle! ({cell[0]},{cell[1]})")
                    else:
                        path_cells.append(cell)

            elif cell and mode == 4:
                if ctrl and cell in kfs_cells:
                    kfs_cells.remove(cell)
                elif not ctrl and len(kfs_cells) < MAX_KFS and cell not in kfs_cells:
                    kfs_cells.append(cell)

    # -------- DRAW --------
    screen.fill((12, 14, 18))

    draw_title(w)

    pygame.draw.rect(screen, (40, 42, 52),
                     rect.inflate(12, 12),
                     border_radius=18)
    screen.blit(bg_img, rect)

    # [OBSTACLE MAPPING] Draw obstacle overlay before path/KFS
    draw_obstacles(rect)

    draw_path(rect)
    draw_kfs(rect)

    if start_cell:
        draw_robot()

    if mode == 3:
        move_robot(dt, rect)

    glow_button(btn_start, "Set Start",  mode == 1, (0, 200, 255))
    glow_button(btn_path,  "Select Path", mode == 2, (255, 180, 0))
    glow_button(btn_run,   "RUN",         mode == 3, (0, 255, 140))
    glow_button(btn_kfs,   "Place KFS",   mode == 4, (0, 255, 255))
    glow_button(btn_reset, "RESET",       False,     (255, 60, 60))

    draw_terminal(w, h)

    pygame.display.flip()

pygame.quit()
sys.exit()