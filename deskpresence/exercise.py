"""Desk exercises watched by the webcam: counts the repetitions and says when the form is off.

MediaPipe's Pose Landmarker finds 33 body points per frame. Every exercise turns them into one
number (the head's tilt, how high the shoulders are, ...) and a small state machine counts a
repetition when that number goes far enough and comes back. A movement that starts but does not
go far enough, or a body part that does the wrong thing, gives a correction instead.

Everything except PoseTracker is plain Python, so the counting is tested without a webcam.
Landmarks are (x, y, z, visibility) in pixels; y grows downwards, like the image.
"""
import logging
import math
import os
import sys
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MODEL_NAME = "pose_landmarker_lite.task"

NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 2, 5, 7, 8
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = 11, 12, 13, 14, 15, 16
VISIBLE = 0.5
BASELINE_FRAMES = 12     # still frames that tell how you sit normally
NEXT_PAUSE = 2.5         # seconds of "well done" between two exercises
MESSAGE_SECONDS = 2.0    # a message stays on screen at least this long
CHEERS = 4               # ex.cheer.1 .. ex.cheer.4


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


# ------------------------------------------------------------ geometry
def _vis(lm, *ids):
    return all(lm[i][3] >= VISIBLE for i in ids)


def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _width(lm):
    a, b = lm[L_SHOULDER], lm[R_SHOULDER]
    return max(1.0, math.hypot(a[0] - b[0], a[1] - b[1]))


def _roll(a, b):
    """Angle in degrees of the line from b (the person's right side) to a (their left side); 0 = level."""
    return math.degrees(math.atan2(a[1] - b[1], a[0] - b[0]))


def _angle(a, b, c):
    """The angle at b, in degrees (180 = straight)."""
    v1, v2 = (a[0] - b[0], a[1] - b[1]), (c[0] - b[0], c[1] - b[1])
    n = math.hypot(*v1) * math.hypot(*v2)
    if n < 1e-9:
        return 180.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n))
    return math.degrees(math.acos(cos))


# ------------------------------------------------------------ repetition counters
class TwoSided:
    """One repetition = far enough to one side, back, far enough to the other side, back."""

    def __init__(self, far, partial):
        self.far, self.partial = far, partial
        self.neutral = partial * 0.6
        self.reached = set()
        self.out = False
        self.sign = 0
        self.peak = 0.0

    def update(self, m):
        """Returns "rep", "side" (one side done), "partial" (not far enough) or None."""
        sign = 1 if m > 0 else -1
        if abs(m) >= self.neutral:
            event = None
            if self.out and sign != self.sign:  # swung straight over to the other side
                event = self._finish()
            if not self.out:
                self.out, self.sign, self.peak = True, sign, 0.0
            self.peak = max(self.peak, abs(m))
            return event
        return self._finish() if self.out else None

    def _finish(self):
        self.out = False
        if self.peak >= self.far:
            self.reached.add(self.sign)
            if len(self.reached) == 2:
                self.reached.clear()
                return "rep"
            return "side"
        return "partial" if self.peak >= self.partial else None


class UpDown:
    """One repetition = the value rises to `far` and comes back down below `back`."""

    def __init__(self, far, partial, back):
        self.far, self.partial, self.back = far, partial, back
        self.peak = None
        self.went_up_at = None

    def update(self, m, now=0.0):
        """Returns "rep", "partial" or None."""
        if m > self.back:
            if self.peak is None:
                self.peak, self.went_up_at = m, now
            self.peak = max(self.peak, m)
            return None
        if self.peak is None:
            return None
        peak, self.peak = self.peak, None
        if peak >= self.far:
            return "rep"
        return "partial" if peak >= self.partial else None


# ------------------------------------------------------------ the exercises
def _neck(lm, base):
    """Head tilt relative to the shoulders (degrees)."""
    if _vis(lm, L_EAR, R_EAR):
        head = _roll(lm[L_EAR], lm[R_EAR])
    elif _vis(lm, L_EYE, R_EYE):
        head = _roll(lm[L_EYE], lm[R_EYE])
    else:
        return None
    return head - _roll(lm[L_SHOULDER], lm[R_SHOULDER])


def _neck_check(lm, base, m):
    if abs(_roll(lm[L_SHOULDER], lm[R_SHOULDER])) > 10:
        return "ex.fix.shoulders_level"  # the head should move, not the shoulders
    return None


def _shrug(lm, base):
    """How much the shoulders came up towards the ears, as a share of the normal neck height."""
    if not _vis(lm, NOSE):
        return None
    w = base.get("width") or _width(lm)
    neck = (_mid(lm[L_SHOULDER], lm[R_SHOULDER])[1] - lm[NOSE][1]) / w
    if "neck" not in base:
        return neck
    return 1.0 - neck / max(1e-6, base["neck"])


def _shrug_check(lm, base, m):
    if m > 0.1 and abs(lm[L_SHOULDER][1] - lm[R_SHOULDER][1]) / _width(lm) > 0.12:
        return "ex.fix.both_shoulders"
    return None


