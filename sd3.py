import cv2
import numpy as np
import os
import glob
from collections import deque

# ====================== CONFIGURATION ======================
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

TEMPLATE_SIZE = 100
PROCESS_WIDTH = 400
SCALE_STEPS = 5
MIN_SCALE = 0.5
MAX_SCALE = 1.6
DETECT_EVERY_N = 3

# Thresholds
THRESHOLD = 0.38

# Smoothing
SMOOTH_FRAMES = 12
MAJORITY_PCT = 0.70


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
        templates.append({"name": name, "edges": edges})
        print(f"  + {name}  ({edges.shape[1]}x{edges.shape[0]})")

    return templates


# ====================== DETECTION ======================
def detect(frame_edges, templates, scales):
    """
    Canny edge template matching.
    Returns (best_val, best_name, best_location_on_frame)
    """
    best_val = 0.0
    best_name = ""
    best_loc = None
    best_size = (0, 0)
    fh, fw = frame_edges.shape

    for t in templates:
        te = t["edges"]
        th, tw = te.shape

        for sc in scales:
            nw, nh = int(tw * sc), int(th * sc)
            if nw < 12 or nh < 12 or nh >= fh or nw >= fw:
                continue

            resized = cv2.resize(te, (nw, nh))
            result = cv2.matchTemplate(frame_edges, resized, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(result)

            if mx > best_val:
                best_val = mx
                best_name = t["name"]
                best_loc = loc
                best_size = (nw, nh)

    return best_val, best_name, best_loc, best_size


# ====================== MAIN ======================
def main():
    print("=" * 50)
    print("      SYMBOL DETECTOR  -  TRUE / FALSE")
    print("=" * 50)

    templates = load_templates(TEMPLATE_DIR)
    if not templates:
        print("No templates loaded!")
        return

    print(f"\n  {len(templates)} templates loaded. Starting camera...\n")

    scales = np.linspace(MIN_SCALE, MAX_SCALE, SCALE_STEPS)
    history = deque(maxlen=SMOOTH_FRAMES)

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    if not cap.isOpened():
        print("Cannot open camera!")
        return

    count = 0
    c_val = 0.0
    c_name = ""
    c_loc = None
    c_size = (0, 0)
    scale_factor = 1.0
    current_state = False

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        count += 1

        # --- Detection every Nth frame ---
        if count % DETECT_EVERY_N == 0:
            h, w = frame.shape[:2]
            scale_factor = w / PROCESS_WIDTH
            new_h = int(h / scale_factor)
            small = cv2.resize(frame, (PROCESS_WIDTH, new_h))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            edges = to_edges(gray)

            c_val, c_name, c_loc, c_size = detect(edges, templates, scales)
            history.append(c_val >= THRESHOLD)

        # --- Smoothed state ---
        if len(history) >= 3:
            true_pct = sum(history) / len(history)
            if current_state:
                if true_pct < (1.0 - MAJORITY_PCT):
                    current_state = False
            else:
                if true_pct >= MAJORITY_PCT:
                    current_state = True

        # --- Draw border around matched region ---
        if c_loc is not None and c_val >= THRESHOLD:
            x = int(c_loc[0] * scale_factor)
            y = int(c_loc[1] * scale_factor)
            w = int(c_size[0] * scale_factor)
            h = int(c_size[1] * scale_factor)
            border_color = (0, 255, 0) if current_state else (0, 0, 255)
            cv2.rectangle(frame, (x, y), (x + w, y + h), border_color, 3)

        # --- Display ---
        if current_state:
            cv2.putText(frame, "TRUE", (40, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 3.5, (0, 255, 0), 8)
            cv2.putText(frame, f"{c_name}", (40, 155),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "FALSE", (40, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 3.5, (0, 0, 255), 8)

        # Debug scores
        cv2.putText(frame, f"Score: {c_val:.3f} (need {THRESHOLD})", (40, 200),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        if len(history) > 0:
            pct = sum(history) / len(history) * 100
            cv2.putText(frame, f"Vote: {pct:.0f}% (need {MAJORITY_PCT*100:.0f}%)", (40, 230),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        # Bottom bar
        color = (0, 200, 0) if current_state else (0, 0, 200)
        cv2.rectangle(frame, (0, frame.shape[0]-35),
                      (frame.shape[1], frame.shape[0]), color, -1)
        cv2.putText(frame, f"Templates: {len(templates)} | q=quit",
                    (8, frame.shape[0]-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        cv2.imshow("Symbol Detector", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
