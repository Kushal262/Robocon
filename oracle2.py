"""
fast_accurate_detector.py

Usage:
- Put templates named template_1.png, template_2.png, ... in TEMPLATE_DIR.
- Set TEMPLATE_DIR to your absolute path (use raw string on Windows).
- Run: python fast_accurate_detector.py
- Press 'q' to quit, 'c' to clear detection state.

Requirements:
- Python 3.8+
- OpenCV (pip install opencv-python)
"""

import cv2
import numpy as np
import glob
import os
import threading
import time
from collections import deque, Counter

# ===================== USER TUNABLE PARAMETERS =====================
TEMPLATE_DIR = r"C:\Users\KHUSH GOYANI\OneDrive\Desktop\python\templates"

# Camera / processing
CAM_INDEX = 0
CAP_WIDTH = 1280
CAP_HEIGHT = 720
PROCESS_WIDTH = 800            # width used for ORB matching (downscale for speed)

# ORB matching parameters
ORB_N_FEATURES = 1500
RATIO_TEST = 0.75
MIN_GOOD_MATCHES = 8           # lower if templates are small / low-texture
MIN_INLIERS = 6
INLIER_RATIO_THRESHOLD = 0.35

# Debounce / stability
DEBOUNCE_WINDOW = 6            # number of recent detection results to keep
DETECTION_REQUIRED_COUNT = 4   # how many frames in window must agree
DETECTION_SCORE_THRESHOLD = 8  # average score threshold (inliers * inlier_ratio)

# Tracker & revalidation
TRACKER_TYPE = "KCF"           # "KCF" (fast) or "CSRT" (more accurate, slower)
REVALIDATE_EVERY_N_SEC = 0.8   # seconds between revalidations while tracking
TRACKER_MAX_LOST = 6           # allowed consecutive tracker failures before fallback

# Performance limits
MAX_TEMPLATES_TO_CHECK = 40
SAVE_DETECTIONS = True
DETECTIONS_DIR = "detections"
VERBOSE = False
# ==================================================================

os.makedirs(DETECTIONS_DIR, exist_ok=True)

# -------------------- Utilities --------------------
def list_template_files(path):
    return sorted(glob.glob(os.path.join(path, "template_*.png")))

def composite_alpha_to_bgr(img):
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        b,g,r,a = cv2.split(img)
        bg = np.ones_like(b, dtype=np.uint8) * 255
        alpha = a.astype(float)/255.0
        cb = (b.astype(float)*alpha + bg*(1-alpha)).astype(np.uint8)
        cg = (g.astype(float)*alpha + bg*(1-alpha)).astype(np.uint8)
        cr = (r.astype(float)*alpha + bg*(1-alpha)).astype(np.uint8)
        img = cv2.merge([cb,cg,cr])
    return img

