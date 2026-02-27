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
SCORE_THRESHOLD = 5.0         # Set to 5.0 as per user requirement

# Detection parameters
MIN_AREA        = 3000
MAX_AREA        = 250000
WINDOW_NAME     = "Integrated Robocon System (Manual Control)"

# Robot Movement Tuning
BAUD_RATE       = 115200
MAX_SPEED       = 180         # Max PWM value (matches Arduino MAX_SPEED)

# Autonomous Sequence Timing
STOP_DURATION   = 2.0         # Stop for 2 seconds (Updated as requested)
COOLDOWN_T      = 3.0         # Seconds to ignore detection after match



# --- States ---
STATE_MANUAL     = "MANUAL_CONTROL"  # Direct PS4 Control
STATE_AUTO_STOP  = "AUTO_STOPPING"    # Detected! Sequence Priority


# ===================================================================
#  PREPROCESSING & DETECTION FUNCTIONS
# ===================================================================

def preprocess(img):
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    
    # 1. Contrast Enhancement (Simple CLAHE or Normalization)
    # Using simple normalization for speed and robustness
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    
    # 2. Noise Reduction (Bilateral is better at preserving edges than Median for shapes)
    blurred = cv2.bilateralFilter(gray, 9, 75, 75)
    
    # 3. Adaptive Thresholding
    # Increased blockSize and reduced C to be more sensitive
    binary  = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=31, C=5
    )
    
    # 4. Clean up (Small dilation to close gaps in symbol outlines)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    binary = cv2.dilate(binary, kernel, iterations=1)
    return binary

def generate_variants(img_binary):
    """Generates 4 tilted versions of the input binary image to handle perspective."""
    h, w = img_binary.shape
    variants = [img_binary]
    
    # Define source points (corners)
    src = np.float32([[0, 0], [w, 0], [0, h], [w, h]])
    
    # Perspective tilt variations (approx 15 degrees)
    tilt_px = int(w * 0.15)
    
    configs = [
        [[tilt_px, 0], [w-tilt_px, 0], [0, h], [w, h]], # Tilt Up
        [[0, 0], [w, 0], [tilt_px, h], [w-tilt_px, h]], # Tilt Down
        [[0, tilt_px], [w, 0], [0, h-tilt_px], [w, h]], # Tilt Left
        [[0, 0], [w, tilt_px], [0, h], [w, h-tilt_px]], # Tilt Right
    ]
    
    for config in configs:
        dst = np.float32(config)
        matrix = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(img_binary, matrix, (w, h))
        variants.append(warped)
        
    return variants

def extract_main_contour(binary):
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours if MIN_AREA < cv2.contourArea(c) < MAX_AREA]
    return max(valid, key=cv2.contourArea) if valid else None

def get_match_score(cnt1, cnt2):
    # Filter 1: Aspect Ratio Similarity
    x1, y1, w1, h1 = cv2.boundingRect(cnt1)
    x2, y2, w2, h2 = cv2.boundingRect(cnt2)
    ar1 = float(w1) / h1
    ar2 = float(w2) / h2
    
    # Filter 1: Aspect Ratio Similarity (Loosened to 40% for warped views)
    if abs(ar1 - ar2) / max(ar1, ar2) > 0.40:
        return 0.0

    # Filter 2: Circularity Comparison (Loosened to 0.5 for warped views)
    area1 = cv2.contourArea(cnt1)
    peri1 = cv2.arcLength(cnt1, True)
    circ1 = (4 * np.pi * area1) / (peri1**2 + 1e-6)
    
    area2 = cv2.contourArea(cnt2)
    peri2 = cv2.arcLength(cnt2, True)
    circ2 = (4 * np.pi * area2) / (peri2**2 + 1e-6)
    
    if abs(circ1 - circ2) > 0.5:
        return 0.0

    # Filter 3: Hu Moments
    diff = cv2.matchShapes(cnt1, cnt2, cv2.CONTOURS_MATCH_I1, 0)
    return 1.0 / (diff + 1e-6)


# ===================================================================
#  STARTUP & PORT SELECTION
# ===================================================================

print("==================================================")
print("   ROBOCON MANUAL CONTROL SYSTEM v4.0 (Enhanced)")
print("==================================================")

# Ask for COM Port
com_input = input("Enter Arduino COM Port Number (e.g., 3): ").strip()
SERIAL_PORT = f"COM{com_input}"