def _arms_up(lm, base):
    """0 = hands at shoulder height or lower, 1 = both hands above the head (the lower hand counts)."""
    if not _vis(lm, NOSE):
        return None
    w = _width(lm)
    top = lm[NOSE][1] - 0.4 * w        # roughly the top of the head
    shoulder_y = _mid(lm[L_SHOULDER], lm[R_SHOULDER])[1]
    heights = []
    for wrist, elbow in ((L_WRIST, L_ELBOW), (R_WRIST, R_ELBOW)):
        if _vis(lm, wrist):
            y = lm[wrist][1]
        elif _vis(lm, elbow) and lm[elbow][1] < lm[NOSE][1]:
            y = top - 1                # the hand left the picture above the head
        else:
            y = shoulder_y + w         # not seen: hanging down
        heights.append((shoulder_y - y) / max(1.0, shoulder_y - top))
    return max(0.0, min(1.2, min(heights)))


def _arms_check(lm, base, m):
    w = _width(lm)
    hands_up = [_vis(lm, wr) and lm[wr][1] < lm[NOSE][1] - 0.2 * w for wr in (L_WRIST, R_WRIST)]
    if any(hands_up) and not all(hands_up):
        return "ex.fix.both_arms"
    if m > 0.7:
        for s, e, wr in ((L_SHOULDER, L_ELBOW, L_WRIST), (R_SHOULDER, R_ELBOW, R_WRIST)):
            if _vis(lm, s, e, wr) and _angle(lm[s], lm[e], lm[wr]) < 140:
                return "ex.fix.straight_arms"
    return None


def _side_bend(lm, base):
    """How far the upper body leans sideways: the shoulder line's tilt (degrees)."""
    return _roll(lm[L_SHOULDER], lm[R_SHOULDER])


def _side_check(lm, base, m):
    if "width" in base and _width(lm) < 0.75 * base["width"]:
        return "ex.fix.face_forward"  # turning instead of bending
    return None


def _twist(lm, base):
    """Rotation of the upper body: depth difference of the shoulders, shown as the narrowing shoulder line."""
    w0 = base.get("width")
    w = _width(lm)
    dz = (lm[L_SHOULDER][2] - lm[R_SHOULDER][2]) / w
    if not w0:
        return 0.0
    turn = max(0.0, 1.0 - w / w0)      # 0 = facing the camera, ~0.3 = a good twist
    return math.copysign(turn, dz) if abs(dz) > 0.05 else 0.0


def _twist_check(lm, base, m):
    if "nose_x" in base and abs(m) > 0.1:
        # the head should turn with the body, not stay behind
        mid = _mid(lm[L_SHOULDER], lm[R_SHOULDER])[0]
        if abs(lm[NOSE][0] - mid) / _width(lm) > 0.9:
            return "ex.fix.head_with_body"
    return None


def _squat(lm, base):
    """How far the shoulders rose above the sitting height, in shoulder widths."""
    w0 = base.get("width") or _width(lm)
    y = _mid(lm[L_SHOULDER], lm[R_SHOULDER])[1]
    if "shoulder_y" not in base:
        return 0.0
    return (base["shoulder_y"] - y) / w0


@dataclass
class Move:
    key: str
    two_sided: bool
    far: float
    partial: float
    metric: object
    check: object = None
    back: float = 0.0          # UpDown only
    min_seconds: float = 0.0   # quicker repetitions get "slower"
    needs: tuple = (L_SHOULDER, R_SHOULDER)
    lost_up: bool = False      # squats: the head leaving the top of the picture means "up"
    extra: dict = field(default_factory=dict)

    def counter(self):
        if self.two_sided:
            return TwoSided(self.far, self.partial)
        return UpDown(self.far, self.partial, self.back)


MOVES = {
    "neck_tilt": Move("neck_tilt", True, 18.0, 9.0, _neck, _neck_check),
    "shoulder_shrug": Move("shoulder_shrug", False, 0.22, 0.12, _shrug, _shrug_check, back=0.06,
                           needs=(NOSE, L_SHOULDER, R_SHOULDER)),
    "arm_raise": Move("arm_raise", False, 1.0, 0.6, _arms_up, _arms_check, back=0.2,
                      needs=(NOSE, L_SHOULDER, R_SHOULDER)),
    "side_bend": Move("side_bend", True, 14.0, 7.0, _side_bend, _side_check),
    "torso_twist": Move("torso_twist", True, 0.25, 0.12, _twist, _twist_check),
    "chair_squat": Move("chair_squat", False, 0.6, 0.3, _squat, back=0.15, min_seconds=1.5, lost_up=True),
}
ORDER = tuple(MOVES)


