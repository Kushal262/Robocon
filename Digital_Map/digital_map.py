import pygame
import sys
import math
import time
import tkinter as tk
from tkinter import messagebox

# =====================================================================
# CONFIGURABLE GRID SIZES (in mm) — change these to adjust grid density
# =====================================================================
GRID_MC       = 100   # Martial Club grid cell size (mm)
GRID_PATHWAY  = 100   # R1/R2 Pathway grid cell size (mm)
GRID_FOREST   = 120   # Forest block grid cell size (mm)
GRID_ARENA    = 100   # Arena grid cell size (mm)
GRID_RAMP     = 100   # Ramp grid cell size (mm)

# =====================================================================
# DISPLAY CONFIG
# =====================================================================
SCALE = 0.08        # mm → pixel conversion (0.08 means 1000mm = 80px)
PANEL_LEFT = 220    # left control panel width (px)
PANEL_RIGHT = 280   # right terminal panel width (px)
MAP_MARGIN = 20     # margin around map (px)

# Robot  — adjust ROBOT_SPEED to control how fast the robot moves
ROBOT_SPEED   = 800   # mm/s in game world (try 400–2000)
R2_SIZE_MM    = 800   # R2 hitbox side (mm)
MAX_KFS       = 8     # max KFS to place

# =====================================================================
# FIELD DIMENSIONS IN MM  (converted from CSS: 100px = 1000mm)
# Origin (0,0) is the top-left of the field frame.
# =====================================================================
FIELD_W_MM = 6000
FIELD_H_MM = 12100

# --- Zone 1: Martial Club ---
ZONE1 = {
    "name": "Zone 1 – Martial Club",
    "x": 25, "y": 50, "w": 6000, "h": 1970,
    "color": (128, 199, 226),  # #80c7e2
    "grid": "GRID_MC",
}

R1_START_ZONE = {
    "name": "R1 Start Zone",
    "x": 5025, "y": 50, "w": 1000, "h": 1000,
    "color": (50, 0, 255),  # #3200ff
}

R2_START_ZONE = {
    "name": "R2 Start Zone",
    "x": 1025, "y": 50, "w": 800, "h": 800,
    "color": (50, 0, 255),  # #3200ff
}

STAFF_RACK = {
    "name": "Staff Rack",
    "x": 3025, "y": 50, "w": 800, "h": 300,
    "color": (155, 95, 0),  # #9b5f00
}

# --- Zone 2: Meihua Forest pathways ---
R1_PATHWAY_LEFT = {
    "name": "R1 Pathway (L)",
    "x": 25, "y": 2050, "w": 1200, "h": 7450,
    "color": (128, 191, 209),  # #80bfd1
    "grid": "GRID_PATHWAY",
}

R1_PATHWAY_RIGHT = {
    "name": "R1 Pathway (R)",
    "x": 4825, "y": 2050, "w": 1200, "h": 5970,
    "color": (128, 191, 209),
    "grid": "GRID_PATHWAY",
}

R2_ENTRANCE = {
    "name": "R2 Entrance",
    "x": 1255, "y": 2050, "w": 3540, "h": 1200,
    "color": (128, 191, 209),
    "grid": "GRID_PATHWAY",
}

R2_EXIT = {
    "name": "R2 Exit",
    "x": 1255, "y": 8050, "w": 4770, "h": 1450,
    "color": (128, 191, 209),
    "grid": "GRID_PATHWAY",
}

# --- Zone 3: Arena ---
ZONE3 = {
    "name": "Zone 3 – Arena",
    "x": 25, "y": 9550, "w": 6000, "h": 2500,
    "color": (129, 210, 214),  # #81d2d6
    "grid": "GRID_ARENA",
}

RAMP = {
    "name": "Ramp",
    "x": 4525, "y": 9350, "w": 1500, "h": 1500,
    "color": (192, 189, 182),  # #c0bdb6
    "grid": "GRID_RAMP",
}

