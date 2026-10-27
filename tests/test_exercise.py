"""Desk exercises: repetitions are counted from synthetic body landmarks, wrong form is corrected."""
import math

from deskpresence import controller, exercise
from deskpresence.exercise import (L_EAR, L_ELBOW, L_SHOULDER, L_WRIST, NOSE, R_EAR, R_ELBOW, R_SHOULDER,
                                   R_WRIST, Session)


def body(head_tilt=0.0, lean=0.0, shrug=0.0, arms=0.0, rise=0.0, twist=0.0, lift_one_shoulder=0.0,
         bent_elbows=False, one_arm=False):
    """A person facing the camera. Angles in degrees, distances in shoulder widths (100 px)."""
    w = 100.0 * (1.0 - abs(twist))            # turning narrows the shoulder line
    cx, sy = 320.0, 300.0 - rise * 100.0
    a = math.radians(lean)
    dx, dy = math.cos(a) * w / 2, math.sin(a) * w / 2
    lm = [(0.0, 0.0, 0.0, 0.0)] * 33
    lm = list(lm)
    # the person's left side is on the image's right; leaning to the left lowers the left shoulder
    ls = (cx + dx, sy + dy - lift_one_shoulder * 100, -twist * 100, 0.99)
    rs = (cx - dx, sy - dy, twist * 100, 0.99)
    ls = (ls[0], ls[1] - shrug * 60, ls[2], ls[3])
    rs = (rs[0], rs[1] - shrug * 60, rs[2], rs[3])
    lm[L_SHOULDER], lm[R_SHOULDER] = ls, rs
    nose = (cx, sy - 110, -50.0, 0.99)
    lm[NOSE] = nose
    h = math.radians(head_tilt + lean)
    ex, ey = math.cos(h) * 35, math.sin(h) * 35
    lm[L_EAR] = (nose[0] + ex, nose[1] + 10 + ey, 0.0, 0.99)
    lm[R_EAR] = (nose[0] - ex, nose[1] + 10 - ey, 0.0, 0.99)
    for s_, e_, w_, side in ((ls, L_ELBOW, L_WRIST, 1), (rs, R_ELBOW, R_WRIST, -1)):
        up = 0.0 if (one_arm and side < 0) else arms
        top = nose[1] - 80
        ey_ = s_[1] - up * (s_[1] - top) * 0.5 + (1 - up) * 60
        wy = s_[1] - up * (s_[1] - top) * 1.1 + (1 - up) * 120
        bend = 40 if bent_elbows else 0
        lm[e_] = (s_[0] + side * (15 + bend), ey_, 0.0, 0.99)
        lm[w_] = (s_[0] + side * 10, wy, 0.0, 0.99)
    return lm


class Feeder:
    def __init__(self, keys, reps=3):
        self.s = Session(keys, reps)
        self.t = 0.0
        self.messages = []

    def frames(self, n=15, **pose):
        for _ in range(n):
            self.t += 1 / 15
            snap = self.s.update(body(**pose), self.t)
            self.messages.append(snap["message"])
        return snap

    def settle(self):
        return self.frames(exercise.BASELINE_FRAMES + 2)


def test_neck_tilts_are_counted_and_need_both_sides():
    f = Feeder(["neck_tilt"])
    f.settle()
    f.frames(head_tilt=25)
    snap = f.frames()
    assert snap["count"] == 0 and snap["message"] in ("ex.other_side", "ex.do.neck_tilt")
    f.frames(head_tilt=-25)
    snap = f.frames()
    assert snap["count"] == 1 and "ex.cheer.1" in f.messages


def test_a_small_tilt_asks_for_more():
    f = Feeder(["neck_tilt"])
    f.settle()
    f.frames(head_tilt=12)
    f.frames()
    assert "ex.fix.more.neck_tilt" in f.messages and f.s.count == 0


