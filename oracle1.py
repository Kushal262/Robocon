"""
ORB Feature Matching Detector

Usage:
- Put your cropped templates as PNG files named template_1.png, template_2.png, ...
- Set TEMPLATE_DIR to your absolute templates folder path.
- Run: python orb_detector.py
- Press 'q' to quit.

Tuning:
- MIN_MATCH_COUNT: minimum good matches before attempting homography.
- INLIER_RATIO_THRESHOLD: fraction of inliers required to accept homography.
- RATIO_TEST: Lowe ratio for descriptor matching (0.7-0.8 typical).
"""

import cv2
import numpy as np
import os
import glob
import threading
import time
from collections import deque

# ================= USER CONFIGURATION =================
TEMPLATE_DIR = r"C:\Users\KHUSH GOYANI\OneDrive\Desktop\python\templates"
CAM_INDEX = 0
CAP_WIDTH = 1280
CAP_HEIGHT = 720
PROCESS_WIDTH = 640

# ORB / matching parameters
ORB_N_FEATURES = 1000
RATIO_TEST = 0.75
MIN_MATCH_COUNT = 12
INLIER_RATIO_THRESHOLD = 0.5  # require at least this fraction of matches to be inliers
SAVE_DETECTIONS = True
DETECTIONS_DIR = "detections"
# ======================================================

os.makedirs(DETECTIONS_DIR, exist_ok=True)

def list_template_files(path):
    return sorted(glob.glob(os.path.join(path, "template_*.png")))

def load_templates_orb(template_dir, orb):
    """
    Load templates and compute ORB keypoints and descriptors.
    Returns list of dicts: {'name','img','kp','des','shape','corners'}
    """
    templates = []
    files = list_template_files(template_dir)
    if not files:
        print("No template_*.png files found in", template_dir)
        return templates

    for p in files:
        img = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        if img is None:
            print("Failed to load:", p)
            continue

        # Convert RGBA to BGR on white background if needed
        if img.ndim == 3 and img.shape[2] == 4:
            b, g, r, a = cv2.split(img)
            bg = np.ones_like(b, dtype=np.uint8) * 255
            alpha = a.astype(float) / 255.0
            cb = (b.astype(float) * alpha + bg.astype(float) * (1 - alpha)).astype(np.uint8)
            cg = (g.astype(float) * alpha + bg.astype(float) * (1 - alpha)).astype(np.uint8)
            cr = (r.astype(float) * alpha + bg.astype(float) * (1 - alpha)).astype(np.uint8)
            img = cv2.merge([cb, cg, cr])

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
        kp, des = orb.detectAndCompute(gray, None)
        h, w = gray.shape[:2]
        corners = np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2)
        templates.append({'name': os.path.basename(p), 'img': img, 'kp': kp, 'des': des, 'shape': (w,h), 'corners': corners})
        print(f"Loaded template: {os.path.basename(p)}  keypoints={len(kp)}  size={w}x{h}")
    return templates

class CameraThread:
    """Threaded camera capture to reduce lag."""
    def __init__(self, index=0, width=1280, height=720, queue_max=2):
        self.cap = cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.queue = deque(maxlen=queue_max)
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        if not self.cap.isOpened():
            raise RuntimeError("Could not open camera")
        self.running = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            with self.lock:
                self.queue.append(frame)

    def read_latest(self):
        with self.lock:
            if not self.queue:
                return None
            return self.queue[-1].copy()

    def stop(self):
        self.running = False
        time.sleep(0.05)
        if self.cap.isOpened():
            self.cap.release()

def match_and_verify(orb_des_frame, template, bf):
    """
    Match descriptors between frame and template, apply ratio test,
    then compute homography and return inlier count and homography.
    """
    if template['des'] is None or orb_des_frame is None:
        return 0, None, None

    # BFMatcher with Hamming for ORB
    matches = bf.knnMatch(template['des'], orb_des_frame, k=2)
    good = []
    for m_n in matches:
        if len(m_n) != 2:
            continue
        m, n = m_n
        if m.distance < RATIO_TEST * n.distance:
            good.append(m)

    if len(good) < MIN_MATCH_COUNT:
        return len(good), None, None

    # Prepare points for homography: template pts -> frame pts
    src_pts = np.float32([ template['kp'][m.queryIdx].pt for m in good ]).reshape(-1,1,2)
    dst_pts = np.float32([ frame_kp[m.trainIdx].pt for m in good ]).reshape(-1,1,2)

    # Compute homography with RANSAC
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if mask is None:
        return len(good), None, None
    inliers = int(mask.sum())
    return len(good), H, mask

