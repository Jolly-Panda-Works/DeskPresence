"""Interval mode (webcam only opens for a look), body presence and "only me" owner recognition."""
from deskpresence import controller, winapi
from deskpresence.controller import AWAY, PRESENT
from deskpresence.vision import Observation, owner_score


def tick(sim, seconds, obs=None):
    """obs: None = the webcam is closed, else a callable returning the observation for this frame."""
    end = sim.clock["t"] + seconds
    while sim.clock["t"] < end:
        sim.clock["t"] += 0.5
        sim.ctrl._process(obs() if obs and sim.ctrl.camera_wanted else None, sim.clock["t"])


def nobody():
    return Observation(face=False)


def me_from_behind():
    return Observation(face=False, person=True)


def test_interval_mode_keeps_the_webcam_off_between_looks(sim):
    ctrl = sim.ctrl
    assert ctrl.interval_mode
    tick(sim, 1, me_from_behind)            # the first look sees you ...
    assert ctrl.state == PRESENT and not ctrl.camera_wanted   # ... and the webcam goes off
    tick(sim, 2 * 60, me_from_behind)
    assert not ctrl.camera_wanted and ctrl.state == PRESENT
    tick(sim, 70, me_from_behind)           # 3 minutes later: the next look
    assert not ctrl.camera_wanted and ctrl.state == PRESENT


def test_a_look_that_sees_nobody_means_away(sim):
    ctrl = sim.ctrl
    tick(sim, 1, me_from_behind)
    tick(sim, 3 * 60 + 1, nobody)           # the next look starts and sees nobody
    assert ctrl.camera_wanted
    tick(sim, 12, nobody)                   # away_seconds (10) without seeing anyone
    assert ctrl.state == AWAY
    assert not ctrl.camera_wanted           # away: the webcam is off between short looks


def test_while_away_short_looks_notice_you_are_back(sim):
    ctrl = sim.ctrl
    tick(sim, 1, me_from_behind)
    tick(sim, 3 * 60 + 40, nobody)
    assert ctrl.state == AWAY
    tick(sim, ctrl.cfg["away_check_seconds"] + 5, me_from_behind)
    assert ctrl.state == PRESENT


def test_typing_skips_the_look(sim, monkeypatch):
    monkeypatch.setattr(winapi, "idle_seconds", lambda: 2.0)
    tick(sim, 10 * 60, nobody)
    assert sim.ctrl.state == PRESENT and not sim.ctrl.camera_wanted


def test_turning_the_head_away_is_not_leaving(sim):
    sim.ctrl.cfg["camera_mode"] = "always"
    tick(sim, 60, me_from_behind)
    assert sim.ctrl.state == PRESENT
    sim.ctrl.cfg["presence_by"] = "face"   # the old rule: no face = away
    tick(sim, 30, me_from_behind)
    assert sim.ctrl.state == AWAY


def test_always_mode_never_closes_the_webcam(sim):
    sim.ctrl.cfg["camera_mode"] = "always"
    tick(sim, 1, me_from_behind)
    assert sim.ctrl.camera_wanted


OWNER = [[1.0, 0.0, 0.0]]


def owner_setup(sim):
    sim.ctrl.cfg.update(camera_mode="always", owner_only=True, owner_faces=OWNER)
    tick(sim, 30, nobody)
    assert sim.ctrl.state == AWAY and sim.ctrl.owner_lock


def test_a_stranger_does_not_turn_it_back_on(sim):
    owner_setup(sim)
    tick(sim, 10, lambda: Observation(face=True, owner=False))
    assert sim.ctrl.state == AWAY
    tick(sim, 2, lambda: Observation(face=True, owner=True))
    assert sim.ctrl.state == PRESENT


def test_a_stranger_on_the_keyboard_gets_dark_screens(sim, monkeypatch):
    owner_setup(sim)
    offs = []
    monkeypatch.setattr(winapi, "monitors_off", lambda: offs.append(1))
    sim.ctrl.cfg["turn_off_monitors"] = True
    monkeypatch.setattr(winapi, "idle_seconds", lambda: 0.2)
    tick(sim, 10, lambda: Observation(face=True, owner=False))
    assert sim.ctrl.state == AWAY and offs


def test_without_a_saved_face_input_still_wakes(sim, monkeypatch):
    sim.ctrl.cfg.update(camera_mode="always", owner_only=True, owner_faces=[])
    tick(sim, 30, nobody)
    monkeypatch.setattr(winapi, "idle_seconds", lambda: 0.2)
    tick(sim, 1, nobody)
    assert sim.ctrl.state == PRESENT


class FakeSensor:
    supports_identity = True
    owner_faces = []
    last_feature = [0.0, 1.0, 0.0]


def test_teaching_the_owner_face(sim):
    ctrl = sim.ctrl
    ctrl.sensor = FakeSensor()
    done = []
    ctrl.teach_owner(done.append)
    assert ctrl.camera_wanted
    end = sim.clock["t"] + controller.ENROLL_SECONDS + controller.CAMERA_WARMUP + 1
    while sim.clock["t"] < end and ctrl._enroll is not None:
        sim.clock["t"] += 0.5
        ctrl._enroll_step(Observation(face=True, faces=1), sim.clock["t"])
    assert ctrl._enroll is None and done and done[0] >= 5
    assert ctrl.cfg["owner_faces"] and ctrl.sensor.owner_faces == ctrl.cfg["owner_faces"]
    ctrl.sensor = None


def test_owner_score():
    assert owner_score([2.0, 0.0], [[1.0, 0.0]]) > 0.99
    assert owner_score([0.0, 1.0], [[1.0, 0.0]]) < 0.01
    assert owner_score(None, [[1.0, 0.0]]) == 0.0
