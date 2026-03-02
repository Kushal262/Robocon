import pygame
import sys
import math
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

# ── Try importing pyserial ──────────────────────────────────────────────────
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("[WARN] pyserial not installed.  Run:  pip install pyserial")

# =====================================================================
# ★ NEW — PHYSICAL ROBOT CONFIG
# =====================================================================
# After connecting, press RUN and your real robot follows the path.
#
# PHYSICAL_SPEED_MM_S : How fast the real robot travels at DRIVE_SPEED.
#   Measure it:  drive straight for 2 sec, measure distance → divide.
#   Start conservative (400) and tune upward.
#
# DRIVE_SPEED : PWM value sent to Arduino (0–255).
#   Must match MAX_SPEED in Arduino sketch (or be ≤ MAX_SPEED).
#
# SERIAL_BAUD : Must match Serial.begin() in Arduino sketch.
#
# INTER_SEGMENT_PAUSE_S : brief stop between waypoints so the real
#   robot doesn't overshoot corners.  0.0 to disable.
# =====================================================================
PHYSICAL_SPEED_MM_S    = 500     # mm/s — tune this to your real robot
DRIVE_SPEED            = 150     # PWM 0–255 — keep ≤ MAX_SPEED in Arduino
SERIAL_BAUD            = 115200  # must match Arduino sketch
INTER_SEGMENT_PAUSE_S  = 0.15    # seconds to stop between waypoints

# =====================================================================
# CONFIGURABLE GRID SIZES (in mm)
# =====================================================================
GRID_MC       = 100
GRID_PATHWAY  = 100
GRID_FOREST   = 120
GRID_ARENA    = 100
GRID_RAMP     = 100

# =====================================================================
# DISPLAY CONFIG
# =====================================================================
SCALE        = 0.08
PANEL_LEFT   = 220
PANEL_RIGHT  = 280
MAP_MARGIN   = 20

ROBOT_SPEED  = 800
R2_SIZE_MM   = 800
MAX_KFS      = 8

# =====================================================================
# FIELD DIMENSIONS IN MM
# =====================================================================
FIELD_W_MM = 6000
FIELD_H_MM = 12100

# ---- Zone definitions (unchanged from original) ----
ZONE1 = {"name": "Zone 1 – Martial Club",  "x": 25,   "y": 50,   "w": 6000, "h": 1970, "color": (128,199,226), "grid": "GRID_MC"}
R1_START_ZONE = {"name": "R1 Start Zone",  "x": 5025, "y": 50,   "w": 1000, "h": 1000, "color": (50,0,255)}
R2_START_ZONE = {"name": "R2 Start Zone",  "x": 1025, "y": 50,   "w": 800,  "h": 800,  "color": (50,0,255)}
STAFF_RACK    = {"name": "Staff Rack",     "x": 3025, "y": 50,   "w": 800,  "h": 300,  "color": (155,95,0)}
R1_PATHWAY_LEFT  = {"name": "R1 Pathway (L)", "x": 25,   "y": 2050, "w": 1200, "h": 7450, "color": (128,191,209), "grid": "GRID_PATHWAY"}
R1_PATHWAY_RIGHT = {"name": "R1 Pathway (R)", "x": 4825, "y": 2050, "w": 1200, "h": 5970, "color": (128,191,209), "grid": "GRID_PATHWAY"}
R2_ENTRANCE  = {"name": "R2 Entrance",    "x": 1255, "y": 2050, "w": 3540, "h": 1200, "color": (128,191,209), "grid": "GRID_PATHWAY"}
R2_EXIT      = {"name": "R2 Exit",        "x": 1255, "y": 8050, "w": 4770, "h": 1450, "color": (128,191,209), "grid": "GRID_PATHWAY"}
ZONE3        = {"name": "Zone 3 – Arena", "x": 25,   "y": 9550, "w": 6000, "h": 2500, "color": (129,210,214), "grid": "GRID_ARENA"}
RAMP         = {"name": "Ramp",           "x": 4525, "y": 9350, "w": 1500, "h": 1500, "color": (192,189,182), "grid": "GRID_RAMP"}
RETRY_ZONE_ARENA = {"name": "Arena Retry Zone", "x": 5030, "y": 11050, "w": 1000, "h": 1000, "color": (50,0,255)}
USED_WEAPON  = {"name": "Used Weapon Area","x": 1015, "y": 9550, "w": 1500, "h": 300,  "color": (255,225,0)}

FOREST_COLORS = {200:(41,82,16), 400:(42,113,56), 600:(152,166,80)}
FOREST_BLOCKS = [
    (1,3625,3250,1200,1200,400),(2,2425,3250,1200,1200,200),(3,1225,3250,1200,1200,400),
    (4,3625,4450,1200,1200,200),(5,2425,4450,1200,1200,400),(6,1225,4450,1200,1200,600),
    (7,3625,5650,1200,1200,400),(8,2425,5650,1200,1200,600),(9,1225,5650,1200,1200,400),
    (10,3625,6850,1200,1200,200),(11,2425,6850,1200,1200,400),(12,1225,6850,1200,1200,200),
]

