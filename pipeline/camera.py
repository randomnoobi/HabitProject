"""
pipeline/camera.py — Image / Footage input stage.

Chart stage: "Image/footage"

Reads frames from one of:
  1. A webcam (live)
  2. A video file
  3. A single image (for testing)

Returns numpy frames (BGR, as OpenCV expects).
"""

import cv2
from pipeline.config import CAMERA_INDEX, VIDEO_SOURCE


class Camera:
    """Wraps OpenCV VideoCapture for webcam or video file input."""

    def __init__(self, source=None):
        """
        Args:
            source: Path to video/image file, or None for webcam.
        """
        self.source = source or VIDEO_SOURCE or CAMERA_INDEX
        self.cap = None
        self._is_image = False

    def open(self):
        """Open the video source. Returns True on success."""
        if isinstance(self.source, str) and self.source.lower().endswith(
            ('.png', '.jpg', '.jpeg', '.bmp')
        ):
            self._is_image = True
            self._frame = cv2.imread(self.source)
            return self._frame is not None

        self.cap = cv2.VideoCapture(
            self.source if isinstance(self.source, str) else int(self.source)
        )
        if not self.cap.isOpened():
            print(f'  [camera] Failed to open: {self.source}')
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f'  [camera] Opened: {self.source}  ({w}x{h})')
        return True

    def read(self):
        """Read one frame. Returns (ok, frame) like cv2.VideoCapture."""
        if self._is_image:
            return (self._frame is not None), self._frame
        if self.cap is None:
            return False, None
        return self.cap.read()

    def release(self):
        """Release the video source."""
        if self.cap:
            self.cap.release()

    @property
    def resolution(self):
        """Return (width, height) of the source."""
        if self._is_image and self._frame is not None:
            h, w = self._frame.shape[:2]
            return w, h
        if self.cap:
            return (
                int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            )
        return 0, 0