# ------------------------------------------------------------ a session: several exercises in a row
class Session:
    """Runs the chosen exercises one after another. update() is fed the landmarks of every frame."""

    def __init__(self, keys, reps):
        self.keys = [k for k in keys if k in MOVES] or list(ORDER)
        self.reps = max(1, int(reps))
        self.index = 0
        self.done = False
        self.message, self.tone, self._message_at = "ex.get_ready", "info", -1e9
        self._cheer = 0
        self._start(0.0)

    @property
    def move(self):
        return MOVES[self.keys[self.index]]

    def _start(self, now):
        self.count = 0
        self.base = {}
        self._baseline = []
        self._counter = self.move.counter()
        self._next_at = None
        self._last_up_lost = None
        self.started_at = now

    def _say(self, key, tone, now, force=False):
        """Corrections and cheers stay a moment, so they can be read; "info" never replaces them early."""
        if not force and tone == "info" and now - self._message_at < MESSAGE_SECONDS and self.tone != "info":
            return
        self.message, self.tone = key, tone
        if tone != "info":
            self._message_at = now

    def skip(self, now=0.0):
        self._advance(now)

    def _advance(self, now):
        if self.index + 1 >= len(self.keys):
            self.done = True
            self._say("ex.all_done", "good", now, force=True)
            return
        self.index += 1
        self._start(now)
        self._say("ex.get_ready", "info", now, force=True)

    def update(self, lm, now):
        """lm: 33 landmarks or None (nobody seen)."""
        if self.done:
            return self.snapshot()
        if self._next_at is not None:          # short "well done" pause between exercises
            if now >= self._next_at:
                self._advance(now)
            return self.snapshot()
        mv = self.move
        if lm is None or not _vis(lm, *mv.needs):
            if mv.lost_up and self.base and self._last_up_lost is not None:
                lm = None                      # standing up: the head left the picture
                m = mv.far
            else:
                self._say("ex.fix.visible", "fix", now)
                return self.snapshot()
        else:
            if not self.base:
                return self._learn_baseline(lm, now)
            m = mv.metric(lm, self.base)
            if m is None:
                self._say("ex.fix.visible", "fix", now)
                return self.snapshot()
            self._last_up_lost = now if mv.lost_up and m > mv.partial else None
        if mv.two_sided:
            event = self._counter.update(m)
        else:
            event = self._counter.update(m, now)
        if lm is not None and mv.check:
            fix = mv.check(lm, self.base, m)
            if fix:
                self._say(fix, "fix", now)
        if event == "rep":
            up_at = getattr(self._counter, "went_up_at", None)
            if mv.min_seconds and up_at is not None and now - up_at < mv.min_seconds:
                self._say("ex.fix.slower", "fix", now, force=True)
            else:
                self.count += 1
                self._cheer = self._cheer % CHEERS + 1
                self._say(f"ex.cheer.{self._cheer}", "good", now, force=True)
            if self.count >= self.reps:
                self._next_at = now + NEXT_PAUSE
                self._say("ex.move_done", "good", now, force=True)
        elif event == "side":
            self._say("ex.other_side", "info", now, force=True)
        elif event == "partial":
            self._say(f"ex.fix.more.{mv.key}", "fix", now, force=True)
        elif self.tone == "info" or now - self._message_at >= MESSAGE_SECONDS:
            self._say(f"ex.do.{mv.key}", "info", now)
        return self.snapshot()

    def _learn_baseline(self, lm, now):
        """A few still frames of how you sit, before counting."""
        self._say("ex.sit_still", "info", now)
        self._baseline.append(lm)
        if len(self._baseline) < BASELINE_FRAMES:
            return self.snapshot()
        frames = self._baseline
        width = sorted(_width(f) for f in frames)[len(frames) // 2]
        base = {"width": width,
                "shoulder_y": sorted(_mid(f[L_SHOULDER], f[R_SHOULDER])[1] for f in frames)[len(frames) // 2],
                "nose_x": sorted(f[NOSE][0] for f in frames)[len(frames) // 2]}
        if self.move.key == "shoulder_shrug":
            base["neck"] = sorted(_shrug(f, {"width": width}) for f in frames)[len(frames) // 2]
        self.base = base
        self._say(f"ex.do.{self.move.key}", "info", now, force=True)
        return self.snapshot()

    def snapshot(self):
        return {"move": self.move.key, "index": self.index, "total": len(self.keys), "count": self.count,
                "target": self.reps, "message": self.message, "tone": self.tone, "done": self.done}


# ------------------------------------------------------------ MediaPipe
class PoseTracker:
    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        self._mp = mp
        opts = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path()),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
        )
        self._pose = vision.PoseLandmarker.create_from_options(opts)
        self._last_ts = 0

    def landmarks(self, frame_bgr, t_seconds):
        """33 (x, y, z, visibility) in pixels, or None when nobody is seen."""
        import cv2
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        ts = max(self._last_ts + 1, int(t_seconds * 1000))
        self._last_ts = ts
        res = self._pose.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), ts)
        if not res.pose_landmarks:
            return None
        return [(p.x * w, p.y * h, p.z * w, p.visibility if p.visibility is not None else 1.0)
                for p in res.pose_landmarks[0]]

    def close(self):
        try:
            self._pose.close()
        except Exception:
            pass