BACKGROUND_ZONES = [ZONE1, R1_PATHWAY_LEFT, R1_PATHWAY_RIGHT, R2_ENTRANCE, R2_EXIT, ZONE3]
OVERLAY_ZONES    = [R1_START_ZONE, R2_START_ZONE, STAFF_RACK, RAMP, RETRY_ZONE_ARENA, USED_WEAPON]

# =====================================================================
# HELPERS
# =====================================================================
def mm2px(x_mm, y_mm, ox, oy):
    return (int(ox + x_mm * SCALE), int(oy + y_mm * SCALE))

def mm2size(w_mm, h_mm):
    return (max(1, int(w_mm * SCALE)), max(1, int(h_mm * SCALE)))

def px2mm(sx, sy, ox, oy):
    return ((sx - ox) / SCALE, (sy - oy) / SCALE)

def snap_to_grid(x_mm, y_mm, grid_mm):
    cx = (int(x_mm / grid_mm)) * grid_mm + grid_mm / 2
    cy = (int(y_mm / grid_mm)) * grid_mm + grid_mm / 2
    return (cx, cy)

def point_in_rect_mm(x, y, zone):
    return (zone["x"] <= x <= zone["x"] + zone["w"] and
            zone["y"] <= y <= zone["y"] + zone["h"])

def get_zone_at(x_mm, y_mm):
    for b in FOREST_BLOCKS:
        bx,by,bw,bh = b[1],b[2],b[3],b[4]
        if bx <= x_mm <= bx+bw and by <= y_mm <= by+bh:
            return {"name":f"Forest Block {b[0]}","x":bx,"y":by,"w":bw,"h":bh,"grid":"GRID_FOREST"}
    for z in OVERLAY_ZONES:
        if point_in_rect_mm(x_mm, y_mm, z): return z
    for z in BACKGROUND_ZONES:
        if point_in_rect_mm(x_mm, y_mm, z): return z
    return None

def get_grid_for_pos(x_mm, y_mm):
    z = get_zone_at(x_mm, y_mm)
    if z is None: return GRID_MC
    grid_map = {"GRID_MC":GRID_MC,"GRID_PATHWAY":GRID_PATHWAY,"GRID_FOREST":GRID_FOREST,"GRID_ARENA":GRID_ARENA,"GRID_RAMP":GRID_RAMP}
    return grid_map.get(z.get("grid","GRID_MC"), GRID_MC)

def get_forest_block_at(x_mm, y_mm):
    for b in FOREST_BLOCKS:
        bx,by,bw,bh = b[1],b[2],b[3],b[4]
        if bx <= x_mm <= bx+bw and by <= y_mm <= by+bh: return b
    return None

# =====================================================================
# ★ SERIAL MANAGER
# =====================================================================
class SerialManager:
    """Manages the USB serial connection to the Arduino Mega."""

    def __init__(self):
        self.port       = "COM12"  # e.g. "COM3" or "/dev/ttyUSB0"
        self.ser        = None   # serial.Serial object
        self.connected  = False

    # ── Port scanning ───────────────────────────────────────────────
    def available_ports(self):
        if not SERIAL_AVAILABLE:
            return []
        return [p.device for p in serial.tools.list_ports.comports()]

    # ── Connect / Disconnect ────────────────────────────────────────
    def connect(self, port):
        if not SERIAL_AVAILABLE:
            return False, "pyserial not installed"
        try:
            self.ser       = serial.Serial(port, SERIAL_BAUD, timeout=1)
            self.port      = port
            self.connected = True
            time.sleep(2)          # wait for Arduino reset after DTR
            return True, f"Connected to {port}"
        except Exception as e:
            self.connected = False
            return False, str(e)

    def disconnect(self):
        self.send_stop()
        if self.ser:
            try: self.ser.close()
            except: pass
        self.ser       = None
        self.connected = False

    # ── Packet sender ───────────────────────────────────────────────
    def send_packet(self, lx: int, ly: int, rx: int = 0):
        """Send  <LX,LY,RX>  packet to Arduino (same format as PS4 bridge)."""
        if not (self.ser and self.connected):
            return
        lx = max(-255, min(255, int(lx)))
        ly = max(-255, min(255, int(ly)))
        rx = max(-255, min(255, int(rx)))
        try:
            pkt = f"<{lx},{ly},{rx}>\n".encode()
            self.ser.write(pkt)
        except Exception as e:
            self.connected = False
            print(f"[Serial ERROR] {e}")

    def send_stop(self):
        self.send_packet(0, 0, 0)

    def ping(self):
        """Send PING, return True if PONG received within 1 s."""
        if not (self.ser and self.connected):
            return False
        try:
            self.ser.write(b"PING\n")
            deadline = time.time() + 1.0
            buf = b""
            while time.time() < deadline:
                if self.ser.in_waiting:
                    buf += self.ser.read(self.ser.in_waiting)
                    if b"PONG" in buf:
                        return True
            return False
        except:
            return False


