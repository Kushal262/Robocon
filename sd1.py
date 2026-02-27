import cv2
import numpy as np
import os
import glob

# ====================== CONFIGURATION ======================
# Place your symbol template images in the "templates" folder.
# The detector will ONLY recognize these symbols as TRUE.
# Anything else will be shown as FALSE.
# ============================================================

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# Detection tuning
MIN_GOOD_MATCHES = 15      # Minimum feature matches required to call it TRUE
MATCH_RATIO = 0.75         # Lowe's ratio test (lower = stricter)
PROCESS_WIDTH = 640        # Resize frame to this width for faster processing

# ====================== LOAD TEMPLATES ======================
def load_templates(template_dir):
    """Load all images from the templates directory and extract ORB features."""
    orb = cv2.ORB_create(nfeatures=1000)
    templates = []

    if not os.path.isdir(template_dir):
        print(f"ERROR: Templates folder not found at: {template_dir}")
        return templates

    # Support multiple image formats
    extensions = ("*.png", "*.jpg", "*.jpeg", "*.bmp")
    image_files = []
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(template_dir, ext)))
    image_files.sort()

    for filepath in image_files:
        img = cv2.imread(filepath, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"  WARNING: Could not load {filepath}")
            continue

        # Resize large templates for faster feature extraction
        h, w = img.shape
        if w > 500:
            scale = 500.0 / w
            img = cv2.resize(img, (500, int(h * scale)))

        # Extract ORB keypoints and descriptors
        kp, des = orb.detectAndCompute(img, None)
        if des is not None and len(kp) > 5:
            name = os.path.splitext(os.path.basename(filepath))[0]
            templates.append({
                "name": name,
                "keypoints": kp,
                "descriptors": des,
                "shape": img.shape
            })
            print(f"  Loaded: {name} ({len(kp)} features)")
        else:
            print(f"  WARNING: Not enough features in {filepath}")

    return templates


# ====================== DETECTION ======================
def detect_symbol(gray_frame, templates, orb, bf_matcher):
    """
    Use ORB feature matching to check if any known template is in the frame.
    Returns (matched, match_name, good_match_count)
    """
    # Extract features from current frame
    kp_frame, des_frame = orb.detectAndCompute(gray_frame, None)

    if des_frame is None or len(kp_frame) < 5:
        return False, "", 0

    best_count = 0
    best_name = ""

    for tmpl in templates:
        des_tmpl = tmpl["descriptors"]

        # BFMatcher with knnMatch
        try:
            matches = bf_matcher.knnMatch(des_tmpl, des_frame, k=2)
        except cv2.error:
            continue

        # Apply Lowe's ratio test
        good_matches = []
        for m_pair in matches:
            if len(m_pair) == 2:
                m, n = m_pair
                if m.distance < MATCH_RATIO * n.distance:
                    good_matches.append(m)

        if len(good_matches) > best_count:
            best_count = len(good_matches)
            best_name = tmpl["name"]

    matched = best_count >= MIN_GOOD_MATCHES
    return matched, best_name, best_count


# ====================== MAIN ======================
def main():
    print("=" * 55)
    print("       SYMBOL DETECTOR - TRUE / FALSE")
    print("=" * 55)
    print(f"Templates folder: {TEMPLATE_DIR}")
    print()

    # Load templates with ORB features
    templates = load_templates(TEMPLATE_DIR)

    if len(templates) == 0:
        print("\nERROR: No templates loaded! Add symbol images to the 'templates' folder.")
        return

    print(f"\n✅ Loaded {len(templates)} symbol template(s).")
    print("Starting camera... Press 'q' to quit.\n")

    # Setup ORB and BFMatcher (created once, reused every frame)
    orb = cv2.ORB_create(nfeatures=1000)
    bf_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    # Open camera
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    if not cap.isOpened():
        print("ERROR: Could not open camera!")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Camera read failed.")
            break

        # Resize for faster processing
        h, w = frame.shape[:2]
        scale = PROCESS_WIDTH / w
        small_frame = cv2.resize(frame, (PROCESS_WIDTH, int(h * scale)))
        gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)

        # Run detection
        matched, match_name, match_count = detect_symbol(gray, templates, orb, bf_matcher)

        # ---- Draw results on original frame ----
        if matched:
            # TRUE (green)
            cv2.putText(frame, "TRUE", (50, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 255, 0), 6)
            info = f"Symbol: {match_name}  |  Matches: {match_count}"
            cv2.putText(frame, info, (50, 140),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        else:
            # FALSE (red)
            cv2.putText(frame, "FALSE", (50, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 255), 6)
            cv2.putText(frame, f"Best matches: {match_count}", (50, 140),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # Status bar at bottom
        bar_color = (0, 255, 0) if matched else (0, 0, 255)
        cv2.rectangle(frame, (0, frame.shape[0] - 40), (frame.shape[1], frame.shape[0]), bar_color, -1)
        status = f"{'TRUE - ' + match_name if matched else 'FALSE'}  |  Templates: {len(templates)}  |  Min matches: {MIN_GOOD_MATCHES}"
        cv2.putText(frame, status, (10, frame.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        cv2.imshow("Symbol Detector - TRUE / FALSE", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Camera closed.")


if __name__ == "__main__":
    main()
