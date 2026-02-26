import pygame
import sys
import math
import time
import tkinter as tk
from tkinter import messagebox

# ────────── CONFIG ──────────
IMG_W, IMG_H = 600, 1210           # exact Figma dimensions
GRID = 20                          # fine grid – matches your original code
LINEAR_SPEED = 70
ANGULAR_SPEED = 2.8
MAX_KFS = 4

# Colors from your CSS
COLOR_BORDER       = (0, 0, 0)
COLOR_ZONE1        = (128, 199, 226)   # #80c7e2
COLOR_START_BLUE   = (50, 0, 255)      # #3200ff
COLOR_RACK_BROWN   = (155, 95, 0)      # #9b5f00
COLOR_PATH_CYAN    = (128, 191, 209)   # #80bfd1
COLOR_FOREST_DARK  = (42, 113, 56)     # #2a7138
COLOR_FOREST_DARKER= (41, 82, 16)      # #295210
COLOR_FOREST_LIGHT = (152, 166, 80)    # #98a650
COLOR_ZONE3        = (129, 210, 214)   # #81d2d6
COLOR_RAMP_SAND    = (192, 189, 182)   # #c0bdb6
COLOR_TTT_RACK     = (113, 113, 113)   # #717171
COLOR_RETRY_BLUE   = (50, 0, 255)      # #3200ff
COLOR_WEAPON_YELLOW= (255, 225, 0)     # #ffe100

# ────────── INIT ──────────
pygame.init()
screen = pygame.display.set_mode((1280, 1350), pygame.RESIZABLE)  # taller to show full 1210 px arena
pygame.display.set_caption("Team Panchjanya R2 Control Unit")

font = pygame.font.SysFont("consolas", 20)
title_font = pygame.font.SysFont("consolas", 38, bold=True)
clock = pygame.time.Clock()

root = tk.Tk()
root.withdraw()

# ────────── STATE ──────────
mode = 0
start_cell = None
path_cells = []
kfs_cells = []
robot_x = robot_y = 0
theta = -math.pi / 2
target_index = 0
logs = []
pause_until = 0
run_start_time = None
task_done = False

# ────────── BUTTONS ──────────
btn_start = pygame.Rect(30, 100, 140, 45)
btn_path  = pygame.Rect(30, 155, 140, 45)
btn_run   = pygame.Rect(30, 210, 140, 45)
btn_kfs   = pygame.Rect(30, 265, 140, 45)
btn_reset = pygame.Rect(30, 320, 140, 45)

# ────────── HELPERS ──────────
def log(t):
    logs.append(t)
    if len(logs) > 12:
        logs.pop(0)

def reset_all():
    global start_cell, path_cells, kfs_cells, robot_x, robot_y, theta, target_index, logs, task_done, mode
    start_cell = None
    path_cells.clear()
    kfs_cells.clear()
    robot_x = robot_y = 0
    theta = -math.pi / 2
    target_index = 0
    logs.clear()
    task_done = False
    mode = 0

