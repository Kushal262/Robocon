import cv2
import numpy as np
import os
import glob
from collections import deque

# ====================== CONFIGURATION ======================
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# SIFT matching
MIN_MATCH_COUNT = 10        # Minimum good feature matches to consider
MIN_INLIERS = 10            # Minimum geometric inliers for TRUE
RATIO_TEST = 0.7            # Lowe's ratio test
PROCESS_WIDTH = 640         # Frame processing width

# Smoothing
SMOOTH_FRAMES = 8
MAJORITY_PCT = 0.60


# ====================== LOAD TEMPLATES ======================
def load_templates(template_dir):
    
    """Load templates and extract SIFT features."""
    sift = cv2.SIFT_create(nfeatures=1000)
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

        # Resize template for speed
        h, w = img.shape
        if max(h, w) > 500:
            s = 500 / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)))

        kp, des = sift.detectAndCompute(img, None)
        if des is not None and len(kp) >= 5:
            name = os.path.splitext(os.path.basename(f))[0]
            templates.append({
                "name": name,
                "image": img,
                "keypoints": kp,
                "descriptors": des
            })
            print(f"  + {name} ({len(kp)} features)")

    return templates


# ====================== QUALITY CHECK ======================
def is_good_homography(boundary, frame_shape):
    """
    Check if the detected boundary makes geometric sense.
    Rejects matches on random background objects.
    """
    if boundary is None:
        return False

    pts = boundary.reshape(4, 2)

    # Check area: must be reasonable (not too tiny or huge)
    area = cv2.contourArea(pts.astype(np.float32))
    frame_area = frame_shape[0] * frame_shape[1]
    if area < frame_area * 0.005 or area > frame_area * 0.8:
        return False

    # Check convexity: a valid match should form a roughly convex quad
    if not cv2.isContourConvex(pts.astype(np.float32)):
        return False

    # Check aspect ratio: sides shouldn't be wildly different
    sides = []
    for i in range(4):
        d = np.linalg.norm(pts[i] - pts[(i + 1) % 4])
        sides.append(d)
    if min(sides) < 15 or max(sides) / (min(sides) + 1e-6) > 8:
        return False

    return True


# ====================== DETECTION ======================
def detect_symbol(gray_frame, templates, sift, flann):
    """
    SIFT feature matching + homography verification.
    Returns (matched, name, inliers, boundary_pts)
    """
    kp_frame, des_frame = sift.detectAndCompute(gray_frame, None)

    if des_frame is None or len(kp_frame) < 5:
        return False, "", 0, None

    best_inliers = 0
    best_name = ""
    best_boundary = None

    for tmpl in templates:
        des_t = tmpl["descriptors"]
        kp_t = tmpl["keypoints"]

        # FLANN matching
        try:
            matches = flann.knnMatch(des_t, des_frame, k=2)
        except cv2.error:
            continue

        # Lowe's ratio test
        good = []
        for pair in matches:
            if len(pair) == 2:
                m, n = pair
                if m.distance < RATIO_TEST * n.distance:
                    good.append(m)

        if len(good) < MIN_MATCH_COUNT:
            continue

        # Geometric verification with homography (RANSAC)
        src_pts = np.float32([kp_t[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp_frame[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

        M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

        if M is not None and mask is not None:
            inliers = int(mask.ravel().sum())

            if inliers > best_inliers:
                # Get the boundary of the detected symbol
                h, w = tmpl["image"].shape
                pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
                boundary = cv2.perspectiveTransform(pts, M)

                # Quality check: reject nonsensical matches
                if is_good_homography(boundary, gray_frame.shape):
                    best_inliers = inliers
                    best_name = tmpl["name"]
                    best_boundary = boundary

    matched = best_inliers >= MIN_INLIERS
    return matched, best_name, best_inliers, best_boundary


# ====================== MAIN ======================
def main():
    print("=" * 55)
    print("   SIFT SYMBOL DETECTOR  -  TRUE / FALSE")
    print("=" * 55)

    # Load templates
    print("\nLoading templates...")
    templates = load_templates(TEMPLATE_DIR)
    if not templates:
        print("No templates loaded!")
        return

    print(f"\n  {len(templates)} templates ready.\n")
    print("Starting camera... Press 'q' to quit.\n")

    # SIFT detector
    sift = cv2.SIFT_create(nfeatures=1000)

    # FLANN matcher
    FLANN_INDEX_KDTREE = 1
    index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    search_params = dict(checks=50)
    flann = cv2.FlannBasedMatcher(index_params, search_params)

    # Smoothing
    history = deque(maxlen=SMOOTH_FRAMES)

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print("Cannot open camera!")
        return

    current_state = False
    c_name = ""
    c_inliers = 0
    c_boundary = None
    scale_factor = 1.0
    frame_count = 0

    while True:
        # Drain buffer to always get the latest frame
        for _ in range(2):
            cap.grab()
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1

        # Process every 2nd frame for speed
        if frame_count % 2 == 0:
            h, w = frame.shape[:2]
            scale_factor = w / PROCESS_WIDTH
            new_h = int(h / scale_factor)
            small = cv2.resize(frame, (PROCESS_WIDTH, new_h))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            matched, name, inliers, boundary = detect_symbol(gray, templates, sift, flann)
            c_name = name
            c_inliers = inliers
            c_boundary = boundary
            history.append(matched)

        # Smoothed state
        if len(history) >= 3:
            true_pct = sum(history) / len(history)
            if current_state:
                if true_pct < (1.0 - MAJORITY_PCT):
                    current_state = False
            else:
                if true_pct >= MAJORITY_PCT:
                    current_state = True

        # Draw symbol boundary (perspective-correct outline)
        if c_boundary is not None and current_state:
            pts = (c_boundary * scale_factor).astype(np.int32)
            cv2.polylines(frame, [pts], True, (0, 255, 0), 3)

        # Display TRUE/FALSE
        if current_state:
            cv2.putText(frame, "TRUE", (40, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 3.5, (0, 255, 0), 8)
            cv2.putText(frame, f"{c_name}  (inliers: {c_inliers})", (40, 155),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "FALSE", (40, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 3.5, (0, 0, 255), 8)

        # Debug info
        cv2.putText(frame, f"Inliers: {c_inliers} (need {MIN_INLIERS})", (40, 200),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Bottom bar
        color = (0, 200, 0) if current_state else (0, 0, 200)
        cv2.rectangle(frame, (0, frame.shape[0] - 35),
                      (frame.shape[1], frame.shape[0]), color, -1)
        cv2.putText(frame, f"SIFT | Templates: {len(templates)} | q=quit",
                    (8, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        cv2.imshow("Symbol Detector", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
