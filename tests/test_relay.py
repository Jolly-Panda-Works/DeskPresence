"""End-to-end: relay server + PC (Companion + RelayClient) + a simulated phone, all over real sockets."""
import asyncio
import copy
import json
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from deskpresence import companion, config, e2e

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import relay as relay_server  # noqa: E402

from test_companion import FakeCfg, FakeCtrl  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def relay_url(tmp_path):
    from aiohttp import web
    port = free_port()
    loop = asyncio.new_event_loop()
    runner = web.AppRunner(relay_server.make_app(str(tmp_path / "relay.db")))
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", port).start())
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(timeout=10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


@pytest.fixture
def pc(relay_url, tmp_path, monkeypatch):
    monkeypatch.setattr(companion, "CERT_PATH", str(tmp_path / "cert.pem"))
    monkeypatch.setattr(companion, "KEY_PATH", str(tmp_path / "key.pem"))
    monkeypatch.setattr(companion.Companion, "_advertise", lambda self: None)
    cfg = FakeCfg(copy.deepcopy(config.DEFAULTS))
    cfg["mobile"].update(enabled=True, relay_url=relay_url, hub_id="hubtest1234", hub_secret="s" * 32)
    ctrl = FakeCtrl(cfg)
    comp = companion.Companion(ctrl, cfg, free_port())
    comp.start()
    for _ in range(100):
        if comp.relay and comp.relay.connected:
            break
        time.sleep(0.05)
    assert comp.relay.connected, comp.relay.error
    yield comp, ctrl
    comp.stop()


def post(url, data, headers=None, method="POST"):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Phone:
    """What the Android app does, in Python."""

    def __init__(self, relay, hub):
        self.relay, self.hub = relay, hub
        self.key_pair = ec.generate_private_key(ec.SECP256R1())
        self.pub = e2e.public_b64(self.key_pair)

    def pair(self, code, expect_fingerprint=None):
        status, r = post(f"{self.relay}/v1/hub/{self.hub}/call",
                         {"pair": {"code": code, "name": "Sara", "pub": self.pub}})
        if status != 200:
            return status
        if expect_fingerprint:
            assert e2e.fingerprint(r["pc_pub"]) == expect_fingerprint  # the key the QR code promised
        self.device_id = r["device_id"]
        self.key = e2e.derive(self.key_pair, r["pc_pub"], self.device_id)
        return 200

    def envelope(self, method, path, body=None):
        env = e2e.seal(self.key, {"m": method, "p": path, "b": body or {}, "t": time.time()}, self.device_id)
        env["d"] = self.device_id
        return env

    def call(self, method, path, body=None, env=None):
        env = env or self.envelope(method, path, body)
        status, r = post(f"{self.relay}/v1/hub/{self.hub}/call", env)
        if status != 200:
            return status, r
        inner = e2e.open_sealed(self.key, r, self.device_id)
        return inner["s"], inner["b"]


def test_pairing_and_api_through_the_relay(relay_url, pc):
    comp, ctrl = pc
    phone = Phone(relay_url, "hubtest1234")
    assert phone.pair("000000") == 403  # no code yet
    code = comp.new_code()
    assert phone.pair(code, expect_fingerprint=e2e.fingerprint(e2e.public_b64(comp.identity))) == 200

    status, st = phone.call("GET", "/api/status")
    assert status == 200 and st["state"] == "working" and st["water_today"] == 3

    assert phone.call("POST", "/api/message", {"text": "سلام"})[0] == 200
    assert ctrl.messages == [("Sara", "سلام")]

    env = phone.envelope("GET", "/api/status")
    assert phone.call(None, None, env=env)[0] == 200
    assert phone.call(None, None, env=env)[0] == 401  # the same envelope twice = replay

    stranger = Phone(relay_url, "hubtest1234")
    stranger.device_id, stranger.key = phone.device_id, AESGCM.generate_key(256)
    assert stranger.call("GET", "/api/status")[0] == 401  # wrong key


def test_encrypted_webcam_stream_through_the_relay(relay_url, pc):
    comp, ctrl = pc
    phone = Phone(relay_url, "hubtest1234")
    assert phone.pair(comp.new_code()) == 200
    req = urllib.request.Request(f"{relay_url}/v1/hub/hubtest1234/stream",
                                 data=json.dumps(phone.envelope("GET", "/api/camera")).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        frames = []
        while len(frames) < 3:
            length = struct.unpack(">I", r.read(4))[0]
            blob = r.read(length)
            frames.append(AESGCM(phone.key).decrypt(blob[:12], blob[12:], phone.device_id.encode()))
        assert all(f.startswith(b"\xff\xd8") for f in frames)  # JPEGs, readable only by the phone
        assert ctrl.viewer_log[-1] == ["Sara"]
    for _ in range(60):
        if ctrl.viewer_log[-1] == []:
            break
        time.sleep(0.1)
    assert ctrl.viewer_log[-1] == []  # banner removed once the phone stopped watching


def test_pc_offline(relay_url):
    assert post(f"{relay_url}/v1/hub/nobodyhome/call", {"pair": {"code": "1"}})[0] == 503


def test_phone_to_phone_status(relay_url):
    def register():
        r = post(f"{relay_url}/v1/phones", {})[1]
        return {"Authorization": f"Phone {r['phone_id']}:{r['secret']}"}, r["phone_id"]

    a_auth, a_id = register()
    b_auth, b_id = register()
    a_key, b_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())

    code = post(f"{relay_url}/v1/invites", {"pub": e2e.public_b64(a_key), "name": "Ali"}, a_auth)[1]["code"]
    assert post(f"{relay_url}/v1/invites/{code}", None, b_auth, "GET")[1]["name"] == "Ali"
    assert post(f"{relay_url}/v1/invites/{code}/accept", {"pub": e2e.public_b64(b_key), "name": "Sara"}, b_auth)[0] == 200
    result = post(f"{relay_url}/v1/invites/{code}/result", None, a_auth, "GET")[1]
    assert result["phone_id"] == b_id and result["name"] == "Sara"
    assert post(f"{relay_url}/v1/invites/{code}/accept", {"pub": "x"}, b_auth)[0] == 409  # one use

    salt = "".join(sorted([a_id, b_id]))
    k_ab = e2e.derive(a_key, e2e.public_b64(b_key), salt, b"deskpresence phone-phone v1")
    k_ba = e2e.derive(b_key, e2e.public_b64(a_key), salt, b"deskpresence phone-phone v1")
    assert k_ab == k_ba

    sealed = e2e.seal(k_ab, {"status": "busy", "battery": 64, "charging": False, "in_call": True}, a_id)
    assert post(f"{relay_url}/v1/status", {"to": {b_id: json.dumps(sealed)}}, a_auth, "PUT")[0] == 200
    inbox = post(f"{relay_url}/v1/status", None, b_auth, "GET")[1]["from"]
    got = e2e.open_sealed(k_ba, json.loads(inbox[a_id]["sealed"]), a_id)
    assert got["status"] == "busy" and got["battery"] == 64 and got["in_call"] is True

    # strangers cannot post into someone's inbox, and removed contacts stop seeing each other
    c_auth, c_id = register()
    post(f"{relay_url}/v1/status", {"to": {b_id: "spam"}}, c_auth, "PUT")
    assert c_id not in post(f"{relay_url}/v1/status", None, b_auth, "GET")[1]["from"]
    assert post(f"{relay_url}/v1/contacts/{a_id}", None, b_auth, "DELETE")[0] == 200
    assert post(f"{relay_url}/v1/status", None, b_auth, "GET")[1]["from"] == {}
    assert post(f"{relay_url}/v1/status", None, {"Authorization": "Phone x:y"}, "GET")[0] == 401


def test_landing_page(relay_url):
    with urllib.request.urlopen(f"{relay_url}/p/", timeout=5) as r:
        html = r.read().decode()
    assert "deskpresence" in html and "{{" not in html
