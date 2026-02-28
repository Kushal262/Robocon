import cv2
import numpy as np
import os
import glob
from collections import deque

# ====================== CONFIGURATION ======================
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

TEMPLATE_SIZE = 100         # Max template dimension (pixels)
PROCESS_WIDTH = 400         # Frame processing width
SCALE_STEPS = 5
MIN_SCALE = 0.5
MAX_SCALE = 1.6
DETECT_EVERY_N = 3          # Process every Nth frame

# --- Dual thresholds (BOTH must pass to be TRUE) ---
EDGE_THRESHOLD = 0.35       # Canny edge match threshold
GRAY_THRESHOLD = 0.55       # Grayscale match threshold

# --- Smoothing ---
SMOOTH_FRAMES = 12          # History buffer size
MAJORITY_PCT = 0.70         # 70% majority required to switch state


# ====================== HELPERS ======================
def to_edges(gray_img):
    blurred = cv2.GaussianBlur(gray_img, (5, 5), 0)
    return cv2.Canny(blurred, 50, 150)


def shrink(img, max_dim):
    h, w = img.shape[:2]
    if max(h, w) <= max_dim:
        return img
    s = max_dim / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


# ====================== LOAD TEMPLATES ======================
def load_templates(template_dir):
    templates = []
    if not os.path.isdir(template_dir):
        print(f"ERROR: Folder not found: {template_dir}")
        return templates

    files = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
        files.extend(glob.glob(os.path.join(template_dir, ext)))
    files.sort()

    for f in files:
        img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        img = shrink(img, TEMPLATE_SIZE)
        edges = to_edges(img)
        name = os.path.splitext(os.path.basename(f))[0]
        templates.append({"name": name, "gray": img, "edges": edges})
        print(f"  + {name}  ({img.shape[1]}x{img.shape[0]})")

    return templates


# ====================== DETECTION ======================
def detect(frame_gray, frame_edges, templates, scales):
    """
    Dual-method detection:
      1) Canny edge template matching
      2) Grayscale template matching
    Both must exceed their thresholds for TRUE.
    Returns (edge_score, gray_score, best_name)
    """
    best_edge = 0.0
    best_gray = 0.0
    best_name = ""
    best_combined = 0.0
    fh, fw = frame_edges.shape

    for t in templates:
        for sc in scales:
            # Edge matching
            te = t["edges"]
            th, tw = te.shape
            nw, nh = int(tw * sc), int(th * sc)
            if nw < 12 or nh < 12 or nh >= fh or nw >= fw:
                continue

            resized_edge = cv2.resize(te, (nw, nh))
            result_e = cv2.matchTemplate(frame_edges, resized_edge, cv2.TM_CCOEFF_NORMED)
            _, mx_e, _, _ = cv2.minMaxLoc(result_e)

            # Grayscale matching
            tg = t["gray"]
            resized_gray = cv2.resize(tg, (nw, nh))
            result_g = cv2.matchTemplate(frame_gray, resized_gray, cv2.TM_CCOEFF_NORMED)
            _, mx_g, _, _ = cv2.minMaxLoc(result_g)

            # Combined score (both must be decent)
            combined = mx_e + mx_g
            if combined > best_combined:
                best_combined = combined
                best_edge = mx_e
                best_gray = mx_g
                best_name = t["name"]

    return best_edge, best_gray, best_name


# ====================== MAIN ======================
def main():
    print("=" * 50)
    print("      SYMBOL DETECTOR  -  TRUE / FALSE")
    print("=" * 50)

    templates = load_templates(TEMPLATE_DIR)
    if not templates:
        print("No templates loaded!")
        return

    print(f"\n✅ {len(templates)} templates loaded. Starting camera...\n")

    scales = np.linspace(MIN_SCALE, MAX_SCALE, SCALE_STEPS)
    history = deque(maxlen=SMOOTH_FRAMES)

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    if not cap.isOpened():
        print("Cannot open camera!")
        return

    count = 0
    c_edge = 0.0
    c_gray = 0.0
    c_name = ""
    current_state = False

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        count += 1

        # --- Detection every Nth frame ---
        if count % DETECT_EVERY_N == 0:
            h, w = frame.shape[:2]
            sc = PROCESS_WIDTH / w
            small = cv2.resize(frame, (PROCESS_WIDTH, int(h * sc)))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            edges = to_edges(gray)

            c_edge, c_gray, c_name = detect(gray, edges, templates, scales)

            # DUAL check: BOTH methods must pass their threshold
            frame_match = (c_edge >= EDGE_THRESHOLD) and (c_gray >= GRAY_THRESHOLD)
            history.append(frame_match)

        # --- Smoothed state ---
        if len(history) >= 3:
            true_pct = sum(history) / len(history)
            if current_state:
                # Switch to FALSE only when strong FALSE majority
                if true_pct < (1.0 - MAJORITY_PCT):
                    current_state = False
            else:
                # Switch to TRUE only when strong TRUE majority
                if true_pct >= MAJORITY_PCT:
                    current_state = True

        # --- Display ---
        if current_state:
            cv2.putText(frame, "TRUE", (40, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 3.5, (0, 255, 0), 8)
            cv2.putText(frame, f"{c_name}", (40, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "FALSE", (40, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 3.5, (0, 0, 255), 8)

        # --- Debug info (always visible so you can see the scores) ---
        debug_color = (255, 255, 255)
        cv2.putText(frame, f"Edge: {c_edge:.3f}  (need {EDGE_THRESHOLD})", (40, 200),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, debug_color, 1)
        cv2.putText(frame, f"Gray: {c_gray:.3f}  (need {GRAY_THRESHOLD})", (40, 225),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, debug_color, 1)
        if len(history) > 0:
            pct = sum(history) / len(history) * 100
            cv2.putText(frame, f"Vote: {pct:.0f}%  (need {MAJORITY_PCT*100:.0f}%)", (40, 250),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, debug_color, 1)

        # Bottom bar
        color = (0, 200, 0) if current_state else (0, 0, 200)
        cv2.rectangle(frame, (0, frame.shape[0] - 35),
                      (frame.shape[1], frame.shape[0]), color, -1)
        cv2.putText(frame, f"Templates: {len(templates)} | q=quit",
                    (8, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        cv2.imshow("Symbol Detector", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
