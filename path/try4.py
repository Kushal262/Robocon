import pygame
import sys
import math
import time
import tkinter as tk
from tkinter import messagebox

# -------- CONFIG --------
IMG_W, IMG_H = 600, 1210   # Exact Figma frame dimensions
GRID = 20                  # Your original fine grid (change to 120 if you prefer coarser)

LINEAR_SPEED = 70
ANGULAR_SPEED = 2.8
MAX_KFS = 4

# Colors from your Figma CSS (RGB tuples)
COLOR_BORDER       = (0, 0, 0)
COLOR_TOP_BLUE     = (128, 199, 226)   # #80c7e2
COLOR_DARK_BLUE    = (50, 0, 255)      # #3200ff
COLOR_BROWN        = (155, 95, 0)      # #9b5f00
COLOR_SIDE_CYAN    = (128, 191, 209)   # #80bfd1
COLOR_FOREST_DARK  = (42, 113, 56)     # #2a7138
COLOR_FOREST_DARKER= (41, 82, 16)      # #295210
COLOR_FOREST_LIGHT = (152, 166, 80)    # #98a650
COLOR_BOTTOM_CYAN  = (129, 210, 214)   # #81d2d6
COLOR_SAND         = (192, 189, 182)   # #c0bdb6
COLOR_GRAY         = (113, 113, 113)   # #717171
COLOR_YELLOW       = (255, 225, 0)     # #ffe100

# -------- INIT --------
pygame.init()
screen = pygame.display.set_mode((1100, 1400), pygame.RESIZABLE)  # taller to show full 1210 px arena
pygame.display.set_caption("Team Panchjanya R2 Control Unit")

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
btn_start = pygame.Rect(40, 120, 150, 45)
btn_path  = pygame.Rect(40, 180, 150, 45)
btn_run   = pygame.Rect(40, 240, 150, 45)
btn_kfs   = pygame.Rect(40, 300, 150, 45)
btn_reset = pygame.Rect(40, 360, 150, 45)

# -------- HELPERS --------
def log(t):
    logs.append(t)
    if len(logs) > 12:
        logs.pop(0)

def reset_all():
    global start_cell, path_cells, kfs_cells, robot_x, robot_y
    global theta, target_index, logs, task_done, mode
    start_cell = None
    path_cells.clear()
    kfs_cells.clear()
    robot_x = robot_y = 0
    theta = -math.pi / 2
    target_index = 0
    logs.clear()
    task_done = False
    mode = 0