RETRY_ZONE_ARENA = {
    "name": "Arena Retry Zone",
    "x": 5030, "y": 11050, "w": 1000, "h": 1000,
    "color": (50, 0, 255),
}

USED_WEAPON = {
    "name": "Used Weapon Area",
    "x": 1015, "y": 9550, "w": 1500, "h": 300,
    "color": (255, 225, 0),  # #ffe100
}

# --- Forest blocks (12 blocks, 1200mm × 1200mm each) ---
# Heights determine color: 200mm = #295210, 400mm = #2a7138, 600mm = #98a650
FOREST_COLORS = {
    200: (41, 82, 16),    # dark green
    400: (42, 113, 56),   # medium green
    600: (152, 166, 80),  # light green
}

FOREST_BLOCKS = [
    # (block_num, x_mm, y_mm, w_mm, h_mm, height_mm)
    (1,  3625, 3250, 1200, 1200, 400),
    (2,  2425, 3250, 1200, 1200, 200),
    (3,  1225, 3250, 1200, 1200, 400),
    (4,  3625, 4450, 1200, 1200, 200),
    (5,  2425, 4450, 1200, 1200, 400),
    (6,  1225, 4450, 1200, 1200, 600),
    (7,  3625, 5650, 1200, 1200, 400),
    (8,  2425, 5650, 1200, 1200, 600),
    (9,  1225, 5650, 1200, 1200, 400),
    (10, 3625, 6850, 1200, 1200, 200),
    (11, 2425, 6850, 1200, 1200, 400),
    (12, 1225, 6850, 1200, 1200, 200),
]

# =====================================================================
# ALL ZONES (for grid drawing & collision), ordered bottom-to-top draw
# =====================================================================
BACKGROUND_ZONES = [ZONE1, R1_PATHWAY_LEFT, R1_PATHWAY_RIGHT,
                    R2_ENTRANCE, R2_EXIT, ZONE3]
OVERLAY_ZONES = [R1_START_ZONE, R2_START_ZONE, STAFF_RACK,
                 RAMP, RETRY_ZONE_ARENA, USED_WEAPON]

# Navigable zone rects for R2 (mm) — the robot must stay inside these
R2_NAVIGABLE = [
    ZONE1, R2_ENTRANCE, R2_EXIT, ZONE3, RAMP,
    # Forest blocks are navigable too (R2 steps on top)
]

# =====================================================================
# HELPER: mm → screen pixel
# =====================================================================
def mm2px(x_mm, y_mm, ox, oy):
    """Convert mm coordinates to screen pixels given map origin."""
    return (int(ox + x_mm * SCALE), int(oy + y_mm * SCALE))

def mm2size(w_mm, h_mm):
    return (max(1, int(w_mm * SCALE)), max(1, int(h_mm * SCALE)))

def px2mm(sx, sy, ox, oy):
    """Convert screen pixel to mm coordinates."""
    return ((sx - ox) / SCALE, (sy - oy) / SCALE)

# =====================================================================
# INIT
# =====================================================================
pygame.init()

# Calculate initial window size to fit the map + panels
map_w_px = int(FIELD_W_MM * SCALE) + MAP_MARGIN * 2
map_h_px = int(FIELD_H_MM * SCALE) + MAP_MARGIN * 2
WIN_W = PANEL_LEFT + map_w_px + PANEL_RIGHT
WIN_H = max(map_h_px + 80, 720)  # +80 for title bar

screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
pygame.display.set_caption("Robocon 2026 – R2 Digital Map (Blue Team)")

font       = pygame.font.SysFont("consolas", 16)
font_small = pygame.font.SysFont("consolas", 13)
title_font = pygame.font.SysFont("consolas", 28, bold=True)
label_font = pygame.font.SysFont("consolas", 11)
block_font = pygame.font.SysFont("arial", 14, bold=True)

clock = pygame.time.Clock()

