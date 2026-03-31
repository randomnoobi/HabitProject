"""
pipeline/detection.py — Object Recognition stage.

Chart stage: "Object Recognition (real time)"

Runs YOLOv8 on a frame, filters to TARGET_CLASSES, and returns
structured detection results with bounding boxes and center points.
"""

from ultralytics import YOLO
from pipeline.config import MODEL_PATH, CONFIDENCE, TARGET_CLASSES


class Detector:
    """YOLO-based object detector filtered to target classes."""

    def __init__(self):
        print(f'  [detection] Loading model: {MODEL_PATH}')
        self.model = YOLO(MODEL_PATH)
        print(f'  [detection] Target classes: {TARGET_CLASSES}')

    def detect(self, frame):
        """
        Run detection on a single frame.

        Args:
            frame: BGR numpy array from the camera.

        Returns:
            list of dicts, each with:
                - class_name: str  (e.g. "cell phone")
                - confidence: float
                - bbox: [x1, y1, x2, y2]  (pixel coordinates)
                - center: (cx, cy)         (center point)
            Only objects in TARGET_CLASSES are returned.
        """
        results = self.model.predict(source=frame, conf=CONFIDENCE, verbose=False)

        detections = []
        for r in results:
            for box in r.boxes:
                cls_name = self.model.names[int(box.cls[0])]

                if cls_name not in TARGET_CLASSES:
                    continue

                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2

                detections.append({
                    'class_name': cls_name,
                    'confidence': conf,
                    'bbox': [x1, y1, x2, y2],
                    'center': (cx, cy),
                })

        return detections

    def annotate(self, frame, detections):
        """
        Draw bounding boxes and labels on a frame for preview display.

        Args:
            frame: BGR numpy array (will be modified in place).
            detections: list from detect().

        Returns:
            The annotated frame.
        """
        import cv2

        for det in detections:
            x1, y1, x2, y2 = [int(v) for v in det['bbox']]
            label = f"{det['class_name']} {det['confidence']:.0%}"
            color = (0, 0, 255) if 'dangerous' in det.get('status', '') else (0, 255, 0)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        return frame
