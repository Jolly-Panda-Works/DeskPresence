"""Phone presence, keyboard/mouse fallback, eye-tracking math, webcam sharing and the network link."""
import socket
import time

import numpy as np

from deskpresence import camshare, eyetrack, network, winapi
from deskpresence.controller import AWAY, PRESENT


class FakePhone:
    def __init__(self, near):
        self.near = near
        self.device_id = "dev"


def run_without_camera(sim, seconds):
    end = sim.clock["t"] + seconds
    while sim.clock["t"] < end:
        sim.clock["t"] += 0.5
        sim.ctrl._process(None, sim.clock["t"])


def test_phone_leaving_means_away_and_coming_back_means_back(sim):
    sim.ctrl.cfg["presence_source"] = "phone"
    sim.ctrl._phone = FakePhone(True)
    run_without_camera(sim, 60)
    assert sim.ctrl.state == PRESENT
    sim.ctrl._phone.near = False
    run_without_camera(sim, 15)
    assert sim.ctrl.state == AWAY
    sim.ctrl._phone.near = True
    run_without_camera(sim, 1)
    assert sim.ctrl.state == PRESENT


def test_both_sources_stay_present_while_phone_is_near(sim):
    sim.ctrl._phone = FakePhone(True)
    sim.run(60, face=False)  # camera sees nobody, but the phone is here
    assert sim.ctrl.state == PRESENT
    sim.ctrl._phone.near = False
    sim.run(15, face=False)
    assert sim.ctrl.state == AWAY


def test_without_any_source_only_long_inactivity_counts(sim, monkeypatch):
    idle = {"s": 30.0}
    monkeypatch.setattr(winapi, "idle_seconds", lambda: idle["s"])
    run_without_camera(sim, 120)
    assert sim.ctrl.state == PRESENT  # 30 s idle is not enough without webcam / phone
    idle["s"] = 5 * 60 + 1
    run_without_camera(sim, 1)
    assert sim.ctrl.state == AWAY
    idle["s"] = 0.2
    run_without_camera(sim, 1)
    assert sim.ctrl.state == PRESENT


def _fake_landmarks(iris_dx=0.0, iris_dy=0.0, closed=False):
    pts = [(0.0, 0.0)] * 478
    pts = list(pts)

    def eye(outer, inner, top, bot, iris, x0, x1):
        y = 100.0
        pts[outer], pts[inner] = (x0, y), (x1, y)
        h = 1.0 if closed else 12.0
        mid = (x0 + x1) / 2
        pts[top], pts[bot] = (mid, y - h), (mid, y + h)
        pts[iris] = (mid + iris_dx, y + iris_dy)
    eye(eyetrack.R_OUT, eyetrack.R_IN, eyetrack.R_TOP, eyetrack.R_BOT, eyetrack.R_IRIS, 100, 160)
    eye(eyetrack.L_OUT, eyetrack.L_IN, eyetrack.L_TOP, eyetrack.L_BOT, eyetrack.L_IRIS, 260, 200)
    return pts


def test_eye_features_follow_the_iris():
    center = eyetrack.eye_features(_fake_landmarks())
    right = eyetrack.eye_features(_fake_landmarks(iris_dx=6))
    down = eyetrack.eye_features(_fake_landmarks(iris_dy=4))
    assert abs(center[0]) < 1e-9 and abs(center[1]) < 1e-9
    assert right[0] > 0.05 and abs(right[1]) < 1e-9   # both eyes agree on "right"
    assert down[1] > 0.03 and abs(down[0]) < 1e-9


def test_blink_is_ignored():
    assert eyetrack.eye_features(_fake_landmarks(closed=True)) is None


def test_gaze_mapper_learns_a_mapping():
    rng = np.random.default_rng(1)
    feats = rng.uniform(-0.2, 0.2, size=(200, 4))
    pts = np.column_stack([960 + 4000 * feats[:, 0], 540 + 3000 * feats[:, 1]])
    mapper, err = eyetrack.GazeMapper.fit(feats, pts)
    assert err < 5
    x, y = mapper.predict(np.array([0.1, -0.05, 0, 0]))
    assert abs(x - 1360) < 15 and abs(y - 390) < 15
    again = eyetrack.GazeMapper(mapper.to_dict())
    assert again.ok and abs(again.predict(np.array([0.1, -0.05, 0, 0]))[0] - x) < 1e-6


def test_one_euro_smooths_jitter():
    f = eyetrack.OneEuro()
    out = [f(np.array([100.0 + (5 if i % 2 else -5), 0.0]), i / 15)[0] for i in range(60)]
    assert max(out[20:]) - min(out[20:]) < 6


def test_camera_app_names():
    assert camshare.app_name(r"NonPackaged\C:#Program Files#Zoom#bin#Zoom.exe") == "Zoom"
    assert camshare.app_name("MSTeams_8wekyb3d8bbwe") == "MSTeams"
    assert camshare.app_name("Microsoft.WindowsCamera_8wekyb3d8bbwe") == "WindowsCamera"
    assert camshare.CameraShare._is_own(r"NonPackaged\C:#Apps#DeskPresence#DeskPresence.exe")
    assert not camshare.CameraShare._is_own(r"NonPackaged\C:#Program Files#Zoom#bin#Zoom.exe")
    assert camshare.in_use((5, 0)) and camshare.in_use((9, 3)) and not camshare.in_use((3, 9))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait(cond, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_link_end_to_end():
    port = _free_port()
    got = []
    desktop = network.Link("desktop", port, "secret", on_message=got.append)
    desktop.start()
    try:
        assert _wait(lambda: network.test_connection("127.0.0.1", port, "secret") == "ok")
        assert network.test_connection("127.0.0.1", port, "wrong") == "bad_token"
        laptop_got = []
        laptop = network.Link("laptop", port, "secret", host="127.0.0.1", on_message=laptop_got.append)
        laptop.start()
        try:
            assert _wait(lambda: desktop.connected and laptop.connected)
            desktop.send({"type": "away"})
            laptop.send({"type": "notification", "title": "hi"})
            assert _wait(lambda: laptop_got and got)
            assert laptop_got[0]["type"] == "away" and got[0]["title"] == "hi"
        finally:
            laptop.stop()
    finally:
        desktop.stop()
    assert network.test_connection("127.0.0.1", _free_port(), "secret") == "unreachable"