# Tkinter for popups
root = tk.Tk()
root.withdraw()

# =====================================================================
# STATE
# =====================================================================
mode = 0          # 0=idle, 1=set start, 2=select path, 3=running, 4=place KFS
start_pos = None  # (x_mm, y_mm) in field coords
path_cells = []   # list of (cell_cx_mm, cell_cy_mm, grid_mm) — filled grid cells
kfs_cells  = []   # list of (block_num, x_mm, y_mm)

robot_x = 0.0     # mm
robot_y = 0.0     # mm
target_index = 0

logs = []
pause_until = 0
run_start_time = None
task_done = False

# =====================================================================
# BUTTONS
# =====================================================================
btn_start = pygame.Rect(25, 140, 170, 40)
btn_path  = pygame.Rect(25, 195, 170, 40)
btn_run   = pygame.Rect(25, 250, 170, 40)
btn_kfs   = pygame.Rect(25, 305, 170, 40)
btn_reset = pygame.Rect(25, 360, 170, 40)

# =====================================================================
# HELPERS
# =====================================================================
def log(t):
    logs.append(t)
    if len(logs) > 20:
        logs.pop(0)

def reset_all():
    global start_pos, path_cells, kfs_cells, robot_x, robot_y
    global target_index, logs, task_done, mode
    start_pos = None
    path_cells.clear()
    kfs_cells.clear()
    robot_x = robot_y = 0
    target_index = 0
    logs.clear()
    task_done = False
    mode = 0

def get_map_origin():
    """Top-left pixel of the field map on screen."""
    return (PANEL_LEFT + MAP_MARGIN, 60)

def snap_to_grid(x_mm, y_mm, grid_mm):
    """Snap mm coordinate to the nearest grid cell center."""
    cx = (int(x_mm / grid_mm)) * grid_mm + grid_mm / 2
    cy = (int(y_mm / grid_mm)) * grid_mm + grid_mm / 2
    return (cx, cy)

def point_in_rect_mm(x, y, zone):
    """Check if (x_mm, y_mm) is inside a zone dict."""
    return (zone["x"] <= x <= zone["x"] + zone["w"] and
            zone["y"] <= y <= zone["y"] + zone["h"])

def get_zone_at(x_mm, y_mm):
    """Return the zone dict the point is in, or None."""
    # Check forest blocks first
    for b in FOREST_BLOCKS:
        bx, by, bw, bh = b[1], b[2], b[3], b[4]
        if bx <= x_mm <= bx + bw and by <= y_mm <= by + bh:
            return {"name": f"Forest Block {b[0]}", "x": bx, "y": by,
                    "w": bw, "h": bh, "grid": "GRID_FOREST"}
    # Check overlay zones
    for z in OVERLAY_ZONES:
        if point_in_rect_mm(x_mm, y_mm, z):
            return z
    # Check background zones
    for z in BACKGROUND_ZONES:
        if point_in_rect_mm(x_mm, y_mm, z):
            return z
    return None

def get_grid_for_pos(x_mm, y_mm):
    """Return the appropriate grid size (mm) for the given position."""
    z = get_zone_at(x_mm, y_mm)
    if z is None:
        return GRID_MC  # default
    g = z.get("grid", "GRID_MC")
    grid_map = {
        "GRID_MC": GRID_MC,
        "GRID_PATHWAY": GRID_PATHWAY,
        "GRID_FOREST": GRID_FOREST,
        "GRID_ARENA": GRID_ARENA,
        "GRID_RAMP": GRID_RAMP,
    }
    return grid_map.get(g, GRID_MC)

def is_on_ramp(x_mm, y_mm):
    """Check if a position is on the ramp."""
    return point_in_rect_mm(x_mm, y_mm, RAMP)