# =====================================================================
# ★ PATH EXECUTOR  (state-machine — no blocking, no threads)
# =====================================================================
# ─────────────────────────────────────────────────────────────────────
# COORDINATE CONVENTION
# ─────────────────────────────────────────────────────────────────────
#   Map:      +X = right,  +Y = DOWN  (screen coords)
#   Robot:    LX +ve = strafe RIGHT
#             LY +ve = move FORWARD  (= map -Y direction)
#
# So to translate map vector (dx_map, dy_map) to joystick:
#     LX =  dx_map / dist  * DRIVE_SPEED   (right is right)
#     LY = -dy_map / dist  * DRIVE_SPEED   (down  is backward)
#
# This assumes the robot's FRONT faces map-UP (decreasing Y) when the
# run starts.  If your robot faces a different direction, rotate the
# field vectors accordingly using HEADING_OFFSET_DEG below.
# ─────────────────────────────────────────────────────────────────────
HEADING_OFFSET_DEG = 0   # 0 = robot faces map-UP.  90 = faces map-RIGHT, etc.

class PathExecutor:
    """
    Drives the real robot through path_cells one segment at a time.
    Call  start()  when RUN is pressed.
    Call  update(dt)  every game loop tick.
    """

    # States
    IDLE    = 0
    MOVING  = 1
    PAUSING = 2
    DONE    = 3

    def __init__(self, serial_mgr: SerialManager):
        self.sm           = serial_mgr
        self.state        = self.IDLE
        self.seg_idx      = 0        # current segment index
        self.seg_start_t  = 0.0
        self.seg_duration = 0.0
        self.seg_lx       = 0
        self.seg_ly       = 0
        self.pause_end_t  = 0.0

        # References set in start()
        self._path        = []
        self._start       = (0.0, 0.0)
        self.on_complete  = None     # callback()
        self.on_log       = None     # callback(str)

        # Live interpolated position for digital robot sync
        self.interp_x     = 0.0
        self.interp_y     = 0.0

    # ── Public API ──────────────────────────────────────────────────
    def start(self, start_pos, path_cells, on_complete=None, on_log=None):
        self._path       = path_cells
        self._start      = start_pos
        self.on_complete = on_complete
        self.on_log      = on_log
        self.seg_idx     = 0
        self.interp_x    = start_pos[0]
        self.interp_y    = start_pos[1]
        self.state       = self.MOVING
        self._begin_segment(0)

    def stop(self):
        self.sm.send_stop()
        self.state = self.IDLE

    def is_running(self):
        return self.state in (self.MOVING, self.PAUSING)

    # ── Per-frame update ────────────────────────────────────────────
    def update(self, dt):
        now = time.time()

        if self.state == self.IDLE or self.state == self.DONE:
            return

        elif self.state == self.PAUSING:
            if now >= self.pause_end_t:
                self.seg_idx += 1
                if self.seg_idx >= len(self._path):
                    self._finish()
                else:
                    self.state = self.MOVING
                    self._begin_segment(self.seg_idx)

        elif self.state == self.MOVING:
            elapsed  = now - self.seg_start_t
            progress = min(1.0, elapsed / max(self.seg_duration, 1e-6))

            # Interpolate digital robot
            sx, sy = self._seg_start_xy(self.seg_idx)
            tx, ty = self._path[self.seg_idx][0], self._path[self.seg_idx][1]
            self.interp_x = sx + (tx - sx) * progress
            self.interp_y = sy + (ty - sy) * progress

            if elapsed >= self.seg_duration:
                # Snap to target, send stop
                self.interp_x = tx
                self.interp_y = ty
                self.sm.send_stop()
                if self._log: self._log(f">> Reached cell {self.seg_idx+1}/{len(self._path)}")

                # Short pause between segments
                if INTER_SEGMENT_PAUSE_S > 0:
                    self.state      = self.PAUSING
                    self.pause_end_t = now + INTER_SEGMENT_PAUSE_S
                else:
                    self.seg_idx += 1
                    if self.seg_idx >= len(self._path):
                        self._finish()
                    else:
                        self._begin_segment(self.seg_idx)

    # ── Internal helpers ────────────────────────────────────────────
    def _log(self, msg):
        if self.on_log: self.on_log(msg)

    def _seg_start_xy(self, idx):
        if idx == 0:
            return self._start
        return (self._path[idx-1][0], self._path[idx-1][1])

    def _begin_segment(self, idx):
        sx, sy = self._seg_start_xy(idx)
        tx, ty = self._path[idx][0], self._path[idx][1]

        dx_map = tx - sx
        dy_map = ty - sy
        dist   = math.hypot(dx_map, dy_map)

        if dist < 10:
            # Zero-length segment — skip
            self.seg_idx += 1
            if self.seg_idx >= len(self._path):
                self._finish()
            else:
                self._begin_segment(self.seg_idx)
            return

        # ── Direction → joystick values ────────────────────────────
        # Rotate by heading offset (if robot not facing map-up)
        angle_rad = math.atan2(dy_map, dx_map)
        offset_rad = math.radians(HEADING_OFFSET_DEG)
        angle_rad -= offset_rad          # compensate robot orientation

        lx = math.cos(angle_rad) * DRIVE_SPEED   # strafe component
        ly = -math.sin(angle_rad) * DRIVE_SPEED  # forward component (flip Y)

        self.seg_lx       = int(round(lx))
        self.seg_ly       = int(round(ly))
        self.seg_duration = dist / PHYSICAL_SPEED_MM_S
        self.seg_start_t  = time.time()

        self._log(f"Seg {idx+1}: dist={dist:.0f}mm  LX={self.seg_lx}  LY={self.seg_ly}  t={self.seg_duration:.2f}s")
        self.sm.send_packet(self.seg_lx, self.seg_ly)

    def _finish(self):
        self.sm.send_stop()
        self.state = self.DONE
        self._log(">> Path complete — robot stopped")
        if self.on_complete: self.on_complete()