def arena_rect():
    w, h = screen.get_size()
    # More generous top margin + ensure bottom is visible
    top_margin = max(60, (h - IMG_H) // 4)
    return pygame.Rect((w - IMG_W) // 2, top_margin, IMG_W, IMG_H)

def cell_from_mouse(pos, rect):
    x = pos[0] - rect.x
    y = pos[1] - rect.y
    if 0 <= x < IMG_W and 0 <= y < IMG_H:
        return (y // GRID, x // GRID)
    return None

def cell_center(cell, rect):
    r, c = cell
    return rect.x + c * GRID + GRID // 2, rect.y + r * GRID + GRID // 2

# ────────── DRAW FUNCTIONS ──────────
def draw_title(w):
    text = "Team Panchjanya R2 Control Unit"
    glow = title_font.render(text, True, (0, 255, 180))
    for i in range(5):
        surf = pygame.Surface((glow.get_width() + 16, glow.get_height() + 16), pygame.SRCALPHA)
        surf.blit(glow, (8, 8))
        surf.set_alpha(40 - i*8)
        screen.blit(surf, (w // 2 - glow.get_width() // 2 - 8, 12 - i))
    main = title_font.render(text, True, (220, 255, 240))
    screen.blit(main, (w // 2 - main.get_width() // 2, 15))

def glow_button(rect, text, active, color):
    glow = pygame.Surface((rect.w + 16, rect.h + 16), pygame.SRCALPHA)
    pygame.draw.rect(glow, (*color, 140 if active else 50), glow.get_rect(), border_radius=12)
    screen.blit(glow, (rect.x - 8, rect.y - 8))
    pygame.draw.rect(screen, color if active else (70, 70, 80), rect, border_radius=10)
    screen.blit(font.render(text, True, (255,255,255)), (rect.x + 12, rect.y + 12))

def draw_robot():
    size = 14
    pts = [
        (robot_x + size * math.cos(theta),     robot_y + size * math.sin(theta)),
        (robot_x + size * math.cos(theta + 2.4), robot_y + size * math.sin(theta + 2.4)),
        (robot_x + size * math.cos(theta - 2.4), robot_y + size * math.sin(theta - 2.4)),
    ]
    pygame.draw.polygon(screen, (240, 240, 255), pts)
    pygame.draw.circle(screen, (180,180,255), (int(robot_x), int(robot_y)), 5)

def draw_path(rect):
    s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
    s.fill((255, 210, 0, 140))
    for r, c in path_cells:
        screen.blit(s, (rect.x + c * GRID, rect.y + r * GRID))

def draw_kfs(rect):
    s = pygame.Surface((GRID, GRID), pygame.SRCALPHA)
    s.fill((0, 240, 240, 160))
    for r, c in kfs_cells:
        screen.blit(s, (rect.x + c * GRID, rect.y + r * GRID))

def draw_terminal(w, h):
    panel = pygame.Rect(w - 260, 70, 240, h - 90)
    pygame.draw.rect(screen, (20, 22, 28), panel, border_radius=12)
    screen.blit(font.render("TERMINAL", True, (0, 255, 180)), (w - 220, 85))
    y = 120
    for t in logs:
        screen.blit(font.render(t, True, (0, 255, 180)), (w - 220, y))
        y += 22

def draw_arena(rect):
    def dr(color, x, y, w, h):
        rx = rect.x + round(x)
        ry = rect.y + round(y)
        pygame.draw.rect(screen, color, (rx, ry, round(w), round(h)))
        pygame.draw.rect(screen, COLOR_BORDER, (rx, ry, round(w), round(h)), 1)

    # Top / Zone 1
    dr(COLOR_ZONE1,       2.5,   5, 595, 192)
    dr(COLOR_START_BLUE, 502.5,  5, 100, 100)     # r-1-start-zone
    dr(COLOR_RACK_BROWN, 302.5,  5,  80,  30)     # staff-rack
    dr(COLOR_RACK_BROWN,  -15,  35,  30, 120)     # spearhead-rack
    dr(COLOR_START_BLUE, 102.5,  5,  80,  80)     # r-2-start-zone

    # Pathways / Side area
    dr(COLOR_PATH_CYAN,    2.5, 205, 120, 745)
    dr(COLOR_PATH_CYAN,  482.5, 205, 120, 597)
    dr(COLOR_PATH_CYAN,  125.5, 205, 354, 120)
    dr(COLOR_PATH_CYAN,  125.5, 805, 477, 145)

    # Forest (12 blocks)
    forest = [
        (362.5, 325, COLOR_FOREST_DARK),
        (242.5, 325, COLOR_FOREST_DARKER),
        (122.5, 325, COLOR_FOREST_DARK),
        (362.5, 445, COLOR_FOREST_DARKER),
        (242.5, 445, COLOR_FOREST_DARK),
        (122.5, 445, COLOR_FOREST_LIGHT),
        (362.5, 565, COLOR_FOREST_DARK),
        (242.5, 565, COLOR_FOREST_LIGHT),
        (122.5, 565, COLOR_FOREST_DARK),
        (362.5, 685, COLOR_FOREST_DARKER),
        (242.5, 685, COLOR_FOREST_DARK),
        (122.5, 685, COLOR_FOREST_DARKER),
    ]
    for x, y, col in forest:
        dr(col, x, y, 120, 120)

    # Bottom / Zone 3 – now fully visible
    dr(COLOR_ZONE3,       2.5, 955, 595, 250)
    dr(COLOR_RAMP_SAND, 452.5, 935, 150, 150)
    dr(COLOR_TTT_RACK,   -15, 999,  30, 162)
    dr(COLOR_RETRY_BLUE, 503, 1105, 100, 100)
    dr(COLOR_WEAPON_YELLOW, 101.5, 955, 150, 30)

# ────────── MOTION (with corrected turn logging) ──────────
def move_robot(dt, rect):
    global robot_x, robot_y, theta, target_index, pause_until, kfs_cells, task_done, mode

    if task_done or time.time() < pause_until:
        return

    if target_index >= len(path_cells):
        log("Task Completed")
        task_done = True
        mode = 0
        messagebox.showinfo("Task Completed", f"Time Taken: {time.time() - run_start_time:.2f} sec")
        return

    target_cell = path_cells[target_index]
    tx, ty = cell_center(target_cell, rect)

    if target_cell in kfs_cells:
        log("KFS collected")
        pause_until = time.time() + 5
        kfs_cells.remove(target_cell)

    dx = tx - robot_x
    dy = ty - robot_y
    ta = math.atan2(dy, dx)
    diff = (ta - theta + math.pi) % (2 * math.pi) - math.pi

    if abs(diff) > 0.15:
        # Reversed logic:
        # positive diff → turn right → "D"
        # negative diff → turn left → "A"
        turn_dir = 1 if diff > 0 else -1
        theta += ANGULAR_SPEED * dt * turn_dir
        log("D" if turn_dir > 0 else "A")
    else:
        d = math.hypot(dx, dy)
        if d > 6:
            robot_x += LINEAR_SPEED * dt * math.cos(theta)
            robot_y += LINEAR_SPEED * dt * math.sin(theta)
            log("W")
        else:
            target_index += 1

# ────────── MAIN LOOP ──────────
running = True
while running:
    dt = clock.tick(60) / 1000.0
    w, h = screen.get_size()
    rect = arena_rect()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if btn_start.collidepoint(event.pos): mode = 1
            elif btn_path.collidepoint(event.pos): mode = 2
            elif btn_run.collidepoint(event.pos):
                if start_cell and path_cells:
                    mode = 3
                    target_index = 0
                    logs.clear()
                    task_done = False
                    run_start_time = time.time()
            elif btn_kfs.collidepoint(event.pos): mode = 4
            elif btn_reset.collidepoint(event.pos):
                reset_all()

            cell = cell_from_mouse(event.pos, rect)
            ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL

            if cell:
                if mode == 1:
                    start_cell = cell
                    robot_x, robot_y = cell_center(cell, rect)
                elif mode == 2:
                    if ctrl and cell in path_cells:
                        path_cells.remove(cell)
                    elif not ctrl and cell not in path_cells:
                        path_cells.append(cell)
                elif mode == 4:
                    if ctrl and cell in kfs_cells:
                        kfs_cells.remove(cell)
                    elif not ctrl and len(kfs_cells) < MAX_KFS and cell not in kfs_cells:
                        kfs_cells.append(cell)

    screen.fill((12, 14, 18))
    draw_title(w)
    pygame.draw.rect(screen, (40, 42, 52), rect.inflate(14, 14), border_radius=16)

    draw_arena(rect)
    draw_path(rect)
    draw_kfs(rect)

    if start_cell:
        draw_robot()

    if mode == 3:
        move_robot(dt, rect)

    glow_button(btn_start, "Set Start", mode == 1, (0, 200, 255))
    glow_button(btn_path,  "Select Path", mode == 2, (255, 180, 0))
    glow_button(btn_run,   "RUN", mode == 3, (0, 255, 140))
    glow_button(btn_kfs,   "Place KFS", mode == 4, (0, 255, 255))
    glow_button(btn_reset, "RESET", False, (255, 60, 60))

    draw_terminal(w, h)

    pygame.display.flip()

pygame.quit()
sys.exit()