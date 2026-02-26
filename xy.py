import cv2
import numpy as np
import os
import sys
import serial
import time
import pygame

# ===================================================================
#  CONFIGURATION & TUNING
# ===================================================================
TEMPLATE_DIR    = r"D:\OneDrive\Desktop\robocon\templates\templates"
SCORE_THRESHOLD = 5.0         # Threshold for symbol detection (Lower diff = Higher Score)

# Detection parameters
MIN_AREA        = 3000
MAX_AREA        = 250000
WINDOW_NAME     = "Integrated Robocon System (Manual Control)"

# Robot Movement Tuning
BAUD_RATE       = 115200
MAX_SPEED       = 180         # Max PWM value (matches Arduino MAX_SPEED)

# Autonomous Sequence Timing
STOP_DURATION   = 2.0         # Stop for 2 seconds
MOVE_DISTANCE_T = 1.5         # Calibration: Seconds needed to move 20cm
COOLDOWN_T      = 3.0         # Seconds to ignore detection after a match

# --- States ---
STATE_MANUAL     = "MANUAL_CONTROL"  # Direct PS4 Control
STATE_AUTO_STOP  = "AUTO_STOPPING"    # Detected! Sequence Priority
STATE_AUTO_MOVE  = "AUTO_MOVING"      # Moving 20cm autonomously
STATE_COOLDOWN   = "COOLDOWN_WAIT"    # Safe period after move

# ===================================================================
#  PREPROCESSING & DETECTION FUNCTIONS
# ===================================================================

def preprocess(img):
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    binary  = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=21, C=8
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    return binary

def extract_main_contour(binary):
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours if MIN_AREA < cv2.contourArea(c) < MAX_AREA]
    return max(valid, key=cv2.contourArea) if valid else None

def get_match_score(cnt1, cnt2):
    diff = cv2.matchShapes(cnt1, cnt2, cv2.CONTOURS_MATCH_I1, 0)
    return 1.0 / (diff + 1e-6)

# ===================================================================
#  STARTUP & PORT SELECTION
# ===================================================================

print("==================================================")
print("   ROBOCON MANUAL CONTROL SYSTEM v3.2")
print("==================================================")

# Ask for COM Port
com_input = input("Enter Arduino COM Port Number (e.g., 3): ").strip()
SERIAL_PORT = f"COM{com_input}"

# Setup Serial
ser = None
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    print(f"[SERIAL] Connected to {SERIAL_PORT}")
except Exception as e:
    print(f"[SERIAL ERROR] Simulation Mode: {e}")

# Setup Controller
pygame.init()
pygame.joystick.init()
controller = None
if pygame.joystick.get_count() > 0:
    controller = pygame.joystick.Joystick(0)
    controller.init()
    print(f"[INPUT] Controller: {controller.get_name()}")
else:
    print("[INPUT WARNING] No controller detected. Please connect PS4 controller.")

# Load Templates
reference_data = []
print(f"Loading templates from: {TEMPLATE_DIR}")
for i in range(1, 16):
    path = os.path.join(TEMPLATE_DIR, f"template_{i}.png")
    if not os.path.exists(path): continue
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None: continue
    binary = preprocess(img)
    contour = extract_main_contour(binary)
    if contour is not None:
        reference_data.append((i, contour))

if len(reference_data) < 15:
    print(f"Loaded {len(reference_data)}/15 symbol templates.")

# Setup Camera
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# ===================================================================
#  MAIN LOOP & STATE MACHINE
# ===================================================================

current_state = STATE_MANUAL
state_timer = 0
prev_packet = ""

def send_robot_packet(lx, ly, rx):
    global prev_packet
    packet = f"<{lx},{ly},{rx}>"
    if packet != prev_packet:
        if ser:
            try:
                ser.write(f"{packet}\n".encode('ascii'))
            except:
                pass
        prev_packet = packet

print("\n--- SYSTEM LIVE ---")
print("MANUAL CONTROL ACTIVE: Use PS4 sticks to drive.")
print("AUTOMATIC OVERRIDE: Symbol Detection stays active.")

while True:
    ret, frame = cap.read()
    if not ret: break

    # PS4 Inputs
    pygame.event.pump()
    mlx, mly, mrx = 0, 0, 0
    if controller:
        mlx = int(controller.get_axis(0) * MAX_SPEED)    # Strafe
        mly = int(-controller.get_axis(1) * MAX_SPEED)   # Forward/Backward
        mrx = int(controller.get_axis(2) * MAX_SPEED)    # Rotate

    # CV Detection
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    binary_frame = preprocess(gray)
    contours, _ = cv2.findContours(binary_frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    best_score, best_id, best_cnt = 0, -1, None
    for cnt in contours:
        if not (MIN_AREA < cv2.contourArea(cnt) < MAX_AREA): continue
        for tid, t_cnt in reference_data:
            score = get_match_score(cnt, t_cnt)
            if score > best_score:
                best_score, best_id, best_cnt = score, tid, cnt

    # State Machine Logic
    now = time.time()
    
    if current_state == STATE_MANUAL:
        if best_score >= SCORE_THRESHOLD:
            print(f"\n[AUTO TRIGGER] Symbol {best_id} Detected. Interrupting PS4 Control.")
            current_state, state_timer = STATE_AUTO_STOP, now
            send_robot_packet(0, 0, 0) # Hard Stop
        else:
            # DIRECT MANUAL CONTROL
            send_robot_packet(mlx, mly, mrx)

    elif current_state == STATE_AUTO_STOP:
        send_robot_packet(0, 0, 0)
        if now - state_timer >= STOP_DURATION:
            print("[AUTO] Wait complete. Executing 20cm forward move.")
            current_state, state_timer = STATE_AUTO_MOVE, now
            send_robot_packet(0, 120, 0) # Forward move at constant speed

    elif current_state == STATE_AUTO_MOVE:
        send_robot_packet(0, 120, 0)
        if now - state_timer >= MOVE_DISTANCE_T:
            print("[AUTO] Sequence finished. Cooling down detection.")
            current_state, state_timer = STATE_COOLDOWN, now
            send_robot_packet(0, 0, 0)

    elif current_state == STATE_COOLDOWN:
        # Return to manual control, but wait before scanning again
        send_robot_packet(mlx, mly, mrx)
        if now - state_timer >= COOLDOWN_T:
            print("[SYSTEM] Detection re-enabled.")
            current_state = STATE_MANUAL

    # UI Visuals
    display = frame.copy()
    cv2.rectangle(display, (0,0), (1280, 45), (30,30,30), -1)
    status_color = (0, 255, 0) if current_state == STATE_MANUAL else (0, 165, 255)
    cv2.putText(display, f"STATE: {current_state} | Best Match: {best_score:.2f}", (20, 32), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)
    
    if best_cnt is not None:
        cv2.drawContours(display, [best_cnt], -1, (0,0,255), 3)

    cv2.imshow(WINDOW_NAME, display)
    if cv2.waitKey(1) & 0xFF == ord('q'): break

if ser: send_robot_packet(0,0,0); ser.close()
cap.release(); cv2.destroyAllWindows(); pygame.quit()
print("\nSystem Exited.")