# Setup Serial
ser = None
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    ser.setDTR(False) # Prevent Reset on connect
    time.sleep(1)
    ser.setDTR(True)
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

# Load Templates with Synthetic Perspective Variations
reference_data = []
print(f"Loading templates with angle augmentation from: {TEMPLATE_DIR}")
for i in range(1, 16):
    path = os.path.join(TEMPLATE_DIR, f"template_{i}.png")
    if not os.path.exists(path): continue
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None: continue
    
    # Preprocess and extract variations
    binary = preprocess(img)
    warped_versions = generate_variants(binary)
    
    for warp in warped_versions:
        contour = extract_main_contour(warp)
        if contour is not None:
            reference_data.append((i, contour))

print(f"System Ready: {len(reference_data)} perspective variations loaded for 15 symbols.")

# Setup Camera
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 30)

# ===================================================================
#  MAIN LOOP & STATE MACHINE
# ===================================================================

current_state = STATE_MANUAL
state_timer = 0
prev_packet = ""
detection_history = [] # Buffer for temporal consensus

def send_robot_packet(lx, ly, rx):
    global prev_packet
    packet = f"<{lx},{ly},{rx}>"
    if packet != prev_packet:
        # Show telemetry in terminal
        print(f"[PACKET] {packet}")
        
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
    
    current_best_id = -1
    best_score, best_cnt = 0, None
    
    for cnt in contours:
        if not (MIN_AREA < cv2.contourArea(cnt) < MAX_AREA): continue
        for tid, t_cnt in reference_data:
            score = get_match_score(cnt, t_cnt)
            if score > best_score:
                best_score, best_cnt = score, cnt
                current_best_id = tid


    # 1. Temporal Filtering: Consensus over 5 frames
    detection_history.append(current_best_id if best_score >= SCORE_THRESHOLD else -1)
    if len(detection_history) > 5:
        detection_history.pop(0)
    
    # A detection is valid only if it appears in 3 out of last 5 frames
    consensus_id = -1
    if len(detection_history) >= 3:
        # Count occurrences of non -1 IDs
        valid_ids = [i for i in detection_history if i != -1]
        if valid_ids:
            most_freq = max(set(valid_ids), key=valid_ids.count)
            if detection_history.count(most_freq) >= 3:
                 consensus_id = most_freq

    # State Machine Logic
    now = time.time()
    
    if current_state == STATE_MANUAL:
        if consensus_id != -1: # Use consensus ID instead of single-frame detection
            print(f"\n[AUTO TRIGGER] Symbol {consensus_id} Verified. Interrupting PS4 Control.")
            current_state, state_timer = STATE_AUTO_STOP, now
            detection_history.clear() # Clear history so next scan starts fresh
            send_robot_packet(0, 0, 0) # Hard Stop
        else:
            # DIRECT MANUAL CONTROL
            send_robot_packet(mlx, mly, mrx)


    elif current_state == STATE_AUTO_STOP:
        send_robot_packet(0, 0, 0)
        if now - state_timer >= STOP_DURATION:
            print("[AUTO] Sequence finished. Returning to Manual Control.")
            current_state, state_timer = STATE_MANUAL, now

    # UI Visuals
    display = frame.copy()
    cv2.rectangle(display, (0,0), (1280, 45), (30,30,30), -1)
    
    # Check if we are in "Software Cooldown" (ignore detection for COOLDOWN_T seconds)
    if current_state == STATE_MANUAL and (now - state_timer < COOLDOWN_T):
        status_text = f"STATE: {current_state} (COOLDOWN)"
        status_color = (0, 165, 255)
        consensus_id = -1 # Disable triggers during cooldown
    else:
        status_text = f"STATE: {current_state} | Best Match: {best_score:.2f}"
        status_color = (0, 255, 0) if current_state == STATE_MANUAL else (0, 165, 255)

    cv2.putText(display, status_text, (20, 32), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)

    
    if best_cnt is not None:
        cv2.drawContours(display, [best_cnt], -1, (0,0,255), 3)

    cv2.imshow(WINDOW_NAME, display)
    cv2.imshow("Binary View (Debug)", binary_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'): break

if ser: send_robot_packet(0,0,0); ser.close()
cap.release(); cv2.destroyAllWindows(); pygame.quit()
print("\nSystem Exited.")
