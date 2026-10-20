"""Webcam eye tracking: moves the cursor to where you look.

MediaPipe's Face Landmarker finds 478 face points including both irises. From them we build
a small feature vector per frame:

  h, v    where the irises sit inside the eyes (horizontal / vertical, averaged over both eyes)
  fx, fy  head direction from the face transformation matrix

A short calibration (look at dots on every monitor) fits a regularised quadratic regression
from those features to screen coordinates. A One Euro filter smooths the result.
A webcam is far less precise than a real eye tracker: expect the cursor to land within a few
centimetres of where you look, which is enough to bring it to the right place and finish with
the mouse.
"""
import logging
import math
import os
import sys

import numpy as np

log = logging.getLogger(__name__)

MODEL_NAME = "face_landmarker.task"

# landmark indices (MediaPipe face mesh with iris refinement)
R_OUT, R_IN, R_TOP, R_BOT, R_IRIS = 33, 133, 159, 145, 468
L_IN, L_OUT, L_TOP, L_BOT, L_IRIS = 362, 263, 386, 374, 473
BLINK_RATIO = 0.13


def model_path():
    for base in (getattr(sys, "_MEIPASS", ""), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")):
        p = os.path.join(base, "assets", MODEL_NAME)
        if os.path.exists(p):
            return p
    return None


def available():
    if not model_path():
        return False
    try:
        import mediapipe  # noqa: F401
        return True
    except Exception:
        return False


def eye_features(pts, matrix=None):
    """pts: sequence of (x, y) in image coordinates. Returns np.array([h, v, fx, fy]) or None on a blink."""
    def p(i):
        return np.asarray(pts[i][:2], dtype=float)

    feats_h, feats_v = [], []
    for outer, inner, top, bot, iris in ((R_OUT, R_IN, R_TOP, R_BOT, R_IRIS), (L_OUT, L_IN, L_TOP, L_BOT, L_IRIS)):
        a, b = p(outer), p(inner)
        width = np.linalg.norm(b - a)
        if width < 1e-6:
            return None
        if np.linalg.norm(p(bot) - p(top)) / width < BLINK_RATIO:
            return None  # blinking: the iris position is meaningless
        axis = (b - a) / width
        normal = np.array([-axis[1], axis[0]])
        rel = p(iris) - (a + b) / 2
        feats_h.append(float(rel @ axis) / width)
        feats_v.append(float(rel @ normal) / width)
    # both eyes are measured from the outer to the inner corner, so the two eyes' axes (and
    # their normals) point in opposite directions -> flip the left eye so both grow the same way
    h = (feats_h[0] - feats_h[1]) / 2
    v = (feats_v[0] - feats_v[1]) / 2
    fx = fy = 0.0
    if matrix is not None:
        m = np.asarray(matrix)
        fx, fy = float(m[0, 2]), float(m[1, 2])
    return np.array([h, v, fx, fy])


def _phi(f):
    f = np.atleast_2d(f)
    h, v, fx, fy = f[:, 0], f[:, 1], f[:, 2], f[:, 3]
    return np.column_stack([np.ones(len(f)), h, v, fx, fy, h * h, v * v, h * v, h * fx, v * fy, fx * fx, fy * fy])


class GazeMapper:
    """Features -> screen point, fitted from calibration samples."""

    def __init__(self, data=None):
        self.ok = False
        if data:
            try:
                self.mean = np.array(data["mean"])
                self.std = np.array(data["std"])
                self.wx = np.array(data["wx"])
                self.wy = np.array(data["wy"])
                self.ok = True
            except (KeyError, ValueError):
                self.ok = False

    @classmethod
    def fit(cls, features, points, ridge=1e-3):
        X = _phi(np.asarray(features, dtype=float))
        mean, std = X.mean(axis=0), X.std(axis=0)
        mean[0], std[0] = 0.0, 1.0
        std[std < 1e-9] = 1.0
        Xn = (X - mean) / std
        P = np.asarray(points, dtype=float)
        A = Xn.T @ Xn + ridge * len(Xn) * np.eye(Xn.shape[1])
        A[0, 0] -= ridge * len(Xn)  # don't shrink the intercept
        wx = np.linalg.solve(A, Xn.T @ P[:, 0])
        wy = np.linalg.solve(A, Xn.T @ P[:, 1])
        m = cls()
        m.mean, m.std, m.wx, m.wy, m.ok = mean, std, wx, wy, True
        err = np.hypot(Xn @ wx - P[:, 0], Xn @ wy - P[:, 1])
        return m, float(np.median(err))

    def to_dict(self):
        return {"mean": self.mean.tolist(), "std": self.std.tolist(), "wx": self.wx.tolist(), "wy": self.wy.tolist()}

    def predict(self, f):
        x = ((_phi(f) - self.mean) / self.std)[0]
        return float(x @ self.wx), float(x @ self.wy)


class OneEuro:
    """One Euro filter (Casiez et al.): smooth when still, responsive when moving."""

    def __init__(self, min_cutoff=0.6, beta=0.01, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        x = np.asarray(x, dtype=float)
        if self.t is None or t <= self.t:
            self.x, self.dx, self.t = x, np.zeros_like(x), t
            return x
        dt = t - self.t
        dx = (x - self.x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * float(np.linalg.norm(self.dx))
        a = self._alpha(cutoff, dt)
        self.x = a * x + (1 - a) * self.x
        self.t = t
        return self.x

    def reset(self):
        self.x = self.dx = self.t = None


class EyeTracker:
    def __init__(self):
        from mediapipe.tasks.python import BaseOptions, vision
        import mediapipe as mp
        self._mp = mp
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path()),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_facial_transformation_matrixes=True,
        )
        self._lm = vision.FaceLandmarker.create_from_options(opts)
        self._last_ts = 0

    def features(self, frame_bgr, t_seconds):
        import cv2
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        ts = max(self._last_ts + 1, int(t_seconds * 1000))
        self._last_ts = ts
        res = self._lm.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), ts)
        if not res.face_landmarks:
            return None
        pts = [(lm.x * w, lm.y * h) for lm in res.face_landmarks[0]]
        matrix = res.facial_transformation_matrixes[0] if res.facial_transformation_matrixes else None
        return eye_features(pts, matrix)

    def close(self):
        try:
            self._lm.close()
        except Exception:
            pass