# Initialize ORB and BF matcher
orb = cv2.ORB_create(nfeatures=ORB_N_FEATURES)
bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

# Load templates
templates = load_templates_orb(TEMPLATE_DIR, orb)
if not templates:
    print("No templates loaded. Place template_*.png files in TEMPLATE_DIR and re-run.")
    raise SystemExit

# Start camera thread
cam = CameraThread(index=CAM_INDEX, width=CAP_WIDTH, height=CAP_HEIGHT, queue_max=2)
try:
    cam.start()
except RuntimeError as e:
    print("Camera error:", e)
    raise SystemExit

print("Starting ORB detector. Press 'q' to quit.")
frame_idx = 0
try:
    while True:
        frame = cam.read_latest()
        if frame is None:
            time.sleep(0.01)
            continue
        frame_idx += 1

        # Downscale for processing to speed up
        h, w = frame.shape[:2]
        scale = PROCESS_WIDTH / float(w)
        proc_h = int(h * scale)
        proc = cv2.resize(frame, (PROCESS_WIDTH, proc_h), interpolation=cv2.INTER_AREA)
        gray_proc = cv2.cvtColor(proc, cv2.COLOR_BGR2GRAY)

        # Compute ORB keypoints/descriptors for frame
        frame_kp, frame_des = orb.detectAndCompute(gray_proc, None)
        if frame_des is None or len(frame_kp) < 8:
            # show frame and continue
            cv2.putText(frame, "No features in frame", (10,40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,255), 2)
            cv2.imshow("ORB Detector", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            continue

        best_template = None
        best_score = 0
        best_H = None
        best_mask = None
        best_good_count = 0

        # Match against each template
        for t in templates:
            # match descriptors: template -> frame
            matches = bf.knnMatch(t['des'], frame_des, k=2)
            good = []
            for m_n in matches:
                if len(m_n) != 2:
                    continue
                m, n = m_n
                if m.distance < RATIO_TEST * n.distance:
                    good.append(m)
            good_count = len(good)
            if good_count < MIN_MATCH_COUNT:
                continue

            # compute homography using good matches
            src_pts = np.float32([ t['kp'][m.queryIdx].pt for m in good ]).reshape(-1,1,2)
            dst_pts = np.float32([ frame_kp[m.trainIdx].pt for m in good ]).reshape(-1,1,2)
            H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
            if mask is None:
                continue
            inliers = int(mask.sum())
            # compute inlier ratio
            inlier_ratio = inliers / float(good_count) if good_count > 0 else 0.0

            # Score by inliers and inlier ratio
            score = inliers * inlier_ratio

            if score > best_score and inlier_ratio >= INLIER_RATIO_THRESHOLD:
                best_score = score
                best_template = t
                best_H = H
                best_mask = mask
                best_good_count = good_count

        display = frame.copy()
        if best_template is not None and best_H is not None:
            # Map template corners to frame (proc coords), then scale to original frame
            pts = cv2.perspectiveTransform(best_template['corners'], best_H)
            pts = pts.reshape(-1,2)
            # scale back to original frame coordinates
            inv_scale = 1.0 / scale
            pts_orig = np.int32(pts * inv_scale)

            # draw polygon
            cv2.polylines(display, [pts_orig], True, (0,255,0), 3)
            cv2.putText(display, f"DETECTED: {best_template['name']}", (10,40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 3)
            cv2.putText(display, f"Matches:{best_good_count} Score:{best_score:.1f}", (10,80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)
            cv2.putText(display, "STOP", (10,130), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0,0,255), 6)

            # Save detection crop for inspection
            if SAVE_DETECTIONS:
                x_coords = pts_orig[:,0]
                y_coords = pts_orig[:,1]
                x1, x2 = max(0, x_coords.min()), min(display.shape[1], x_coords.max())
                y1, y2 = max(0, y_coords.min()), min(display.shape[0], y_coords.max())
                if x2 - x1 > 10 and y2 - y1 > 10:
                    crop = display[y1:y2, x1:x2].copy()
                    ts = int(time.time()*1000)
                    fname = os.path.join(DETECTIONS_DIR, f"{best_template['name']}_{best_good_count}_{ts}.png")
                    cv2.imwrite(fname, crop)
        else:
            cv2.putText(display, "CONTINUE", (10,60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0,255,0), 6)

        cv2.imshow("ORB Detector", display)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    cam.stop()
    cv2.destroyAllWindows()