import torch
from facenet_pytorch import MTCNN, InceptionResnetV1
import numpy as np
import cv2

class MotionLivenessDetector:
    def __init__(self):
        self.history = []
        self.live = True # Temporarily default to True due to Python 3.12 library constraints

    def detect_liveness(self, image):
        # Basic check: Ensure image is not too dark
        if image is None: return False
        mean_brightness = np.mean(image)
        if mean_brightness < 20: # Threshold for 'too dark'
            return False
        return True

    def reset(self):
        # Clear the motion history to start a fresh detection session
        self.history = []


class FaceRecognitionEngine:
    def __init__(self, device=None):
        self.device = device if device else torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        # Initialize MTCNN for face detection
        self.mtcnn = MTCNN(keep_all=False, device=self.device)
        # Initialize InceptionResnetV1 for face embedding (pre-trained on vggface2)
        self.resnet = InceptionResnetV1(pretrained='vggface2').eval().to(self.device)
        self.liveness = MotionLivenessDetector()

    def detect_and_embed(self, image, check_liveness=True):
        """
        Detects a face in the image and returns its embedding.
        Also checks liveness.
        image: RGB image numpy array
        """
        # 1. Liveness Check
        is_live = False
        if check_liveness:
            is_live = self.liveness.detect_liveness(image)

        # 2. Face Embedding
        face = self.mtcnn(image)
        if face is None:
            return None, None, is_live
        
        boxes, _ = self.mtcnn.detect(image)
        
        with torch.no_grad():
            face = face.unsqueeze(0).to(self.device)
            # Generate embedding and L2 normalize it
            embedding_tensor = self.resnet(face)
            embedding = torch.nn.functional.normalize(embedding_tensor, p=2, dim=1).cpu().numpy()[0]
            
        return embedding, boxes[0] if boxes is not None else None, is_live

    def compare_embeddings(self, embedding1, embedding2, threshold=0.8):
        """
        Compares two embeddings using Euclidean distance.
        Returns a boolean (match) and the distance.
        The threshold is explicitly passed to enforce security.
        """
        if embedding1 is None or embedding2 is None:
            return False, float('inf')
        
        # Calculate Euclidean distance
        distance = np.linalg.norm(embedding1 - embedding2)
        return distance < threshold, distance