def get_forest_block_at(x_mm, y_mm):
    """Return forest block tuple if the point is inside one, else None."""
    for b in FOREST_BLOCKS:
        bx, by, bw, bh = b[1], b[2], b[3], b[4]
        if bx <= x_mm <= bx + bw and by <= y_mm <= by + bh:
            return b
    return None

# =====================================================================
# DRAWING
# =====================================================================
def draw_title():
    w = screen.get_width()
    text = "Robocon 2026 – R2 Digital Map"
    glow = title_font.render(text, True, (0, 200, 255))
    for i in range(4):
        surf = pygame.Surface((glow.get_width() + 16, glow.get_height() + 16),
                              pygame.SRCALPHA)
        surf.blit(glow, (8, 8))
        surf.set_alpha(25)
        screen.blit(surf, (w // 2 - glow.get_width() // 2 - 8, 8 - i))
    main = title_font.render(text, True, (220, 245, 255))
    screen.blit(main, (w // 2 - main.get_width() // 2, 10))

def glow_button(rect, text, active, color):
    glow = pygame.Surface((rect.w + 16, rect.h + 16), pygame.SRCALPHA)
    pygame.draw.rect(glow, (*color, 100 if active else 30),
                     glow.get_rect(), border_radius=14)
    screen.blit(glow, (rect.x - 8, rect.y - 8))
    pygame.draw.rect(screen, color if active else (55, 55, 65),
                     rect, border_radius=10)
    lbl = font.render(text, True, (255, 255, 255))
    screen.blit(lbl, (rect.x + rect.w // 2 - lbl.get_width() // 2,
                      rect.y + rect.h // 2 - lbl.get_height() // 2))

def draw_zone_rect(zone, ox, oy, draw_label=True):
    """Draw a single zone rectangle on the map."""
    px, py = mm2px(zone["x"], zone["y"], ox, oy)
    pw, ph = mm2size(zone["w"], zone["h"])
    pygame.draw.rect(screen, zone["color"], (px, py, pw, ph))
    pygame.draw.rect(screen, (0, 0, 0), (px, py, pw, ph), 1)
    if draw_label and "name" in zone:
        lbl = label_font.render(zone["name"], True, (0, 0, 0))
        screen.blit(lbl, (px + 4, py + 3))

def draw_forest_block(block, ox, oy):
    """Draw a forest block with height coloring and number label."""
    num, bx, by, bw, bh, height = block
    color = FOREST_COLORS.get(height, (42, 113, 56))
    px, py = mm2px(bx, by, ox, oy)
    pw, ph = mm2size(bw, bh)
    pygame.draw.rect(screen, color, (px, py, pw, ph))
    pygame.draw.rect(screen, (0, 0, 0), (px, py, pw, ph), 1)
    # Block number
    num_lbl = block_font.render(str(num), True, (255, 255, 255))
    screen.blit(num_lbl, (px + pw // 2 - num_lbl.get_width() // 2,
                          py + ph // 2 - num_lbl.get_height() // 2))
    # Height label
    h_lbl = font_small.render(f"{height}mm", True, (220, 220, 220))
    screen.blit(h_lbl, (px + 3, py + ph - h_lbl.get_height() - 2))

def draw_grid_for_zone(zone, ox, oy, grid_mm, grid_color=(0, 0, 0, 40)):
    """Draw a grid overlay on a zone."""
    zx, zy, zw, zh = zone["x"], zone["y"], zone["w"], zone["h"]
    px0, py0 = mm2px(zx, zy, ox, oy)
    pw, ph = mm2size(zw, zh)
    step_px = max(1, int(grid_mm * SCALE))
    if step_px < 4:
        return  # grid too dense to draw
    s = pygame.Surface((pw, ph), pygame.SRCALPHA)
    # Vertical lines
    x = 0
    while x <= pw:
        pygame.draw.line(s, grid_color, (x, 0), (x, ph), 1)
        x += step_px
    # Horizontal lines
    y = 0
    while y <= ph:
        pygame.draw.line(s, grid_color, (0, y), (pw, y), 1)
        y += step_px
    screen.blit(s, (px0, py0))

def draw_map(ox, oy):
    """Draw the entire field map."""
    # Field boundary
    fw, fh = mm2size(FIELD_W_MM, FIELD_H_MM)
    pygame.draw.rect(screen, (240, 240, 240), (ox, oy, fw, fh))
    pygame.draw.rect(screen, (130, 130, 130), (ox, oy, fw, fh), 2)

    # Background zones
    for z in BACKGROUND_ZONES:
        draw_zone_rect(z, ox, oy)
        g = z.get("grid")
        if g:
            grid_map = {"GRID_MC": GRID_MC, "GRID_PATHWAY": GRID_PATHWAY,
                        "GRID_ARENA": GRID_ARENA}
            gv = grid_map.get(g, GRID_MC)
            draw_grid_for_zone(z, ox, oy, gv)

    # Forest blocks
    for b in FOREST_BLOCKS:
        draw_forest_block(b, ox, oy)
        # Grid overlay on each forest block
        fz = {"x": b[1], "y": b[2], "w": b[3], "h": b[4]}
        draw_grid_for_zone(fz, ox, oy, GRID_FOREST, (0, 0, 0, 50))

    # Overlay zones
    for z in OVERLAY_ZONES:
        draw_zone_rect(z, ox, oy)
        g = z.get("grid")
        if g:
            grid_map = {"GRID_RAMP": GRID_RAMP}
            gv = grid_map.get(g, GRID_MC)
            draw_grid_for_zone(z, ox, oy, gv)

    # Zone section labels (large semi-transparent)
    sections = [
        ("MARTIAL CLUB", ZONE1),
        ("MEIHUA FOREST", {"x": 1225, "y": 3250, "w": 3600, "h": 4800}),
        ("ARENA", ZONE3),
    ]
    for name, z in sections:
        px, py = mm2px(z["x"], z["y"], ox, oy)
        pw, ph = mm2size(z["w"], z["h"])
        sec_lbl = font.render(name, True, (0, 0, 0))
        lbl_surf = pygame.Surface((sec_lbl.get_width(), sec_lbl.get_height()),
                                  pygame.SRCALPHA)
        lbl_surf.blit(sec_lbl, (0, 0))
        lbl_surf.set_alpha(60)
        screen.blit(lbl_surf, (px + pw // 2 - sec_lbl.get_width() // 2,
                               py + ph // 2 - sec_lbl.get_height() // 2))

def draw_path_overlay(ox, oy):
    """Draw selected path as filled grid squares."""
    for i, (cx, cy, g) in enumerate(path_cells):
        # Top-left of the grid cell in mm
        cell_x = cx - g / 2
        cell_y = cy - g / 2
        px, py = mm2px(cell_x, cell_y, ox, oy)
        pw, ph = mm2size(g, g)
        # Filled highlight
        s = pygame.Surface((pw, ph), pygame.SRCALPHA)
        s.fill((255, 210, 0, 100))  # semi-transparent yellow
        screen.blit(s, (px, py))
        pygame.draw.rect(screen, (255, 180, 0), (px, py, pw, ph), 2)
        # Sequence number in center
        n = font_small.render(str(i + 1), True, (255, 255, 255))
        screen.blit(n, (px + pw // 2 - n.get_width() // 2,
                        py + ph // 2 - n.get_height() // 2))
        # Line connecting to previous cell center
        if i > 0:
            pcx, pcy, _ = path_cells[i - 1]
            ppx, ppy = mm2px(pcx, pcy, ox, oy)
            cpx, cpy = mm2px(cx, cy, ox, oy)
            pygame.draw.line(screen, (255, 210, 0), (ppx, ppy), (cpx, cpy), 1)

def draw_kfs_overlay(ox, oy):
    """Draw placed KFS indicators on forest blocks."""
    for bnum, kx, ky in kfs_cells:
        px, py = mm2px(kx, ky, ox, oy)
        # Cyan square representing KFS cube
        half = max(2, int(350 * SCALE / 2))  # 350mm KFS cube at scale
        r = pygame.Rect(px - half, py - half, half * 2, half * 2)
        s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        s.fill((0, 255, 255, 150))
        screen.blit(s, r.topleft)
        pygame.draw.rect(screen, (0, 200, 200), r, 2)
        lbl = font_small.render("KFS", True, (0, 60, 60))
        screen.blit(lbl, (px - lbl.get_width() // 2, py - lbl.get_height() // 2))

def draw_robot(ox, oy):
    """Draw R2 as a triangle pointing toward next waypoint, with hitbox."""
    if start_pos is None:
        return
    px, py = mm2px(robot_x, robot_y, ox, oy)
    size = max(6, int(R2_SIZE_MM * SCALE / 2))  # visual half-size

    # Hitbox outline (square)
    hb = int(R2_SIZE_MM * SCALE)
    hitbox_rect = pygame.Rect(px - hb // 2, py - hb // 2, hb, hb)
    s = pygame.Surface((hb, hb), pygame.SRCALPHA)
    s.fill((255, 255, 255, 25))
    screen.blit(s, hitbox_rect.topleft)
    pygame.draw.rect(screen, (255, 255, 255, 80), hitbox_rect, 1)

    # Compute heading toward next target (or default up)
    if target_index < len(path_cells):
        tx, ty = path_cells[target_index][0], path_cells[target_index][1]
        heading = math.atan2(ty - robot_y, tx - robot_x)
    else:
        heading = -math.pi / 2  # default: facing up

    # Triangle pointing in heading direction
    pts = [
        (px + size * math.cos(heading),        py + size * math.sin(heading)),
        (px + size * math.cos(heading + 2.5),  py + size * math.sin(heading + 2.5)),
        (px + size * math.cos(heading - 2.5),  py + size * math.sin(heading - 2.5)),
    ]
    pygame.draw.polygon(screen, (0, 200, 255), pts)
    pygame.draw.polygon(screen, (255, 255, 255), pts, 1)

def draw_terminal():
    """Draw log / terminal panel on the right."""
    w, h = screen.get_size()
    panel_x = w - PANEL_RIGHT + 10
    panel = pygame.Rect(panel_x, 60, PANEL_RIGHT - 20, h - 70)
    pygame.draw.rect(screen, (18, 20, 28), panel, border_radius=12)

    # Header
    hdr = font.render("TERMINAL", True, (0, 200, 160))
    screen.blit(hdr, (panel_x + 12, 72))

    # Logs
    y = 100
    for t in logs[-18:]:
        line = font_small.render(t, True, (0, 220, 150))
        screen.blit(line, (panel_x + 12, y))
        y += 18
        if y > panel.bottom - 10:
            break

    # Info section at bottom of terminal
    info_y = panel.bottom - 90
    pygame.draw.line(screen, (40, 50, 40), (panel_x + 10, info_y),
                     (panel_x + PANEL_RIGHT - 40, info_y), 1)
    info_y += 8
    info_lines = [
        f"Robot: ({robot_x:.0f}, {robot_y:.0f}) mm",
        f"Speed: {ROBOT_SPEED} mm/s",
        f"Path cells: {len(path_cells)}",
        f"KFS placed: {len(kfs_cells)}/{MAX_KFS}",
    ]
    for line in info_lines:
        txt = font_small.render(line, True, (0, 180, 140))
        screen.blit(txt, (panel_x + 12, info_y))
        info_y += 16

def draw_mode_indicator():
    """Show current mode on the left panel."""
    mode_names = {
        0: ("IDLE", (120, 120, 130)),
        1: ("SET START", (0, 200, 255)),
        2: ("SELECT PATH", (255, 180, 0)),
        3: ("RUNNING", (0, 255, 140)),
        4: ("PLACE KFS", (0, 255, 255)),
    }
    name, color = mode_names.get(mode, ("IDLE", (120, 120, 130)))
    lbl = font.render(f"Mode: {name}", True, color)
    screen.blit(lbl, (25, 110))

def draw_legend():
    """Draw forest height legend on left panel."""
    y = 430
    lbl = font_small.render("Forest Heights:", True, (180, 180, 190))
    screen.blit(lbl, (25, y))
    y += 20
    for h_mm, color in sorted(FOREST_COLORS.items()):
        pygame.draw.rect(screen, color, (25, y, 18, 14))
        pygame.draw.rect(screen, (200, 200, 200), (25, y, 18, 14), 1)
        txt = font_small.render(f" {h_mm}mm", True, (180, 180, 190))
        screen.blit(txt, (46, y))
        y += 20

    y += 10
    lbl = font_small.render("Grid Sizes (mm):", True, (180, 180, 190))
    screen.blit(lbl, (25, y))
    y += 20
    grids = [
        ("MC", GRID_MC), ("Pathway", GRID_PATHWAY),
        ("Forest", GRID_FOREST), ("Arena", GRID_ARENA),
        ("Ramp", GRID_RAMP),
    ]
    for name, val in grids:
        txt = font_small.render(f" {name}: {val}", True, (150, 150, 160))
        screen.blit(txt, (25, y))
        y += 16

def draw_mouse_info(ox, oy):
    """Show coordinate of mouse position on field."""
    mx, my = pygame.mouse.get_pos()
    x_mm, y_mm = px2mm(mx, my, ox, oy)
    if 0 <= x_mm <= FIELD_W_MM and 0 <= y_mm <= FIELD_H_MM:
        zone = get_zone_at(x_mm, y_mm)
        zone_name = zone["name"] if zone else "Outside"
        info = f"({x_mm:.0f}, {y_mm:.0f})mm  [{zone_name}]"
        txt = font_small.render(info, True, (200, 200, 210))
        h = screen.get_height()
        screen.blit(txt, (PANEL_LEFT + 10, h - 22))

# =====================================================================
# ROBOT MOTION
# =====================================================================
def move_robot(dt, ox, oy):
    """Move robot directly from cell-center to cell-center (no rotation delay)."""
    global robot_x, robot_y, target_index
    global pause_until, task_done, mode

    if task_done:
        return
    if time.time() < pause_until:
        return
    if target_index >= len(path_cells):
        log(">> Task Completed")
        task_done = True
        mode = 0
        elapsed = time.time() - run_start_time
        messagebox.showinfo("Task Completed", f"Time Taken: {elapsed:.2f} sec")
        return

    tx, ty = path_cells[target_index][0], path_cells[target_index][1]

    # Check if target is on a KFS — collect it
    for kfs in kfs_cells[:]:
        kx, ky = kfs[1], kfs[2]
        if math.hypot(tx - kx, ty - ky) < 200:
            log(f">> KFS collected (Block {kfs[0]})")
            pause_until = time.time() + 2
            kfs_cells.remove(kfs)
            break

    # Move directly toward target cell center
    dx, dy = tx - robot_x, ty - robot_y
    d = math.hypot(dx, dy)
    if d > 20:  # 20mm tolerance
        step = ROBOT_SPEED * dt
        if step >= d:
            # Snap to target
            robot_x, robot_y = tx, ty
        else:
            robot_x += step * (dx / d)
            robot_y += step * (dy / d)
    else:
        robot_x, robot_y = tx, ty
        log(f">> Reached cell {target_index + 1}")
        target_index += 1

# =====================================================================
# MAIN LOOP
# =====================================================================
running = True
while running:
    dt = clock.tick(60) / 1000.0
    w, h = screen.get_size()
    ox, oy = get_map_origin()

    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False

        elif e.type == pygame.MOUSEBUTTONDOWN:
            # Button clicks
            if btn_start.collidepoint(e.pos):
                mode = 1
                log("Mode: SET START — click on map")
            elif btn_path.collidepoint(e.pos):
                mode = 2
                log("Mode: SELECT PATH — click waypoints")
            elif btn_run.collidepoint(e.pos):
                if start_pos and path_cells:
                    mode = 3
                    target_index = 0
                    task_done = False
                    run_start_time = time.time()
                    log(">> RUN started")
                else:
                    log("ERR: Set start & path first")
            elif btn_kfs.collidepoint(e.pos):
                mode = 4
                log("Mode: PLACE KFS — click forest blocks")
            elif btn_reset.collidepoint(e.pos):
                reset_all()
                log(">> RESET complete")
            else:
                # Map clicks
                x_mm, y_mm = px2mm(e.pos[0], e.pos[1], ox, oy)
                if 0 <= x_mm <= FIELD_W_MM and 0 <= y_mm <= FIELD_H_MM:
                    ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL
                    grid = get_grid_for_pos(x_mm, y_mm)
                    sx, sy = snap_to_grid(x_mm, y_mm, grid)

                    if mode == 1:  # Set start
                        start_pos = (sx, sy)
                        robot_x, robot_y = sx, sy
                        zone = get_zone_at(x_mm, y_mm)
                        zn = zone["name"] if zone else "field"
                        log(f"Start: ({sx:.0f},{sy:.0f}) [{zn}]")

                    elif mode == 2:  # Select path — toggle grid cells
                        cell = (sx, sy, grid)
                        # Check if this cell is already selected
                        existing = [c for c in path_cells
                                    if c[0] == sx and c[1] == sy]
                        if ctrl or existing:
                            # Remove cell (Ctrl+click or click again)
                            if existing:
                                path_cells.remove(existing[0])
                                log(f"Removed cell ({sx:.0f},{sy:.0f})")
                        else:
                            path_cells.append(cell)
                            log(f"Cell #{len(path_cells)}: ({sx:.0f},{sy:.0f})")

                    elif mode == 4:  # Place KFS
                        fb = get_forest_block_at(x_mm, y_mm)
                        if fb:
                            bnum = fb[0]
                            cx = fb[1] + fb[3] / 2
                            cy = fb[2] + fb[4] / 2
                            # Check if already placed on this block
                            existing = [k for k in kfs_cells if k[0] == bnum]
                            if ctrl:
                                if existing:
                                    kfs_cells.remove(existing[0])
                                    log(f"Removed KFS from Block {bnum}")
                            else:
                                if not existing and len(kfs_cells) < MAX_KFS:
                                    kfs_cells.append((bnum, cx, cy))
                                    log(f"KFS placed on Block {bnum}")
                                elif existing:
                                    log(f"Block {bnum} already has KFS")
                                else:
                                    log(f"Max KFS ({MAX_KFS}) reached")
                        else:
                            log("Click inside a forest block")

    # ---- DRAW ----
    screen.fill((14, 16, 22))

    draw_title()
    draw_map(ox, oy)
    draw_path_overlay(ox, oy)
    draw_kfs_overlay(ox, oy)
    draw_robot(ox, oy)

    if mode == 3:
        move_robot(dt, ox, oy)

    # UI
    glow_button(btn_start, "Set Start",   mode == 1, (0, 200, 255))
    glow_button(btn_path,  "Select Path", mode == 2, (255, 180, 0))
    glow_button(btn_run,   "RUN",         mode == 3, (0, 255, 140))
    glow_button(btn_kfs,   "Place KFS",   mode == 4, (0, 255, 255))
    glow_button(btn_reset, "RESET",       False,     (255, 60, 60))

    draw_mode_indicator()
    draw_legend()
    draw_terminal()
    draw_mouse_info(ox, oy)

    pygame.display.flip()

pygame.quit()
sys.exit()
