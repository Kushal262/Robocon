import os
os.environ["SDL_VIDEODRIVER"] = "dummy"  # No window needed

import pygame
import serial
import time
import cv2
import threading
import socket
from flask import Flask, Response

# ================================================================
# ===== TUNABLE PARAMETERS — EDIT HERE ONLY =====================
# ================================================================

SERIAL_PORT    = "/dev/ttyACM0"  # Serial port for Arduino
BAUD_RATE      = 115200          # Serial baud rate

MAX_PWM        = 150             # Drive motor max speed forward/backward (0-255)
STRAFE_PWM     = 100             # Drive motor max speed when strafing (0-255)
ROTATION_PWM   = 100             # Drive motor max speed when rotating (0-255)
MAX_LIFT_PWM   = 100             # Lift motor max speed (0-255)
DEAD_ZONE      = 0.1             # Stick deadzone (0.0-1.0) — increase if drift
RAMP_STEP      = 100             # Motor acceleration step — lower = smoother

CAMERA_INDEX   = 0               # 0 = first webcam, 1 = second webcam
STREAM_PORT    = 5000            # port to serve the camera stream
FRAME_WIDTH    = 640             # camera resolution width — reduced for less lag
FRAME_HEIGHT   = 480             # camera resolution height — reduced for less lag
FRAME_RATE     = 15              # frames per second — reduced for less lag
JPEG_QUALITY   = 70              # JPEG quality (0-100) — lower = less bandwidth

# ================================================================

# ===== SERIAL INIT =====
ser = serial.Serial(SERIAL_PORT, BAUD_RATE)
time.sleep(2)

# ===== TOGGLE MEMORY =====
prev_cross     = False
prev_square    = False
prev_triangle  = False
prev_circle    = False
prev_dpad_left = False

# ===== TOGGLE STATES =====
pneumaticOn = False
backUp      = False

# ===== RAMP VARIABLES =====
current_LF   = 0
current_RF   = 0
current_LB   = 0
current_RB   = 0
current_LIFT = 0

# ===== KILL SWITCH =====
motors_enabled = False

# ===== SMART PRINT =====
prev_data = ""

# ===== CAMERA =====
cap = cv2.VideoCapture(CAMERA_INDEX)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_FPS,          FRAME_RATE)

# ===== FLASK APP =====
app = Flask(__name__)

def ramp(current, target, step):
    if current < target:
        current += step
        if current > target:
            current = target
    elif current > target:
        current -= step
        if current < target:
            current = target
    return current

def apply_deadzone(value, deadzone):
    if abs(value) < deadzone:
        return 0.0
    return value