# =====================================================================
# INIT pygame + tkinter
# =====================================================================
pygame.init()

map_w_px = int(FIELD_W_MM * SCALE) + MAP_MARGIN * 2
map_h_px = int(FIELD_H_MM * SCALE) + MAP_MARGIN * 2
WIN_W    = PANEL_LEFT + map_w_px + PANEL_RIGHT
WIN_H    = max(map_h_px + 80, 720)

screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
pygame.display.set_caption("Robocon 2026 – R2 Digital Map + Real Robot Control")

font       = pygame.font.SysFont("consolas", 16)
font_small = pygame.font.SysFont("consolas", 13)
title_font = pygame.font.SysFont("consolas", 28, bold=True)
label_font = pygame.font.SysFont("consolas", 11)
block_font = pygame.font.SysFont("arial", 14, bold=True)

clock = pygame.time.Clock()

root = tk.Tk()
root.withdraw()

# =====================================================================
# STATE
# =====================================================================
mode         = 0
start_pos    = None
path_cells   = []
kfs_cells    = []
robot_x      = 0.0
robot_y      = 0.0
target_index = 0
logs         = []
pause_until  = 0
run_start_time = None
task_done    = False

# ── Serial & path executor ──────────────────────────────────────────
ser_mgr  = SerialManager()
executor = PathExecutor(ser_mgr)

selected_port = ""          # currently highlighted port in UI
port_list     = []          # refreshed port list

# =====================================================================
# BUTTONS  (original 5 + serial controls)
# =====================================================================
btn_start   = pygame.Rect(25, 140, 170, 40)
btn_path    = pygame.Rect(25, 190, 170, 40)
btn_run     = pygame.Rect(25, 240, 170, 40)
btn_kfs     = pygame.Rect(25, 290, 170, 40)
btn_reset   = pygame.Rect(25, 340, 170, 40)

# Serial panel buttons
btn_scan    = pygame.Rect(25, 410, 80, 30)
btn_connect = pygame.Rect(115, 410, 80, 30)
btn_ping    = pygame.Rect(25, 450, 80, 30)

# =====================================================================
# HELPERS
# =====================================================================
def log(t):
    logs.append(t)
    if len(logs) > 20: logs.pop(0)

def reset_all():
    global start_pos, path_cells, kfs_cells, robot_x, robot_y
    global target_index, logs, task_done, mode
    executor.stop()
    start_pos = None
    path_cells.clear()
    kfs_cells.clear()
    robot_x = robot_y = 0
    target_index = 0
    logs.clear()
    task_done = False
    mode = 0

def get_map_origin():
    return (PANEL_LEFT + MAP_MARGIN, 60)

def run_path():
    """Called when RUN button is pressed."""
    global mode, task_done, run_start_time, robot_x, robot_y, target_index

    if not start_pos:
        log("ERR: Set start position first")
        return
    if not path_cells:
        log("ERR: Select path cells first")
        return

    mode           = 3
    task_done      = False
    target_index   = 0
    run_start_time = time.time()
    robot_x, robot_y = start_pos

    def on_complete():
        global task_done, mode
        task_done = True
        mode      = 0
        elapsed   = time.time() - run_start_time
        messagebox.showinfo("Task Completed", f"Path done!\nTime: {elapsed:.2f} s")

    if ser_mgr.connected:
        log(f">> RUN started — REAL robot on {ser_mgr.port}")
        executor.start(start_pos, path_cells,
                       on_complete=on_complete,
                       on_log=log)
    else:
        log(">> RUN started — SIMULATION ONLY (not connected)")
        # Fall through to normal simulation mode
        executor.start(start_pos, path_cells,
                       on_complete=on_complete,
                       on_log=log)