def load_template_orb(orb, path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    img = composite_alpha_to_bgr(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    kp, des = orb.detectAndCompute(gray, None)
    h, w = gray.shape[:2]
    corners = np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2)
    return {'name': os.path.basename(path), 'img': img, 'gray': gray, 'kp': kp, 'des': des, 'shape': (w,h), 'corners': corners}

def create_tracker(name="KCF"):
    # Use CSRT if available and you prefer accuracy over speed
    if name == "CSRT":
        return cv2.TrackerCSRT_create()
    return cv2.TrackerKCF_create()

# -------------------- Detection thread --------------------
class DetectorThread(threading.Thread):
    """
    Background detection thread:
    - Always reads the latest frame (no backlog)
    - Runs ORB matching across templates and returns best candidate
    - Posts result into shared variables (with lock)
    """
    def __init__(self, templates, orb, bf, shared):
        super().__init__(daemon=True)
        self.templates = templates
        self.orb = orb
        self.bf = bf
        self.shared = shared
        self.running = True

    def run(self):
        while self.running:
            frame = None
            # get latest frame (non-blocking)
            with self.shared['frame_lock']:
                if self.shared['latest_frame'] is not None:
                    frame = self.shared['latest_frame'].copy()
            if frame is None:
                time.sleep(0.01)
                continue

            # downscale for matching to PROCESS_WIDTH
            h, w = frame.shape[:2]
            scale = PROCESS_WIDTH / float(w)
            proc_h = int(h * scale)
            proc = cv2.resize(frame, (PROCESS_WIDTH, proc_h), interpolation=cv2.INTER_AREA)
            gray_proc = cv2.cvtColor(proc, cv2.COLOR_BGR2GRAY)

            frame_kp, frame_des = self.orb.detectAndCompute(gray_proc, None)
            best_candidate = None  # dict: {name, score, H, inliers, good_count, proc_scale, proc_shape}
            if frame_des is not None and len(frame_kp) >= 6:
                # iterate templates (limit for performance)
                for t in self.templates[:MAX_TEMPLATES_TO_CHECK]:
                    if t['des'] is None or len(t['kp']) < 4:
                        continue
                    matches = self.bf.knnMatch(t['des'], frame_des, k=2)
                    good = []
                    for m_n in matches:
                        if len(m_n) != 2:
                            continue
                        m, n = m_n
                        if m.distance < RATIO_TEST * n.distance:
                            good.append(m)
                    good_count = len(good)
                    if good_count < MIN_GOOD_MATCHES:
                        continue
                    src_pts = np.float32([ t['kp'][m.queryIdx].pt for m in good ]).reshape(-1,1,2)
                    dst_pts = np.float32([ frame_kp[m.trainIdx].pt for m in good ]).reshape(-1,1,2)
                    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
                    if mask is None:
                        continue
                    inliers = int(mask.sum())
                    inlier_ratio = inliers / float(good_count) if good_count > 0 else 0.0
                    score = inliers * inlier_ratio
                    if VERBOSE:
                        print(f"[detector] {t['name']} good={good_count} inliers={inliers} ratio={inlier_ratio:.2f} score={score:.1f}")
                    if inliers >= MIN_INLIERS and inlier_ratio >= INLIER_RATIO_THRESHOLD:
                        if best_candidate is None or score > best_candidate['score']:
                            best_candidate = {
                                'name': t['name'],
                                'score': score,
                                'H': H,
                                'inliers': inliers,
                                'good_count': good_count,
                                'proc_scale': scale,
                                'proc_shape': (proc.shape[1], proc.shape[0])
                            }

            # write result to shared
            with self.shared['result_lock']:
                self.shared['last_detection'] = best_candidate
                self.shared['last_detection_time'] = time.time()

            # small sleep to yield CPU (detection is continuous but not too tight)
            time.sleep(0.02)

    def stop(self):
        self.running = False

# -------------------- Main --------------------
def run():
    # init ORB and BF matcher
    orb = cv2.ORB_create(nfeatures=ORB_N_FEATURES)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    # load templates
    files = list_template_files(TEMPLATE_DIR)
    if not files:
        print("No templates found in", TEMPLATE_DIR)
        return
    templates = []
    for p in files:
        t = load_template_orb(orb, p)
        if t is None:
            print("Failed to load:", p)
            continue
        templates.append(t)
        if VERBOSE:
            print(f"Loaded {t['name']} kp={len(t['kp'])} size={t['shape']}")

    # precompute edges for optional fallback (not used by default)
    for t in templates:
        t['edges'] = cv2.Canny(cv2.GaussianBlur(t['gray'], (3,3), 0), 50, 150)

    # shared state between main thread and detector thread
    shared = {
        'latest_frame': None,
        'frame_lock': threading.Lock(),
        'last_detection': None,
        'last_detection_time': 0.0,
        'result_lock': threading.Lock()
    }

    detector = DetectorThread(templates, orb, bf, shared)
    detector.start()

    # camera capture (main thread reads frames and updates shared.latest_frame)
    cap = cv2.VideoCapture(CAM_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAP_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_HEIGHT)
    if not cap.isOpened():
        print("Cannot open camera")
        detector.stop()
        return

    # tracker state
    tracker = None
    tracking = False
    tracker_lost = 0
    last_revalidate = 0.0
    last_announced = None

    # debounce history
    recent = deque(maxlen=DEBOUNCE_WINDOW)

    print("Started. Press 'q' to quit, 'c' to clear state.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # publish latest frame for detector thread
            with shared['frame_lock']:
                shared['latest_frame'] = frame.copy()

            # If tracking, update tracker and show STOP while tracker is confident
            if tracking and tracker is not None:
                ok, bbox = tracker.update(frame)
                if ok:
                    tracker_lost = 0
                    x, y, w_box, h_box = [int(v) for v in bbox]
                    cv2.rectangle(frame, (x,y), (x+w_box, y+h_box), (0,255,0), 3)
                    cv2.putText(frame, f"TRACKING {last_announced}", (10,40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)
                    cv2.putText(frame, "STOP", (10,90), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0,0,255), 6)

                    # periodic revalidation by checking detector result timestamp
                    now = time.time()
                    if now - last_revalidate >= REVALIDATE_EVERY_N_SEC:
                        last_revalidate = now
                        with shared['result_lock']:
                            det = shared['last_detection']
                            det_time = shared['last_detection_time']
                        # if detector recently found the same template, keep tracking
                        if det is None or det['name'] != last_announced or (now - det_time) > 2.0:
                            tracker_lost += 1
                        else:
                            tracker_lost = 0

                    if tracker_lost > TRACKER_MAX_LOST:
                        # drop tracker and clear debounce
                        tracking = False
                        tracker = None
                        tracker_lost = 0
                        recent.clear()
                        last_announced = None
                        if VERBOSE:
                            print("Tracker lost; returning to detection.")
                else:
                    tracker_lost += 1
                    if tracker_lost > TRACKER_MAX_LOST:
                        tracking = False
                        tracker = None
                        tracker_lost = 0
                        recent.clear()
                        last_announced = None
                        if VERBOSE:
                            print("Tracker update failed; returning to detection.")
                    else:
                        cv2.putText(frame, "TRACKER UNSTABLE", (10,40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,200,200), 2)

                cv2.imshow("Fast Accurate Detector", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                if key == ord('c'):
                    recent.clear(); last_announced = None; tracking = False; tracker = None
                continue

            # Not tracking: read latest detection result (non-blocking)
            with shared['result_lock']:
                det = shared['last_detection']
                det_time = shared['last_detection_time']

            candidate_name = None
            candidate_score = 0.0
            candidate_H = None
            candidate_proc_scale = None

            # Accept detection only if it is recent (avoid stale results)
            if det is not None and (time.time() - det_time) < 1.2:
                candidate_name = det['name']
                candidate_score = det['score']
                candidate_H = det['H']
                candidate_proc_scale = det['proc_scale']

            # update debounce history
            recent.append((candidate_name, candidate_score))

            # evaluate debounce: require consistent candidate in recent window
            names = [r[0] for r in recent if r[0] is not None]
            if names:
                most_common, count = Counter(names).most_common(1)[0]
                scores_for_candidate = [s for (n,s) in recent if n == most_common]
                avg_score = sum(scores_for_candidate) / len(scores_for_candidate) if scores_for_candidate else 0.0
            else:
                most_common, count, avg_score = None, 0, 0.0

            detected_now = False
            if most_common is not None and count >= DETECTION_REQUIRED_COUNT and avg_score >= DETECTION_SCORE_THRESHOLD:
                detected_now = True

            display = frame.copy()
            if detected_now and most_common is not None:
                # announce detection and start tracker
                if last_announced != most_common:
                    last_announced = most_common
                    if VERBOSE:
                        print(f"[DETECTED] {most_common} count={count} avg_score={avg_score:.2f}")

                # find template object
                t = next((tt for tt in templates if tt['name'] == most_common), None)
                if t is not None and candidate_H is not None:
                    # map template corners to processed frame then to original
                    pts = cv2.perspectiveTransform(t['corners'], candidate_H)
                    pts = pts.reshape(-1,2)
                    inv_scale = 1.0 / candidate_proc_scale
                    pts_orig = np.int32(pts * inv_scale)
                    cv2.polylines(display, [pts_orig], True, (0,255,0), 3)
                    cv2.putText(display, f"DETECTED: {most_common}", (10,40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 3)
                    cv2.putText(display, f"Score: {avg_score:.1f}", (10,80), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)
                    cv2.putText(display, "STOP", (10,130), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0,0,255), 6)

                    # init tracker on bounding rect of pts_orig
                    x_coords = pts_orig[:,0]; y_coords = pts_orig[:,1]
                    x1, x2 = max(0, x_coords.min()), min(display.shape[1], x_coords.max())
                    y1, y2 = max(0, y_coords.min()), min(display.shape[0], y_coords.max())
                    if x2 - x1 > 10 and y2 - y1 > 10:
                        tracker = create_tracker(TRACKER_TYPE)
                        bbox = (x1, y1, x2 - x1, y2 - y1)
                        try:
                            tracker.init(frame, bbox)
                            tracking = True
                            tracker_lost = 0
                            last_revalidate = time.time()
                            # save detection crop
                            if SAVE_DETECTIONS:
                                crop = display[y1:y2, x1:x2].copy()
                                ts = int(time.time()*1000)
                                fname = os.path.join(DETECTIONS_DIR, f"{most_common}_{int(avg_score)}_{ts}.png")
                                cv2.imwrite(fname, crop)
                        except Exception:
                            tracking = False
                            tracker = None
                else:
                    # fallback: just show candidate name
                    cv2.putText(display, f"DETECTED: {most_common} (no-homography)", (10,40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 3)
                    cv2.putText(display, "STOP", (10,90), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0,0,255), 6)
            else:
                # not stable yet: show candidate if any
                if candidate_name is not None:
                    cv2.putText(display, f"Candidate: {candidate_name} score={candidate_score:.2f}", (10,40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,200,200), 2)
                else:
                    cv2.putText(display, "CONTINUE", (10,60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0,255,0), 6)

            cv2.imshow("Fast Accurate Detector", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('c'):
                recent.clear(); last_announced = None; tracking = False; tracker = None

    finally:
        detector.stop()
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    run()