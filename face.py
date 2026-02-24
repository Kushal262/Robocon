import cv2
import mediapipe as mp
import numpy as np
import time

# --- Configuration ---
EYE_AR_THRESH = 0.25      # EAR threshold for closed eyes
EYE_CLOSED_TIME_THRESH = 3.0  # Seconds to consider sleeping

# MediaPipe Face Mesh indices for eyes
# MediaPipe uses a 468-point mesh. 
# Left eye indices: 362, 385, 387, 263, 373, 380
# Right eye indices: 33, 160, 158, 133, 153, 144
LEFT_EYE_IDXS = [362, 385, 387, 263, 373, 380]
RIGHT_EYE_IDXS = [33, 160, 158, 133, 153, 144]

def eye_aspect_ratio(eye_points):
    """
    Calculates the Eye Aspect Ratio (EAR) for a single eye.
    eye_points: list of (x, y) coordinates.
    """
    # Vertical distances
    A = np.linalg.norm(eye_points[1] - eye_points[5])
    B = np.linalg.norm(eye_points[2] - eye_points[4])

    # Horizontal distance
    C = np.linalg.norm(eye_points[0] - eye_points[3])

    # Compute EAR
    ear = (A + B) / (2.0 * C)
    return ear

def main():
    BaseOptions = mp.tasks.BaseOptions
    FaceLandmarker = mp.tasks.vision.FaceLandmarker
    FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
    VisionRunningMode = mp.tasks.vision.RunningMode

    # Initialize FaceLandmarker
    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path='face_landmarker.task'),
        running_mode=VisionRunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5)

    try:
        landmarker = FaceLandmarker.create_from_options(options)
    except Exception as e:
        print(f"Failed to create landmarker: {e}")
        return

    # Initialize Video Capture
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    eyes_closed_start_time = None
    status = "Eyes Open"
    start_time = time.time()
    color = (0, 255, 0) # Green

    print("Press 'q' to quit.")

    window_initialized = False

    while cap.isOpened():
        success, image = cap.read()
        if not success:
            print("Ignoring empty camera frame.")
            continue

        # Check if window was closed explicitly (clicked X)
        if window_initialized and cv2.getWindowProperty('Eye Recognition System', cv2.WND_PROP_VISIBLE) < 1:
            break

        # Convert the BGR image to RGB
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)

        # Detect faces asynchronously
        timestamp_ms = int((time.time() - start_time) * 1000)
        face_landmarker_result = landmarker.detect_for_video(mp_image, timestamp_ms)

        if face_landmarker_result.face_landmarks:
            for face_landmarks in face_landmarker_result.face_landmarks:
                # Convert landmarks to pixel coordinates
                h, w, _ = image.shape
                landmarks = []
                # face_landmarks is a list of NormalizedLandmark
                for lm in face_landmarks:
                    landmarks.append(np.array([int(lm.x * w), int(lm.y * h)]))
                
                landmarks = np.array(landmarks)

                # Extract eye coordinates
                left_eye = landmarks[LEFT_EYE_IDXS]
                right_eye = landmarks[RIGHT_EYE_IDXS]

                # Calculate EAR
                leftEAR = eye_aspect_ratio(left_eye)
                rightEAR = eye_aspect_ratio(right_eye)

                # Average EAR
                ear = (leftEAR + rightEAR) / 2.0

                # Check if EAR is below threshold
                if ear < EYE_AR_THRESH:
                    if eyes_closed_start_time is None:
                        eyes_closed_start_time = time.time()
                    
                    current_duration = time.time() - eyes_closed_start_time
                    if current_duration >= EYE_CLOSED_TIME_THRESH:
                        status = "Sleeping"
                        color = (0, 0, 255) # Red
                    else:
                        # Blink detected, but not sleeping yet
                        status = "Eyes Open" # Keep status as Open while blinking/short close
                        color = (0, 255, 0)
                else:
                    eyes_closed_start_time = None
                    status = "Eyes Open"
                    color = (0, 255, 0) # Green

                # Draw eye contours
                cv2.polylines(image, [left_eye], True, (0, 255, 0), 1)
                cv2.polylines(image, [right_eye], True, (0, 255, 0), 1)

                # Display Info
                cv2.putText(image, f"Status: {status}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                cv2.putText(image, f"EAR: {ear:.2f}", (300, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        # Show the image
        cv2.imshow('Eye Recognition System', image)
        window_initialized = True

        if cv2.waitKey(5) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    landmarker.close()

if __name__ == "__main__":
    main()