# =====================================================================
# DRAWING  (unchanged from original + serial panel additions)
# =====================================================================
def draw_title():
    w   = screen.get_width()
    text = "Robocon 2026 – R2 Digital Map"
    main = title_font.render(text, True, (220,245,255))
    screen.blit(main, (w // 2 - main.get_width() // 2, 10))

def glow_button(rect, text, active, color):
    pygame.draw.rect(screen, color if active else (55,55,65), rect, border_radius=10)
    lbl = font.render(text, True, (255,255,255))
    screen.blit(lbl, (rect.x + rect.w//2 - lbl.get_width()//2,
                      rect.y + rect.h//2 - lbl.get_height()//2))

def draw_zone_rect(zone, ox, oy):
    px, py = mm2px(zone["x"], zone["y"], ox, oy)
    pw, ph = mm2size(zone["w"], zone["h"])
    pygame.draw.rect(screen, zone["color"], (px, py, pw, ph))
    pygame.draw.rect(screen, (0,0,0), (px, py, pw, ph), 1)
    if "name" in zone:
        lbl = label_font.render(zone["name"], True, (0,0,0))
        screen.blit(lbl, (px+4, py+3))

def draw_forest_block(block, ox, oy):
    num, bx, by, bw, bh, height = block
    color = FOREST_COLORS.get(height, (42,113,56))
    px, py = mm2px(bx, by, ox, oy)
    pw, ph = mm2size(bw, bh)
    pygame.draw.rect(screen, color, (px, py, pw, ph))
    pygame.draw.rect(screen, (0,0,0), (px, py, pw, ph), 1)
    num_lbl = block_font.render(str(num), True, (255,255,255))
    screen.blit(num_lbl, (px+pw//2-num_lbl.get_width()//2, py+ph//2-num_lbl.get_height()//2))
    h_lbl = font_small.render(f"{height}mm", True, (220,220,220))
    screen.blit(h_lbl, (px+3, py+ph-h_lbl.get_height()-2))

def draw_grid_for_zone(zone, ox, oy, grid_mm, grid_color=(0,0,0,40)):
    zx,zy,zw,zh = zone["x"],zone["y"],zone["w"],zone["h"]
    px0, py0 = mm2px(zx, zy, ox, oy)
    pw, ph   = mm2size(zw, zh)
    step_px  = max(1, int(grid_mm * SCALE))
    if step_px < 4: return
    s = pygame.Surface((pw, ph), pygame.SRCALPHA)
    x = 0
    while x <= pw:
        pygame.draw.line(s, grid_color, (x,0), (x,ph), 1); x += step_px
    y = 0
    while y <= ph:
        pygame.draw.line(s, grid_color, (0,y), (pw,y), 1); y += step_px
    screen.blit(s, (px0, py0))

def draw_map(ox, oy):
    fw, fh = mm2size(FIELD_W_MM, FIELD_H_MM)
    pygame.draw.rect(screen, (240,240,240), (ox,oy,fw,fh))
    pygame.draw.rect(screen, (130,130,130), (ox,oy,fw,fh), 2)
    for z in BACKGROUND_ZONES:
        draw_zone_rect(z, ox, oy)
        g = z.get("grid")
        if g:
            gm = {"GRID_MC":GRID_MC,"GRID_PATHWAY":GRID_PATHWAY,"GRID_ARENA":GRID_ARENA}
            draw_grid_for_zone(z, ox, oy, gm.get(g, GRID_MC))
    for b in FOREST_BLOCKS:
        draw_forest_block(b, ox, oy)
        fz = {"x":b[1],"y":b[2],"w":b[3],"h":b[4]}
        draw_grid_for_zone(fz, ox, oy, GRID_FOREST, (0,0,0,50))
    for z in OVERLAY_ZONES:
        draw_zone_rect(z, ox, oy)
        g = z.get("grid")
        if g:
            draw_grid_for_zone(z, ox, oy, {"GRID_RAMP":GRID_RAMP}.get(g,GRID_MC))
    sections = [("MARTIAL CLUB", ZONE1),
                ("MEIHUA FOREST", {"x":1225,"y":3250,"w":3600,"h":4800}),
                ("ARENA", ZONE3)]
    for name, z in sections:
        px, py = mm2px(z["x"], z["y"], ox, oy)
        pw, ph = mm2size(z["w"], z["h"])
        sec_lbl = font.render(name, True, (0,0,0))
        lbl_surf = pygame.Surface((sec_lbl.get_width(), sec_lbl.get_height()), pygame.SRCALPHA)
        lbl_surf.blit(sec_lbl, (0,0))
        lbl_surf.set_alpha(60)
        screen.blit(lbl_surf, (px+pw//2-sec_lbl.get_width()//2, py+ph//2-sec_lbl.get_height()//2))

def draw_path_overlay(ox, oy):
    for i, (cx, cy, g) in enumerate(path_cells):
        cell_x, cell_y = cx - g/2, cy - g/2
        px, py = mm2px(cell_x, cell_y, ox, oy)
        pw, ph = mm2size(g, g)
        s = pygame.Surface((pw, ph), pygame.SRCALPHA)
        s.fill((255,210,0,100))
        screen.blit(s, (px, py))
        pygame.draw.rect(screen, (255,180,0), (px,py,pw,ph), 2)
        n = font_small.render(str(i+1), True, (255,255,255))
        screen.blit(n, (px+pw//2-n.get_width()//2, py+ph//2-n.get_height()//2))
        if i > 0:
            pcx, pcy, _ = path_cells[i-1]
            ppx,ppy = mm2px(pcx,pcy,ox,oy)
            cpx,cpy = mm2px(cx,cy,ox,oy)
            pygame.draw.line(screen, (255,210,0), (ppx,ppy), (cpx,cpy), 1)

def draw_kfs_overlay(ox, oy):
    for bnum, kx, ky in kfs_cells:
        px, py = mm2px(kx, ky, ox, oy)
        half = max(2, int(350 * SCALE / 2))
        r = pygame.Rect(px-half, py-half, half*2, half*2)
        s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        s.fill((0,255,255,150))
        screen.blit(s, r.topleft)
        pygame.draw.rect(screen, (0,200,200), r, 2)
        lbl = font_small.render("KFS", True, (0,60,60))
        screen.blit(lbl, (px-lbl.get_width()//2, py-lbl.get_height()//2))

def draw_robot(ox, oy):
    if start_pos is None: return
    px, py = mm2px(robot_x, robot_y, ox, oy)
    size   = max(6, int(R2_SIZE_MM * SCALE / 2))
    hb     = int(R2_SIZE_MM * SCALE)
    hitbox_rect = pygame.Rect(px-hb//2, py-hb//2, hb, hb)
    s = pygame.Surface((hb, hb), pygame.SRCALPHA)
    s.fill((255,255,255,25))
    screen.blit(s, hitbox_rect.topleft)
    pygame.draw.rect(screen, (255,255,255,80), hitbox_rect, 1)
    if target_index < len(path_cells):
        tx, ty = path_cells[target_index][0], path_cells[target_index][1]
        heading = math.atan2(ty - robot_y, tx - robot_x)
    else:
        heading = -math.pi / 2
    pts = [
        (px + size*math.cos(heading),       py + size*math.sin(heading)),
        (px + size*math.cos(heading+2.5),   py + size*math.sin(heading+2.5)),
        (px + size*math.cos(heading-2.5),   py + size*math.sin(heading-2.5)),
    ]
    pygame.draw.polygon(screen, (0,200,255), pts)
    pygame.draw.polygon(screen, (255,255,255), pts, 1)

def draw_terminal():
    w, h     = screen.get_size()
    panel_x  = w - PANEL_RIGHT + 10
    panel    = pygame.Rect(panel_x, 60, PANEL_RIGHT-20, h-70)
    pygame.draw.rect(screen, (18,20,28), panel, border_radius=12)
    hdr = font.render("TERMINAL", True, (0,200,160))
    screen.blit(hdr, (panel_x+12, 72))
    y = 100
    for t in logs[-18:]:
        line = font_small.render(t, True, (0,220,150))
        screen.blit(line, (panel_x+12, y))
        y += 18
        if y > panel.bottom - 10: break
    info_y = panel.bottom - 100
    pygame.draw.line(screen, (40,50,40), (panel_x+10, info_y), (panel_x+PANEL_RIGHT-40, info_y), 1)
    info_y += 8
    conn_str = f"Serial: {ser_mgr.port}" if ser_mgr.connected else "Serial: --"
    conn_col = (0,255,120) if ser_mgr.connected else (200,80,80)
    for line in [
        (f"Robot: ({robot_x:.0f},{robot_y:.0f})mm", (0,180,140)),
        (f"Speed: {PHYSICAL_SPEED_MM_S}mm/s", (0,180,140)),
        (f"Cells: {len(path_cells)}  KFS: {len(kfs_cells)}/{MAX_KFS}", (0,180,140)),
        (conn_str, conn_col),
    ]:
        txt = font_small.render(line[0], True, line[1])
        screen.blit(txt, (panel_x+12, info_y))
        info_y += 16

def draw_mode_indicator():
    mode_names = {0:("IDLE",(120,120,130)), 1:("SET START",(0,200,255)),
                  2:("SELECT PATH",(255,180,0)), 3:("RUNNING",(0,255,140)),
                  4:("PLACE KFS",(0,255,255))}
    name, color = mode_names.get(mode, ("IDLE",(120,120,130)))
    lbl = font.render(f"Mode: {name}", True, color)
    screen.blit(lbl, (25, 110))

def draw_legend():
    y = 510
    lbl = font_small.render("Forest Heights:", True, (180,180,190))
    screen.blit(lbl, (25, y)); y += 18
    for h_mm, color in sorted(FOREST_COLORS.items()):
        pygame.draw.rect(screen, color, (25, y, 18, 14))
        pygame.draw.rect(screen, (200,200,200), (25, y, 18, 14), 1)
        txt = font_small.render(f" {h_mm}mm", True, (180,180,190))
        screen.blit(txt, (46, y)); y += 18
    y += 6
    lbl = font_small.render("Grid (mm):", True, (180,180,190))
    screen.blit(lbl, (25, y)); y += 16
    for name, val in [("MC",GRID_MC),("Path",GRID_PATHWAY),("Forest",GRID_FOREST)]:
        txt = font_small.render(f" {name}: {val}", True, (150,150,160))
        screen.blit(txt, (25, y)); y += 14

def draw_serial_panel():
    """Draw serial connection UI on left panel."""
    # ── Section header ──
    y = 393
    pygame.draw.line(screen, (60,60,80), (15, y), (205, y), 1)
    y += 6
    hdr = font_small.render("── SERIAL / ROBOT ──", True, (100,180,255))
    screen.blit(hdr, (25, y))
    y += 18

    # ── Connection status dot + text ──
    dot_color = (0,255,80) if ser_mgr.connected else (255,60,60)
    pygame.draw.circle(screen, dot_color, (35, y+6), 6)
    status = ser_mgr.port if ser_mgr.connected else "not connected"
    st_txt = font_small.render(status, True, dot_color)
    screen.blit(st_txt, (46, y))
    y += 20

    # ── Selected port label ──
    port_disp = selected_port if selected_port else "(no port)"
    pt_txt = font_small.render(f"Port: {port_disp}", True, (200,200,210))
    screen.blit(pt_txt, (25, y))
    y += 16

    # ── Buttons: Scan  Connect/Disconnect ──
    scan_r    = pygame.Rect(25, y, 80, 26)
    connect_r = pygame.Rect(115, y, 80, 26)
    ping_r    = pygame.Rect(25, y+32, 80, 26)

    # Update global rects so event handler can use them
    btn_scan.x, btn_scan.y, btn_scan.width, btn_scan.height = scan_r
    btn_connect.x, btn_connect.y, btn_connect.width, btn_connect.height = connect_r
    btn_ping.x, btn_ping.y, btn_ping.width, btn_ping.height = ping_r

    scan_c    = (60,100,180)
    conn_c    = (255,60,60) if ser_mgr.connected else (0,180,80)
    conn_txt  = "Disconnect" if ser_mgr.connected else "Connect"
    ping_c    = (80,80,200)

    for r, txt, c in [(scan_r,"Scan",scan_c),(connect_r,conn_txt,conn_c),(ping_r,"PING",ping_c)]:
        pygame.draw.rect(screen, c, r, border_radius=8)
        t = font_small.render(txt, True, (255,255,255))
        screen.blit(t, (r.x+r.w//2-t.get_width()//2, r.y+r.h//2-t.get_height()//2))

    y += 64

    # ── Port list (small buttons) ──
    if port_list:
        pl_lbl = font_small.render("Available:", True, (160,160,180))
        screen.blit(pl_lbl, (25, y)); y += 14
        for p in port_list[:4]:
            r = pygame.Rect(25, y, 170, 20)
            col = (0,100,180) if p == selected_port else (40,40,60)
            pygame.draw.rect(screen, col, r, border_radius=5)
            t = font_small.render(p, True, (200,230,255))
            screen.blit(t, (r.x+6, r.y+3))
            y += 23
    else:
        no_t = font_small.render("(press Scan)", True, (100,100,120))
        screen.blit(no_t, (25, y))
        y += 20

    # ── Physical speed reminder ──
    spd_t = font_small.render(f"Phy spd: {PHYSICAL_SPEED_MM_S}mm/s", True, (120,120,140))
    screen.blit(spd_t, (25, y+4))

def draw_mouse_info(ox, oy):
    mx, my = pygame.mouse.get_pos()
    x_mm, y_mm = px2mm(mx, my, ox, oy)
    if 0 <= x_mm <= FIELD_W_MM and 0 <= y_mm <= FIELD_H_MM:
        zone = get_zone_at(x_mm, y_mm)
        zone_name = zone["name"] if zone else "Outside"
        info = f"({x_mm:.0f},{y_mm:.0f})mm  [{zone_name}]"
        txt  = font_small.render(info, True, (200,200,210))
        screen.blit(txt, (PANEL_LEFT+10, screen.get_height()-22))

# =====================================================================
# ROBOT MOTION  (digital simulation, synced with PathExecutor)
# =====================================================================
def move_robot_sim(dt, ox, oy):
    """
    In simulation mode (no serial) or as fallback, use PathExecutor's
    interpolated position for the digital robot.  Also handles KFS collection.
    """
    global robot_x, robot_y, target_index, task_done, mode

    if task_done or not executor.is_running():
        return

    # Sync digital robot to executor interpolation
    robot_x = executor.interp_x
    robot_y = executor.interp_y
    target_index = executor.seg_idx

    # KFS collection check
    for kfs in kfs_cells[:]:
        kx, ky = kfs[1], kfs[2]
        if math.hypot(robot_x - kx, robot_y - ky) < 200:
            log(f">> KFS collected (Block {kfs[0]})")
            kfs_cells.remove(kfs)

# =====================================================================
# MAIN LOOP
# =====================================================================
running = True
while running:
    dt   = clock.tick(60) / 1000.0
    w, h = screen.get_size()
    ox, oy = get_map_origin()

    # ── Recalculate port-button rects for current frame ──
    port_btn_rects = {}
    if port_list:
        py_base = 530
        for i, p in enumerate(port_list[:4]):
            port_btn_rects[p] = pygame.Rect(25, py_base + i*23, 170, 20)

    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False

        elif e.type == pygame.MOUSEBUTTONDOWN:
            mx, my = e.pos

            # ── Original control buttons ──
            if btn_start.collidepoint(e.pos):
                mode = 1; log("Mode: SET START — click on map")

            elif btn_path.collidepoint(e.pos):
                mode = 2; log("Mode: SELECT PATH — click waypoints")

            elif btn_run.collidepoint(e.pos):
                run_path()

            elif btn_kfs.collidepoint(e.pos):
                mode = 4; log("Mode: PLACE KFS — click forest blocks")

            elif btn_reset.collidepoint(e.pos):
                reset_all(); log(">> RESET complete")

            # ── Serial panel buttons ──
            elif btn_scan.collidepoint(e.pos):
                port_list = ser_mgr.available_ports()
                if port_list:
                    log(f"Ports: {', '.join(port_list)}")
                    if not selected_port:
                        selected_port = port_list[0]
                else:
                    log("No serial ports found")

            elif btn_connect.collidepoint(e.pos):
                if ser_mgr.connected:
                    ser_mgr.disconnect()
                    log(">> Serial disconnected")
                else:
                    if not selected_port:
                        # Ask via tkinter if no port selected
                        p = simpledialog.askstring("Port", "Enter COM port (e.g. COM3 or /dev/ttyUSB0):")
                        if p: selected_port = p.strip()
                    if selected_port:
                        ok, msg = ser_mgr.connect(selected_port)
                        log(f"{'>> ' if ok else 'ERR: '}{msg}")

            elif btn_ping.collidepoint(e.pos):
                if ser_mgr.connected:
                    ok = ser_mgr.ping()
                    log(f"PING → {'PONG ✓' if ok else 'no response'}")
                else:
                    log("ERR: not connected")

            # ── Port list click ──
            else:
                port_clicked = False
                for p, r in port_btn_rects.items():
                    if r.collidepoint(e.pos):
                        selected_port = p
                        log(f"Port selected: {p}")
                        port_clicked = True
                        break

                # ── Map clicks ──
                if not port_clicked:
                    x_mm, y_mm = px2mm(e.pos[0], e.pos[1], ox, oy)
                    if 0 <= x_mm <= FIELD_W_MM and 0 <= y_mm <= FIELD_H_MM:
                        ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL
                        grid = get_grid_for_pos(x_mm, y_mm)
                        sx, sy = snap_to_grid(x_mm, y_mm, grid)

                        if mode == 1:
                            start_pos = (sx, sy)
                            robot_x, robot_y = sx, sy
                            zone = get_zone_at(x_mm, y_mm)
                            zn   = zone["name"] if zone else "field"
                            log(f"Start: ({sx:.0f},{sy:.0f}) [{zn}]")

                        elif mode == 2:
                            cell = (sx, sy, grid)
                            existing = [c for c in path_cells if c[0]==sx and c[1]==sy]
                            if ctrl or existing:
                                if existing:
                                    path_cells.remove(existing[0])
                                    log(f"Removed cell ({sx:.0f},{sy:.0f})")
                            else:
                                path_cells.append(cell)
                                log(f"Cell #{len(path_cells)}: ({sx:.0f},{sy:.0f})")

                        elif mode == 4:
                            fb = get_forest_block_at(x_mm, y_mm)
                            if fb:
                                bnum = fb[0]
                                cx_b = fb[1] + fb[3]/2
                                cy_b = fb[2] + fb[4]/2
                                existing = [k for k in kfs_cells if k[0]==bnum]
                                if ctrl:
                                    if existing: kfs_cells.remove(existing[0]); log(f"Removed KFS Block {bnum}")
                                else:
                                    if not existing and len(kfs_cells) < MAX_KFS:
                                        kfs_cells.append((bnum, cx_b, cy_b))
                                        log(f"KFS placed on Block {bnum}")
                                    elif existing: log(f"Block {bnum} already has KFS")
                                    else: log(f"Max KFS ({MAX_KFS}) reached")
                            else:
                                log("Click inside a forest block")

    # ── UPDATE ──
    if mode == 3:
        executor.update(dt)
        move_robot_sim(dt, ox, oy)
        if not executor.is_running() and not task_done:
            pass  # on_complete callback handles task_done

    # ── DRAW ──
    screen.fill((14,16,22))
    draw_title()
    draw_map(ox, oy)
    draw_path_overlay(ox, oy)
    draw_kfs_overlay(ox, oy)
    draw_robot(ox, oy)

    glow_button(btn_start, "Set Start",   mode==1, (0,200,255))
    glow_button(btn_path,  "Select Path", mode==2, (255,180,0))
    glow_button(btn_run,   "RUN",         mode==3, (0,255,140))
    glow_button(btn_kfs,   "Place KFS",   mode==4, (0,255,255))
    glow_button(btn_reset, "RESET",       False,   (255,60,60))

    draw_mode_indicator()
    draw_serial_panel()
    draw_legend()
    draw_terminal()
    draw_mouse_info(ox, oy)

    pygame.display.flip()

# ── Clean exit ──
ser_mgr.disconnect()
pygame.quit()
sys.exit()
