import cv2
import sys
import os

# Add parent directory to path to allow importing recognition module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recognition.engine import FaceRecognitionEngine

def main():
    print("Initializing Face Recognition Engine (this may take a moment to download models on first run)...")
    engine = FaceRecognitionEngine()
    
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    print("Webcam opened. Press 'q' to quit.")
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break

        # Convert to RGB for facenet-pytorch (OpenCV uses BGR)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Get embedding, box, and liveness
        embedding, box, is_live = engine.detect_and_embed(rgb_frame)
        
        if box is not None:
            # Draw bounding box
            x1, y1, x2, y2 = [int(b) for b in box]
            color = (0, 255, 0) if is_live else (0, 165, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            text = "Live Face" if is_live else "Blink to verify..."
            cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

        cv2.imshow('Face Recognition Prototype', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