def test_moving_the_shoulders_during_the_neck_stretch_is_corrected():
    f = Feeder(["neck_tilt"])
    f.settle()
    f.frames(lean=15)                      # the whole upper body leans instead of the head
    assert "ex.fix.shoulders_level" in f.messages


def test_shrugs():
    f = Feeder(["shoulder_shrug"])
    f.settle()
    for _ in range(2):
        f.frames(shrug=1.0)
        f.frames()
    assert f.s.count == 2
    f.frames(shrug=1.0, lift_one_shoulder=0.3)
    assert "ex.fix.both_shoulders" in f.messages


def test_arm_raises_need_straight_arms_and_both_hands():
    f = Feeder(["arm_raise"])
    f.settle()
    f.frames(arms=1.0)
    f.frames()
    assert f.s.count == 1
    f.frames(arms=1.0, one_arm=True)
    assert "ex.fix.both_arms" in f.messages
    f.frames()
    f.frames(arms=1.0, bent_elbows=True)
    assert "ex.fix.straight_arms" in f.messages


def test_side_bends_and_twists():
    f = Feeder(["side_bend"])
    f.settle()
    for lean in (20, -20):
        f.frames(lean=lean, head_tilt=-lean)
        f.frames()
    assert f.s.count == 1
    f = Feeder(["torso_twist"])
    f.settle()
    for tw in (0.35, -0.35):
        f.frames(twist=tw)
        f.frames()
    assert f.s.count == 1


def test_chair_squats_count_and_the_head_may_leave_the_picture():
    f = Feeder(["chair_squat"])
    f.settle()
    f.frames(30, rise=0.8)
    f.frames(30)
    assert f.s.count == 1
    f.frames(10, rise=0.4)                  # rising ...
    for _ in range(20):                     # ... and out of the top of the picture
        f.t += 1 / 15
        f.s.update(None, f.t)
    f.frames(30)
    assert f.s.count == 2


def test_too_fast_squats_are_not_counted():
    f = Feeder(["chair_squat"])
    f.settle()
    f.frames(5, rise=0.8)
    f.frames(5)
    assert f.s.count == 0 and "ex.fix.slower" in f.messages


def test_nobody_in_the_picture():
    s = Session(["neck_tilt"], 3)
    assert s.update(None, 1.0)["message"] == "ex.fix.visible"


def test_session_moves_on_and_finishes():
    f = Feeder(["shoulder_shrug", "arm_raise"], reps=1)
    f.settle()
    f.frames(shrug=1.0)
    f.frames()
    assert f.s.snapshot()["message"] == "ex.move_done"
    f.frames(int(exercise.NEXT_PAUSE * 15) + 2)
    assert f.s.index == 1
    f.s.skip()
    assert f.s.done and f.s.snapshot()["message"] == "ex.all_done"


def test_exercise_reminder_opens_the_window(sim, monkeypatch):
    monkeypatch.setattr(exercise, "available", lambda: True)
    ctrl = sim.ctrl
    ctrl.cfg["camera_mode"] = "always"
    ctrl.cfg["exercise"]["every_minutes"] = 1
    sim.run(61, face=True)
    assert ctrl.exercise is not None and ("exercise",) in sim.ui.log
    assert ctrl.camera_wanted
    sim.run(120, face=False)                # out of the picture while exercising: not "away"
    assert ctrl.state == controller.PRESENT
    ctrl.stop_exercise(later=True)
    assert ctrl.exercise is None
    assert 0 < ctrl.cfg["exercise"]["every_minutes"] * 60 - ctrl.exercise_elapsed <= 10 * 60


def test_exercise_reminder_can_ask_first(sim, monkeypatch):
    monkeypatch.setattr(exercise, "available", lambda: True)
    ctrl = sim.ctrl
    ctrl.cfg["camera_mode"] = "always"
    ctrl.cfg["exercise"].update(every_minutes=1, auto_open=False)
    sim.run(61, face=True)
    assert ctrl.exercise is None and sim.ui.pending
    sim.ui.pending(True)
    assert ctrl.exercise is not None
