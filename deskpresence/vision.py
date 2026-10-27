"""Webcam face detection + a cheap head-pose estimate (yaw / pitch).

Uses OpenCV's YuNet detector, which also returns 5 landmarks (eyes, nose,
mouth corners). Yaw/pitch are approximated from where the nose sits relative
to the eyes, normalised by eye distance - accurate enough to tell which
monitor you are facing after a short calibration.
Falls back to a Haar cascade (presence only, no gaze) if the model is missing.

A face is not needed to count as present: when no face is found (head turned away, looking
down at the phone, leaning back), MediaPipe's object detector looks for a *person* - head,
shoulders and body from any side. With SFace (OpenCV Zoo) the face can also be compared with
the owner's saved face, so only the owner turns the PC back on.
"""
import logging
import os
import sys
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)

MODEL_NAME = "face_detection_yunet_2023mar.onnx"
PERSON_MODEL = "efficientdet_lite0.tflite"
IDENTITY_MODEL = "face_recognition_sface_2021dec.onnx"
PERSON_SCORE = 0.35
OWNER_MATCH = 0.36   # SFace cosine similarity: above this it is the same person (OpenCV's threshold 0.363)


def _model_path(name=MODEL_NAME):
    bases = [getattr(sys, "_MEIPASS", ""),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")]
    for b in bases:
        p = os.path.join(b, "assets", name)
        if os.path.exists(p):
            return p
    return None


@dataclass
class Observation:
    face: bool
    yaw: float = 0.0
    pitch: float = 0.0
    faces: int = 0
    person: bool = None   # someone is there, face visible or not (None = same as face)
    owner: bool = None    # the face is the owner's (None = not checked)

    def __post_init__(self):
        if self.person is None:
            self.person = self.face


class PersonDetector:
    """MediaPipe object detector limited to the "person" class: works from the side and from behind."""

    def __init__(self, path):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        self._mp = mp
        opts = vision.ObjectDetectorOptions(
            base_options=BaseOptions(model_asset_path=path),
            running_mode=vision.RunningMode.IMAGE,
            score_threshold=PERSON_SCORE,
            category_allowlist=["person"],
            max_results=3,
        )
        self._det = vision.ObjectDetector.create_from_options(opts)

    def detect(self, frame_bgr):
        """Returns the largest person box (x, y, w, h) or None."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        res = self._det.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        boxes = [(d.bounding_box.origin_x, d.bounding_box.origin_y, d.bounding_box.width, d.bounding_box.height)
                 for d in res.detections]
        return max(boxes, key=lambda b: b[2] * b[3]) if boxes else None

    def close(self):
        try:
            self._det.close()
        except Exception:
            pass


def owner_score(feature, owner_faces):
    """Best cosine similarity between a face feature and the saved owner features."""
    if feature is None or not owner_faces:
        return 0.0
    f = np.asarray(feature, dtype=np.float32).ravel()
    f = f / max(1e-9, float(np.linalg.norm(f)))
    best = 0.0
    for o in owner_faces:
        o = np.asarray(o, dtype=np.float32).ravel()
        best = max(best, float(f @ o) / max(1e-9, float(np.linalg.norm(o))))
    return best


class FaceSensor:
    WIDTH = 640

    def __init__(self, camera_index, owner_faces=None):
        self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera {camera_index}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.last_frame = None
        self.last_box = None
        self.last_feature = None      # SFace feature of the largest face (when identity is on)
        self.owner_faces = owner_faces or []
        self.check_owner = False      # the controller turns this on while it needs to know who it is
        model = _model_path()
        self.yunet = None
        self.haar = None
        if model and hasattr(cv2, "FaceDetectorYN"):
            self.yunet = cv2.FaceDetectorYN.create(model, "", (320, 320), 0.75, 0.3, 5)
            log.info("Using YuNet face detector")
        else:
            self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            log.warning("YuNet model not found - presence only, gaze disabled")
        self.person = None
        person_model = _model_path(PERSON_MODEL)
        if person_model:
            try:
                self.person = PersonDetector(person_model)
                log.info("Using the person detector (presence without a visible face)")
            except Exception:
                log.exception("Person detector unavailable - presence needs a visible face")
        self.identity = None
        id_model = _model_path(IDENTITY_MODEL)
        if self.yunet is not None and id_model and hasattr(cv2, "FaceRecognizerSF"):
            try:
                self.identity = cv2.FaceRecognizerSF.create(id_model, "")
            except Exception:
                log.exception("Face recognition unavailable")

    @property
    def supports_identity(self):
        return self.identity is not None

    @property
    def supports_body(self):
        return self.person is not None

    def _person(self, frame):
        if self.person is None:
            return None
        try:
            box = self.person.detect(frame)
        except Exception:
            log.exception("Person detection failed")
            self.person.close()
            self.person = None
            return None
        return tuple(int(v) for v in box) if box else None

    def _identify(self, frame, face_row):
        try:
            aligned = self.identity.alignCrop(frame, face_row)
            return self.identity.feature(aligned).ravel()
        except Exception:
            log.debug("Face feature failed", exc_info=True)
            return None

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
            if len(faces):
                self.last_box = tuple(int(v) for v in faces[0])
                return Observation(face=True, faces=len(faces))
            self.last_box = self._person(frame)
            return Observation(face=False, person=self.last_box is not None)

        self.yunet.setInputSize((w, h))
        _, faces = self.yunet.detect(frame)
        self.last_feature = None
        if faces is None or len(faces) == 0:
            # no face: maybe the head is turned away - look for the person instead
            self.last_box = self._person(frame)
            return Observation(face=False, person=self.last_box is not None)
        f = max(faces, key=lambda r: r[2] * r[3])  # largest face = the user
        self.last_box = tuple(int(v) for v in f[:4])
        owner = None
        if self.identity is not None and self.check_owner:
            self.last_feature = self._identify(frame, f)
            if self.owner_faces:
                # the owner may not be the largest face (someone leaning in over the shoulder)
                others = (self._identify(frame, r) for r in faces if r[2] * r[3] < f[2] * f[3])
                owner = any(owner_score(x, self.owner_faces) >= OWNER_MATCH
                            for x in (self.last_feature, *others))
        rex, rey, lex, ley, nx, ny = f[4:10]
        eye_dist = max(1.0, abs(lex - rex))
        mid_x, mid_y = (rex + lex) / 2, (rey + ley) / 2
        yaw = (nx - mid_x) / eye_dist
        pitch = (ny - mid_y) / eye_dist
        return Observation(face=True, yaw=float(yaw), pitch=float(pitch), faces=len(faces), owner=owner)

    def close(self):
        try:
            self.cap.release()
        except Exception:
            pass
        if self.person is not None:
            self.person.close()


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