def generate_frames():
    while True:
        success, frame = cap.read()
        if not success:
            time.sleep(0.01)
            continue
        ret, buffer = cv2.imencode('.jpg', frame, [
            cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY,
            cv2.IMWRITE_JPEG_OPTIMIZE, 1
        ])
        if not ret:
            continue
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Robot 1 — Live Feed</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="mobile-web-app-capable" content="yes">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                background: #000;
                width: 100vw;
                height: 100vh;
                overflow: hidden;
                font-family: Arial, sans-serif;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            #video-container {
                position: relative;
                width: 100vw;
                height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
            }
            #feed {
                width: 100%;
                height: 100%;
                object-fit: contain;
                display: block;
            }
            #overlay {
                position: absolute;
                top: 0; left: 0;
                width: 100%; height: 100%;
                background: linear-gradient(
                    to bottom,
                    rgba(0,0,0,0.6) 0%,
                    transparent 20%,
                    transparent 75%,
                    rgba(0,0,0,0.7) 100%
                );
                opacity: 0;
                transition: opacity 0.3s ease;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                padding: 16px;
            }
            #overlay.visible { opacity: 1; }
            #top-bar {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            #live-badge {
                background: #ff0000;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 3px 8px;
                border-radius: 3px;
                letter-spacing: 1px;
            }
            #title {
                color: white;
                font-size: 16px;
                font-weight: bold;
                text-shadow: 1px 1px 3px rgba(0,0,0,0.8);
            }
            #bottom-bar {
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
            #status { color: #ccc; font-size: 13px; }
            #fullscreen-btn {
                background: none;
                border: none;
                cursor: pointer;
                padding: 6px;
                color: white;
                font-size: 22px;
            }
            #tap-feedback {
                position: absolute;
                top: 50%; left: 50%;
                transform: translate(-50%, -50%);
                background: rgba(0,0,0,0.6);
                border-radius: 50%;
                width: 70px; height: 70px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 30px;
                color: white;
                opacity: 0;
                transition: opacity 0.2s;
                pointer-events: none;
            }
            #tap-feedback.show { opacity: 1; }
            #connection-lost {
                display: none;
                position: absolute;
                top: 50%; left: 50%;
                transform: translate(-50%, -50%);
                color: white;
                font-size: 16px;
                text-align: center;
                background: rgba(0,0,0,0.7);
                padding: 20px 30px;
                border-radius: 10px;
            }
        </style>
    </head>
    <body>
        <div id="video-container" onclick="handleTap()">
            <img id="feed" src="/video_feed"
                 onerror="showConnectionLost()"
                 onload="hideConnectionLost()">
            <div id="overlay">
                <div id="top-bar">
                    <span id="live-badge">● LIVE</span>
                    <span id="title">🤖 Robot 1 — Camera Feed</span>
                </div>
                <div id="bottom-bar">
                    <span id="status">Live Stream</span>
                    <button id="fullscreen-btn" onclick="toggleFullscreen(event)">⛶</button>
                </div>
            </div>
            <div id="tap-feedback">📷</div>
            <div id="connection-lost">
                ⚠️ Connection Lost<br>
                <small>Trying to reconnect...</small>
            </div>
        </div>
        <script>
            let overlayTimeout;
            function handleTap() {
                const overlay = document.getElementById('overlay');
                const feedback = document.getElementById('tap-feedback');
                feedback.classList.add('show');
                setTimeout(() => feedback.classList.remove('show'), 300);
                overlay.classList.add('visible');
                clearTimeout(overlayTimeout);
                overlayTimeout = setTimeout(() => overlay.classList.remove('visible'), 3000);
            }
            function toggleFullscreen(e) {
                e.stopPropagation();
                if (!document.fullscreenElement) {
                    document.documentElement.requestFullscreen().catch(() => {});
                    document.getElementById('fullscreen-btn').innerText = '✕';
                } else {
                    document.exitFullscreen();
                    document.getElementById('fullscreen-btn').innerText = '⛶';
                }
            }
            function showConnectionLost() {
                document.getElementById('connection-lost').style.display = 'block';
                setTimeout(() => {
                    document.getElementById('feed').src = '/video_feed?' + new Date().getTime();
                }, 2000);
            }
            function hideConnectionLost() {
                document.getElementById('connection-lost').style.display = 'none';
            }
            setTimeout(() => document.getElementById('overlay').classList.remove('visible'), 3000);
            document.getElementById('overlay').classList.add('visible');
            setInterval(() => {
                document.getElementById('status').innerText = 'Live • ' + new Date().toLocaleTimeString();
            }, 1000);
        </script>
    </body>
    </html>
    '''

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_flask():
    app.run(host='0.0.0.0', port=STREAM_PORT, debug=False, use_reloader=False)

# ===== START FLASK IN BACKGROUND THREAD =====
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# ===== PYGAME INIT =====
pygame.init()
pygame.joystick.init()

print("=" * 50)
print("Robot 1 — Control + Camera Feed")
print("=" * 50)
print(f"Camera feed: http://192.168.1.200:{STREAM_PORT}")
print("=" * 50)
print("Waiting for PS4 controller...")

while pygame.joystick.get_count() == 0:
    pygame.event.pump()
    pygame.joystick.quit()
    pygame.joystick.init()
    time.sleep(0.5)
    print("No controller found, retrying...")

js = pygame.joystick.Joystick(0)
js.init()
print(f"Controller connected: {js.get_name()}")
print("Motors DISABLED  — Press Circle ⭕ to enable")
print("Pneumatic OFF    — Press Square 🟥 to toggle")
print("Back Lift        — Press DPad Left ◀ to toggle")

running = True

try:
    while running:
        x = y = rot = lift = 0
        grip = back_lift = front_lift = 0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.JOYDEVICEREMOVED:
                print("Controller disconnected!")
                running = False

        pygame.event.pump()

        # ===== READ ANALOG STICKS =====
        left_x  = apply_deadzone(js.get_axis(0), DEAD_ZONE)
        left_y  = apply_deadzone(js.get_axis(1), DEAD_ZONE)
        right_x = apply_deadzone(js.get_axis(3), DEAD_ZONE)

        # ===== READ TRIGGERS =====
        l2 = js.get_axis(2)
        r2 = js.get_axis(5)

        l2 = (l2 + 1) / 2
        r2 = (r2 + 1) / 2

        if l2 < 0.05: l2 = 0.0
        if r2 < 0.05: r2 = 0.0

        # ===== READ BUTTONS =====
        cross    = js.get_button(0)   # Gripper toggle
        circle   = js.get_button(1)   # Kill switch
        square   = js.get_button(2)   # Pneumatic toggle
        triangle = js.get_button(3)   # Front lift toggle
        options  = js.get_button(9)   # Exit

        # ===== READ DPAD =====
        hat       = js.get_hat(0)
        dpad_left = (hat[0] == -1)    # Back lift toggle

        if options:
            running = False

        # ===== KILL SWITCH TOGGLE =====
        if circle and not prev_circle:
            motors_enabled = not motors_enabled
            if motors_enabled:
                print("Motors ENABLED ✅ — Back lift → 90°")
            else:
                print("Motors DISABLED ❌ — Back lift → 180°")
                backUp = False
        prev_circle = circle

        # ===== PNEUMATIC TOGGLE — Square =====
        if square and not prev_square:
            pneumaticOn = not pneumaticOn
            print(f"Pneumatic {'ON 💨' if pneumaticOn else 'OFF'}")
        prev_square = square

        # ===== MOVEMENT =====
        x   =  left_x
        y   = -left_y
        rot = -right_x  # Inverted — fixed!

        # ===== LIFT =====
        lift = r2 - l2
        lift = max(-1.0, min(1.0, lift))

        # ===== GRIP TOGGLE — Cross =====
        grip = 1 if (cross and not prev_cross) else 0
        prev_cross = cross

        # ===== BACK LIFT TOGGLE — DPad Left =====
        if motors_enabled:
            if dpad_left and not prev_dpad_left:
                backUp = not backUp
        else:
            backUp = False

        back_lift = 1 if (dpad_left and not prev_dpad_left and motors_enabled) else 0
        prev_dpad_left = dpad_left

        # ===== FRONT LIFT TOGGLE — Triangle =====
        front_lift = 1 if (triangle and not prev_triangle) else 0
        prev_triangle = triangle

        # ===== PNEUMATIC STATE =====
        pneumatic = 1 if pneumaticOn else 0

        # ===== SMART PWM SELECTION =====
        if y != 0 and x == 0 and rot == 0:
            effective_pwm = MAX_PWM
        elif x != 0 and rot == 0:
            effective_pwm = STRAFE_PWM
        elif rot != 0 and x == 0:
            effective_pwm = ROTATION_PWM
        else:
            effective_pwm = min(STRAFE_PWM, ROTATION_PWM)

        # ===== MECANUM CALC =====
        if motors_enabled:
            LF = y + x + rot
            RF = y - x - rot
            LB = y - x + rot
            RB = y + x - rot

            max_val = max(abs(LF), abs(RF), abs(LB), abs(RB))
            if max_val > 1:
                LF /= max_val
                RF /= max_val
                LB /= max_val
                RB /= max_val

            target_LF   = int(LF * effective_pwm)
            target_RF   = int(RF * effective_pwm)
            target_LB   = int(LB * effective_pwm)
            target_RB   = int(RB * effective_pwm)
            target_LIFT = int(lift * MAX_LIFT_PWM)
        else:
            target_LF   = 0
            target_RF   = 0
            target_LB   = 0
            target_RB   = 0
            target_LIFT = 0

        # ===== APPLY RAMP =====
        current_LF   = ramp(current_LF,   target_LF,   RAMP_STEP)
        current_RF   = ramp(current_RF,   target_RF,   RAMP_STEP)
        current_LB   = ramp(current_LB,   target_LB,   RAMP_STEP)
        current_RB   = ramp(current_RB,   target_RB,   RAMP_STEP)
        current_LIFT = ramp(current_LIFT, target_LIFT, RAMP_STEP)

        # ===== SEND DATA (9 values) =====
        data = f"{current_LF},{current_RF},{current_LB},{current_RB},{current_LIFT},{grip},{back_lift},{front_lift},{pneumatic}\n"

        try:
            ser.write(data.encode())
        except Exception as e:
            print("Serial error:", e)

        # ===== SMART PRINT (only when values change) =====
        if data != prev_data:
            print(data.strip())
            prev_data = data

        time.sleep(0.05)

# ===== SAFE EXIT =====
finally:
    try:
        ser.write(b"0,0,0,0,0,0,0,0,0\n")
        time.sleep(0.1)
        ser.close()
    except:
        pass
    cap.release()
    pygame.quit()
    print("Shutdown complete!")