def img_rect():
    w, h = screen.get_size()
    return pygame.Rect((w - IMG_W) // 2, (h - IMG_H) // 2 + 30, IMG_W, IMG_H)

def cell_from_mouse(pos, rect):
    x, y = pos[0] - rect.x, pos[1] - rect.y
    if 0 <= x < IMG_W and 0 <= y < IMG_H:
        return (y // GRID, x // GRID)  # row, col
    return None

def cell_center(cell, rect):
    r, c = cell
    return (rect.x + c * GRID + GRID // 2,
            rect.y + r * GRID + GRID // 2)

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
        (robot_x + size * math.cos(theta), robot_y + size * math.sin(theta)),
        (robot_x + size * math.cos(theta + 2.5), robot_y + size * math.sin(theta + 2.5)),
        (robot_x + size * math.cos(theta - 2.5), robot_y + size * math.sin(theta - 2.5))
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

def draw_terminal(w, h):
    panel = pygame.Rect(w - 280, 80, 260, h - 90)
    pygame.draw.rect(screen, (18, 20, 26), panel, border_radius=14)
    screen.blit(font.render("TERMINAL", True, (0, 255, 160)), (w - 240, 95))
    y = 130
    for t in logs:
        screen.blit(font.render(t, True, (0, 255, 160)), (w - 240, y))
        y += 24

# -------- Figma Layout Drawing --------
def draw_figma_layout(rect):
    def draw_rect(color, x, y, w, h):
        abs_rect = pygame.Rect(rect.x + x, rect.y + y, w, h)
        pygame.draw.rect(screen, color, abs_rect)
        pygame.draw.rect(screen, COLOR_BORDER, abs_rect, 1)  # 1px black border like Figma

    # Top zone
    draw_rect(COLOR_TOP_BLUE,     2.5,   5, 600-5, 197-10)   # rectangle-5 (adjusted slightly)
    draw_rect(COLOR_DARK_BLUE,   502.5,  5, 100,   100)       # rectangle-2
    draw_rect(COLOR_BROWN,       302.5,  5, 80,    30)        # rectangle-3
    draw_rect(COLOR_BROWN,       -15,   35, 30,    120)       # rectangle-4
    draw_rect(COLOR_DARK_BLUE,   102.5,  5, 80,    80)        # rectangle-1

    # Side areas (cyan platforms)
    draw_rect(COLOR_SIDE_CYAN,    2.5, 205, 120, 745)
    draw_rect(COLOR_SIDE_CYAN,  482.5, 205, 120, 597)
    draw_rect(COLOR_SIDE_CYAN,  125.5, 205, 354, 120)
    draw_rect(COLOR_SIDE_CYAN,  125.5, 805, 477, 145)

    # Forest blocks
    draw_rect(COLOR_FOREST_DARK,  122.5, 325, 120, 120)   # rectangle-7
    draw_rect(COLOR_FOREST_DARK,  362.5, 325, 120, 120)   # rectangle-11
    draw_rect(COLOR_FOREST_DARK,  242.5, 445, 120, 120)   # rectangle-12
    draw_rect(COLOR_FOREST_DARK,  242.5, 685, 120, 120)   # rectangle-13
    draw_rect(COLOR_FOREST_DARK,  362.5, 565, 120, 120)   # rectangle-15
    draw_rect(COLOR_FOREST_DARK,  122.5, 565, 120, 120)   # rectangle-14
    draw_rect(COLOR_FOREST_DARKER,122.5, 685, 120, 120)   # rectangle-8
    draw_rect(COLOR_FOREST_DARKER,242.5, 325, 120, 120)   # rectangle-16
    draw_rect(COLOR_FOREST_DARKER,362.5, 445, 120, 120)   # rectangle-17
    draw_rect(COLOR_FOREST_DARKER,362.5, 685, 120, 120)   # rectangle-18
    draw_rect(COLOR_FOREST_LIGHT, 242.5, 565, 120, 120)   # rectangle-9
    draw_rect(COLOR_FOREST_LIGHT, 122.5, 445, 120, 120)   # rectangle-10

    # Bottom zone
    draw_rect(COLOR_BOTTOM_CYAN,  2.5,  955, 600-5, 250)   # rectangle-19
    draw_rect(COLOR_SAND,        452.5, 935, 150,   150)   # rectangle-20
    draw_rect(COLOR_GRAY,         -15,  999,  30,   162)   # rectangle-29
    draw_rect(COLOR_DARK_BLUE,    503, 1105, 100,   100)   # rectangle-30
    draw_rect(COLOR_YELLOW,      101.5, 955, 150,    30)   # rectangle-31

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
        messagebox.showinfo("Task Completed", f"Time Taken: {elapsed:.2f} sec")
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
        theta += ANGULAR_SPEED * dt * (1 if diff > 0 else -1)
        log("A" if diff > 0 else "D")
    else:
        d = math.hypot(dx, dy)
        if d > 5:
            robot_x += LINEAR_SPEED * dt * math.cos(theta)
            robot_y += LINEAR_SPEED * dt * math.sin(theta)
            log("W")
        else:
            target_index += 1

# -------- MAIN LOOP --------
running = True
while running:
    dt = clock.tick(60) / 1000.0
    w, h = screen.get_size()
    rect = img_rect()

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

    # DRAW EVERYTHING
    screen.fill((12, 14, 18))
    draw_title(w)

    # Arena container with shadow-like border
    pygame.draw.rect(screen, (40, 42, 52), rect.inflate(12, 12), border_radius=18)

    draw_figma_layout(rect)

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