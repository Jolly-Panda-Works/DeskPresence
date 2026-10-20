"""Webcam face detection + a cheap head-pose estimate (yaw / pitch).

Uses OpenCV's YuNet detector, which also returns 5 landmarks (eyes, nose,
mouth corners). Yaw/pitch are approximated from where the nose sits relative
to the eyes, normalised by eye distance - accurate enough to tell which
monitor you are facing after a short calibration.
Falls back to a Haar cascade (presence only, no gaze) if the model is missing.
"""
import logging
import os
import sys
from dataclasses import dataclass

import cv2

log = logging.getLogger(__name__)

MODEL_NAME = "face_detection_yunet_2023mar.onnx"


def _model_path():
    bases = [getattr(sys, "_MEIPASS", ""),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")]
    for b in bases:
        p = os.path.join(b, "assets", MODEL_NAME)
        if os.path.exists(p):
            return p
    return None


@dataclass
class Observation:
    face: bool
    yaw: float = 0.0
    pitch: float = 0.0
    faces: int = 0


class FaceSensor:
    WIDTH = 640

    def __init__(self, camera_index):
        self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera {camera_index}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.last_frame = None
        self.last_box = None
        model = _model_path()
        self.yunet = None
        self.haar = None
        if model and hasattr(cv2, "FaceDetectorYN"):
            self.yunet = cv2.FaceDetectorYN.create(model, "", (320, 320), 0.75, 0.3, 5)
            log.info("Using YuNet face detector")
        else:
            self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            log.warning("YuNet model not found - presence only, gaze disabled")

    @property
    def supports_gaze(self):
        return self.yunet is not None

    def read(self):
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None
        h, w = frame.shape[:2]
        if w != self.WIDTH:
            frame = cv2.resize(frame, (self.WIDTH, int(h * self.WIDTH / w)))
            h, w = frame.shape[:2]
        self.last_frame = frame  # used by the eye tracker and the settings preview

        if self.haar is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.haar.detectMultiScale(gray, 1.2, 5, minSize=(60, 60))
            self.last_box = tuple(int(v) for v in faces[0]) if len(faces) else None
            return Observation(face=len(faces) > 0, faces=len(faces))

        self.yunet.setInputSize((w, h))
        _, faces = self.yunet.detect(frame)
        if faces is None or len(faces) == 0:
            self.last_box = None
            return Observation(face=False)
        f = max(faces, key=lambda r: r[2] * r[3])  # largest face = the user
        self.last_box = tuple(int(v) for v in f[:4])
        rex, rey, lex, ley, nx, ny = f[4:10]
        eye_dist = max(1.0, abs(lex - rex))
        mid_x, mid_y = (rex + lex) / 2, (rey + ley) / 2
        yaw = (nx - mid_x) / eye_dist
        pitch = (ny - mid_y) / eye_dist
        return Observation(face=True, yaw=float(yaw), pitch=float(pitch), faces=len(faces))

    def close(self):
        try:
            self.cap.release()
        except Exception:
            pass


class GazeClassifier:
    """Nearest-centroid classifier with smoothing and a stability requirement."""

    def __init__(self, calibration, stable_seconds):
        self.centroids = {k: tuple(v) for k, v in (calibration or {}).items()}
        self.stable_seconds = stable_seconds
        self._ema = None
        self._candidate = None
        self._since = 0.0
        self.current = None

    @property
    def ready(self):
        return len(self.centroids) >= 2

    def reset(self):
        self._ema = None
        self._candidate = None

    def update(self, yaw, pitch, now):
        """Returns the target name when it newly becomes stable, else None."""
        if not self.ready:
            return None
        if self._ema is None:
            self._ema = (yaw, pitch)
        else:
            a = 0.5
            self._ema = (a * yaw + (1 - a) * self._ema[0], a * pitch + (1 - a) * self._ema[1])
        ey, ep = self._ema
        best = min(self.centroids, key=lambda k: (self.centroids[k][0] - ey) ** 2
                   + 0.5 * (self.centroids[k][1] - ep) ** 2)
        if best != self._candidate:
            self._candidate, self._since = best, now
            return None
        if best != self.current and now - self._since >= self.stable_seconds:
            self.current = best
            return best
        return None
