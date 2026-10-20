"""End-to-end test of the Android companion server over real HTTPS."""
import copy
import hashlib
import json
import socket
import ssl
import time
import urllib.error
import urllib.request

import numpy as np
import pytest

from deskpresence import companion, config


class FakeCfg(dict):
    @property
    def data(self):
        return self

    def set(self, k, v):
        self[k] = v


class FakeStats:
    def today(self):
        return {"water": 3, "work_seconds": 7200}


class FakeCtrl:
    def __init__(self, cfg):
        self.cfg = cfg
        self.stats = FakeStats()
        self.paused = False
        self.uses_camera = True
        self.break_active = False
        self.state = "present"
        self.state_since = time.monotonic() - 60
        self.camera_lent_to = None
        self.messages, self.viewer_log, self.paired = [], [], []

    def camera_frame(self):
        return np.full((120, 160, 3), int(time.monotonic() * 10) % 255, np.uint8)

    def on_viewers_changed(self, names):
        self.viewer_log.append(list(names))

    def on_phone_message(self, name, text):
        self.messages.append((name, text))

    def on_phone_paired(self, name):
        self.paired.append(name)


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(companion, "CERT_PATH", str(tmp_path / "cert.pem"))
    monkeypatch.setattr(companion, "KEY_PATH", str(tmp_path / "key.pem"))
    monkeypatch.setattr(companion.Companion, "_advertise", lambda self: None)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfg = FakeCfg(copy.deepcopy(config.DEFAULTS))
    cfg["mobile"]["enabled"] = True
    ctrl = FakeCtrl(cfg)
    comp = companion.Companion(ctrl, cfg, port)
    comp.start()
    assert comp.running, comp.error
    yield comp, ctrl, f"https://127.0.0.1:{port}"
    comp.stop()


CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE  # the app pins the fingerprint instead (checked below)


def call(url, data=None, token=None, timeout=5):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_pairing_status_message_and_revoke(server):
    comp, ctrl, base = server
    status, info = call(base + "/api/info")
    assert status == 200 and info["fingerprint"] == comp.fingerprint

    # the certificate the client sees is the one whose fingerprint the app pins
    host, port = base[8:].split(":")
    with socket.create_connection((host, int(port))) as raw, CTX.wrap_socket(raw) as tls:
        assert hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest() == comp.fingerprint

    assert call(base + "/api/pair", {"code": "123456", "name": "x"})[0] == 403  # no code yet
    code = comp.new_code()
    wrong = "000000" if code != "000000" else "111111"
    assert call(base + "/api/pair", {"code": wrong, "name": "x"})[0] == 403
    status, paired = call(base + "/api/pair", {"code": code, "name": "Sara's phone"})
    assert status == 200 and paired["fingerprint"] == comp.fingerprint
    token = paired["token"]
    assert ctrl.paired == ["Sara's phone"]
    assert call(base + "/api/pair", {"code": code, "name": "again"})[0] == 403  # one phone per code
    assert token not in json.dumps(dict(ctrl.cfg))  # only the hash is stored

    assert call(base + "/api/status")[0] == 401
    status, st = call(base + "/api/status", token=token)
    assert status == 200
    assert st["state"] == "working" and st["water_today"] == 3 and st["work_seconds_today"] == 7200
    assert st["device_name"] == "Sara's phone"
    ctrl.state = "away"
    assert call(base + "/api/status", token=token)[1]["state"] == "away"

    assert call(base + "/api/message", {"text": "  lunch is ready  "}, token=token)[0] == 200
    assert ctrl.messages == [("Sara's phone", "lunch is ready")]

    companion.rename_device(ctrl.cfg, paired["device_id"], "Sara")
    assert call(base + "/api/status", token=token)[1]["device_name"] == "Sara"

    companion.remove_device(ctrl.cfg, paired["device_id"])
    assert call(base + "/api/status", token=token)[0] == 401


def test_too_many_wrong_codes_invalidate_the_code(server):
    comp, _ctrl, base = server
    code = comp.new_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(companion.CODE_TRIES):
        call(base + "/api/pair", {"code": wrong, "name": "x"})
    assert call(base + "/api/pair", {"code": code, "name": "x"})[0] == 403


def _pair(comp, base):
    return call(base + "/api/pair", {"code": comp.new_code(), "name": "Ali"})[1]["token"]


def test_camera_stream_and_viewer_banner(server):
    comp, ctrl, base = server
    token = _pair(comp, base)
    req = urllib.request.Request(base + "/api/camera", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, context=CTX, timeout=5) as r:
        assert r.headers["Content-Type"].startswith("multipart/x-mixed-replace")
        data = b""
        while data.count(b"--frame") < 3:
            chunk = r.read1(4096)
            assert chunk, "stream ended early"
            data += chunk
        assert b"\xff\xd8" in data  # JPEG start
        assert ctrl.viewer_log[-1] == ["Ali"]  # "Ali is watching you" is on screen
    # the server notices the closed stream on its next write
    for _ in range(40):
        if ctrl.viewer_log[-1] == []:
            break
        time.sleep(0.1)
    assert ctrl.viewer_log[-1] == []


def test_camera_can_be_refused(server):
    comp, ctrl, base = server
    token = _pair(comp, base)
    ctrl.cfg["mobile"]["allow_camera"] = False
    req = urllib.request.Request(base + "/api/camera", headers={"Authorization": f"Bearer {token}"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, context=CTX, timeout=5)
    assert e.value.code == 403
