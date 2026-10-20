"""Phone-call detection, webcam hand-over decisions and the eye-control toggle."""
from deskpresence import calls, camshare
from deskpresence.camshare import Lend


def test_call_phrases():
    assert calls.is_call_text(["Mom", "Incoming call"])
    assert calls.is_call_text(["مامان", "تماس ورودی"])
    assert not calls.is_call_text(["Mom", "Missed call"])
    assert not calls.is_call_text(["Ali", "call me when you can"])  # a text message, not a call
    assert not calls.is_call_text(["Ali", "تماس بگیر"])


def test_exe_of_registry_keys():
    assert camshare.exe_of_key(r"NonPackaged\C:#Program Files#Zoom#bin#Zoom.exe") == "zoom.exe"
    assert camshare.exe_of_key("Microsoft.WindowsCamera_8wekyb3d8bbwe") == "windowscamera.exe"
    assert camshare.exe_of_key("SomethingElse_123") is None


def _share(monkeypatch, snap, procs):
    monkeypatch.setattr(camshare, "snapshot", lambda: dict(snap))
    monkeypatch.setattr(camshare, "processes", lambda: dict(procs))
    return camshare.CameraShare()


def test_starting_a_camera_app_is_a_request(monkeypatch):
    snap = {r"NonPackaged\C:#Apps#Cam#foocam.exe": (1, 2)}
    procs = {1: "explorer.exe"}
    share = _share(monkeypatch, snap, procs)
    procs[50] = "zoom.exe"       # well-known video app
    procs[51] = "chrome.exe"     # browsers never count
    procs[52] = "foocam.exe"     # learned from the webcam history
    found = share.new_requests()
    assert {(f[0], f[3]) for f in found} == {("Zoom", 50), ("foocam", 52)}
    assert share.new_requests() == []  # each process only once


def test_lend_ends_when_the_app_stops_using_the_camera(monkeypatch):
    key = r"NonPackaged\C:#Apps#Zoom#Zoom.exe"
    snap = {key: (1, 2)}
    procs = {50: "zoom.exe"}
    share = _share(monkeypatch, snap, procs)
    lend = Lend("Zoom", "zoom.exe", None, 50)
    assert not share.finished(lend)
    start = camshare.filetime_now()
    snap[key] = (start, 0)             # Zoom picks the camera up
    assert not share.finished(lend)
    snap[key] = (start, start + 10)    # ... and releases it
    lend.free_since = -100.0           # pretend the grace period passed
    assert share.finished(lend)


def test_lend_ends_when_the_app_exits(monkeypatch):
    procs = {50: "zoom.exe"}
    share = _share(monkeypatch, {}, procs)
    lend = Lend("Zoom", "zoom.exe", None, 50)
    assert not share.finished(lend)
    del procs[50]
    assert share.finished(lend)


def test_manual_release_waits_for_the_user(monkeypatch):
    share = _share(monkeypatch, {}, {})
    assert not share.finished(Lend("other apps"))


def test_eye_toggle(sim, monkeypatch):
    calibrations = []
    monkeypatch.setattr(sim.ctrl, "start_eye_calibration", lambda: calibrations.append(1))
    sim.ctrl.set_eye_follow(True)
    assert sim.ctrl.cfg["mouse_mode"] == "eyes"
    assert calibrations == [1]  # not calibrated yet -> calibration starts
    sim.ctrl.set_eye_follow(False)
    assert sim.ctrl.cfg["mouse_mode"] in ("off", "monitor")
