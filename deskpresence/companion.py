"""Server for the DeskPresence Android app, running on this PC.

  HTTPS with a self-signed certificate generated on first use; the phone pins its fingerprint
  when it pairs (trust on first use), so later connections cannot be intercepted.
  Pairing: a 6-digit code shown in Settings -> Mobile (valid 10 minutes, one phone, 5 tries).
  Every phone gets its own random token; only its SHA-256 is stored, so removing a phone in
  the settings revokes it.
  The phones find this PC on the network through mDNS (_deskpresence._tcp).

API (JSON; everything except /api/info and /api/pair needs "Authorization: Bearer <token>"):
  GET  /api/info           {name, version, fingerprint}
  POST /api/pair           {code, name}            -> {device_id, token, name, fingerprint}
  GET  /api/status         presence, today's water glasses and work time
  GET  /api/camera         live webcam as MJPEG; this PC shows who is watching while it runs
  POST /api/message        {text}                  -> shown as a popup on this PC
  POST /api/rename         {name}                  -> the phone renames itself
"""
import datetime
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import APP_VERSION, e2e
from .config import APP_DIR

log = logging.getLogger(__name__)

CERT_PATH = os.path.join(APP_DIR, "companion_cert.pem")
KEY_PATH = os.path.join(APP_DIR, "companion_key.pem")
SERVICE_TYPE = "_deskpresence._tcp.local."
CODE_SECONDS = 600
CODE_TRIES = 5
STREAM_FPS = 10
MAX_MESSAGE = 500


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- certificate
def ensure_certificate():
    """Creates a self-signed certificate on first use. Returns its SHA-256 fingerprint (hex)."""
    if not (os.path.exists(CERT_PATH) and os.path.exists(KEY_PATH)):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"DeskPresence {socket.gethostname()}")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder()
                .subject_name(name).issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(socket.gethostname()),
                                                            x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                               critical=False)
                .sign(key, hashes.SHA256()))
        with open(KEY_PATH, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
        with open(CERT_PATH, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        log.info("Created the companion certificate")
    with open(CERT_PATH, "rb") as f:
        der = ssl.PEM_cert_to_DER_cert(f.read().decode("ascii"))
    return hashlib.sha256(der).hexdigest()


# ---------------------------------------------------------------- paired phones
# (module functions, so the settings window can manage phones while the server is off)
def save_devices(cfg, devices):
    mobile = dict(cfg["mobile"])
    mobile["devices"] = devices
    cfg.set("mobile", mobile)


def rename_device(cfg, device_id, name):
    devices = dict(cfg["mobile"]["devices"])
    name = name.strip()[:40]
    if device_id in devices and name:
        devices[device_id] = dict(devices[device_id], name=name)
        save_devices(cfg, devices)


def remove_device(cfg, device_id):
    devices = dict(cfg["mobile"]["devices"])
    if devices.pop(device_id, None) is not None:
        save_devices(cfg, devices)


def set_device_camera(cfg, device_id, allowed):
    devices = dict(cfg["mobile"]["devices"])
    if device_id in devices:
        devices[device_id] = dict(devices[device_id], camera=bool(allowed))
        save_devices(cfg, devices)


# ---------------------------------------------------------------- server
class Companion:
    """Owns the HTTPS server, pairing and the list of phones. `ctrl` is the Controller."""

    def __init__(self, ctrl, cfg, port):
        self.ctrl, self.cfg, self.port = ctrl, cfg, port
        self.fingerprint = ""
        self.error = None
        self.running = False
        self._server = None
        self._zeroconf = None
        self._zc_info = None
        self._code = None
        self._code_until = 0.0
        self._code_tries = 0
        self._lock = threading.Lock()
        self.viewers = {}  # stream id -> device name
        self.identity = e2e.identity()
        self.relay = None
        self._keys = {}
        self.replay = e2e.ReplayGuard()

    # --- devices (stored in cfg["mobile"]["devices"]: id -> {name, token_sha256, ...})
    def devices(self):
        return dict(self.cfg["mobile"]["devices"])

    def _save_devices(self, devices):
        save_devices(self.cfg, devices)

    def rename(self, device_id, name):
        rename_device(self.cfg, device_id, name)

    def device_for(self, token):
        if not token:
            return None, None
        digest = _hash(token)
        for device_id, d in self.devices().items():
            if hmac.compare_digest(d.get("token_sha256", ""), digest):
                return device_id, d
        return None, None

    def touch(self, device_id):
        """Remembers when a phone was last seen (written to disk at most once a minute)."""
        device = self.cfg["mobile"]["devices"].get(device_id)
        now = int(time.time())
        if device is not None and now - device.get("last_seen", 0) > 60:
            devices = self.devices()
            devices[device_id] = dict(device, last_seen=now)
            self._save_devices(devices)

    # --- pairing code
    def new_code(self):
        with self._lock:
            self._code = f"{secrets.randbelow(1_000_000):06d}"
            self._code_until = time.monotonic() + CODE_SECONDS
            self._code_tries = 0
            return self._code

    def code(self):
        """(code, seconds left) or (None, 0)."""
        with self._lock:
            left = self._code_until - time.monotonic()
            if self._code and left > 0:
                return self._code, int(left)
            return None, 0

    def pair(self, code, name, pub=None):
        with self._lock:
            valid = self._code and time.monotonic() < self._code_until
            if not valid:
                return None
            if not hmac.compare_digest(str(code).strip(), self._code):
                self._code_tries += 1
                if self._code_tries >= CODE_TRIES:
                    self._code = None  # too many wrong tries: a new code is needed
                return None
            self._code = None  # one phone per code
        token = secrets.token_urlsafe(32)
        device_id = secrets.token_hex(6)
        devices = self.devices()
        devices[device_id] = {"name": (name or "Phone").strip()[:40], "token_sha256": _hash(token),
                              "created": int(time.time()), "last_seen": int(time.time()), "camera": True}
        if pub:
            try:
                e2e.load_public(pub)
                devices[device_id]["pub"] = pub
            except Exception:
                log.warning("Phone sent an invalid public key; remote access disabled for it")
        self._save_devices(devices)
        log.info("Paired a new phone: %s", devices[device_id]["name"])
        self.ctrl.on_phone_paired(devices[device_id]["name"])
        return device_id, token

    def pair_reply(self, device_id, token):
        """What a phone gets after pairing (locally or through the relay)."""
        from .network import local_addresses
        return {"device_id": device_id, "token": token, "name": socket.gethostname(),
                "fingerprint": self.fingerprint, "pc_pub": e2e.public_b64(self.identity),
                "lan": [f"{a}:{self.port}" for a in local_addresses()[:3]],
                "hub": self.cfg["mobile"].get("hub_id", ""), "relay": self.cfg["mobile"].get("relay_url", "")}

    def pairing_link(self, code):
        """Link / QR content for a pairing code. Secrets go after "#", which never reaches a server."""
        from urllib.parse import urlencode
        from .network import local_addresses
        mobile = self.cfg["mobile"]
        params = {"c": code, "k": e2e.fingerprint(e2e.public_b64(self.identity)), "f": self.fingerprint[:16]}
        lan = local_addresses()
        if lan:
            params["l"] = f"{lan[0]}:{self.port}"
        if mobile.get("relay_url"):
            params["h"] = mobile["hub_id"]
            return mobile["relay_url"].rstrip("/") + "/p/#" + urlencode(params)
        return "deskpresence://pair?" + urlencode(params)

    def device_key(self, device_id):
        """The end-to-end key shared with one phone (None for phones paired without a key)."""
        device = self.cfg["mobile"]["devices"].get(device_id)
        if not device or not device.get("pub"):
            return None
        cached = self._keys.get(device_id)
        if cached and cached[0] == device["pub"]:
            return cached[1]
        key = e2e.derive(self.identity, device["pub"], device_id)
        self._keys[device_id] = (device["pub"], key)
        return key

    def dispatch(self, device_id, device, method, path, body):
        """The phone API, shared by the local HTTPS server and the relay. Returns (status, json)."""
        if method == "GET" and path == "/api/status":
            status = self.status()
            status["device_name"] = device["name"]
            status["camera_allowed"] = status["camera_allowed"] and device.get("camera", True)
            return 200, status
        if method == "POST" and path == "/api/message":
            text = str(body.get("text", "")).strip()[:MAX_MESSAGE]
            if not text:
                return 400, {"error": "empty"}
            self.ctrl.on_phone_message(device["name"], text)
            return 200, {"ok": True}
        if method == "POST" and path == "/api/rename":
            self.rename(device_id, str(body.get("name", "")))
            return 200, {"ok": True}
        return 404, {"error": "not found"}

    def camera_denied(self, device):
        """None when this phone may watch the webcam now, else (status, error)."""
        if not (self.cfg["mobile"]["allow_camera"] and device.get("camera", True)):
            return 403, "camera_not_allowed"
        if self.ctrl.camera_lent_to is not None:
            return 409, "camera_busy"
        return None

    def frames(self, keep_going):
        """JPEG frames for a viewer at STREAM_FPS while keep_going() is true."""
        import cv2
        waited, last = 0.0, None
        while self.running and keep_going():
            frame = self.ctrl.camera_frame()
            if frame is None or frame is last:
                time.sleep(0.05)
                waited += 0.05
                if waited > 15:  # the webcam did not come up
                    return
                continue
            waited, last = 0.0, frame
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                yield jpg.tobytes()
                time.sleep(1.0 / STREAM_FPS)

    # --- lifecycle
    def start(self):
        try:
            self.fingerprint = ensure_certificate()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(CERT_PATH, KEY_PATH)
            server = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
            server.daemon_threads = True
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
            server.companion = self
            self._server = server
        except Exception as e:
            log.exception("Companion server could not start")
            self.error = str(e)
            return
        threading.Thread(target=self._server.serve_forever, daemon=True, name="companion").start()
        self.running = True
        log.info("Companion server on port %s", self.port)
        self._advertise()
        mobile = self.cfg["mobile"]
        if mobile.get("relay_url"):
            from .relay_client import RelayClient
            self.relay = RelayClient(self, mobile["relay_url"], mobile["hub_id"], mobile["hub_secret"])
            self.relay.start()

    def stop(self):
        self.running = False
        if self.relay:
            self.relay.stop()
            self.relay = None
        if self._zeroconf:
            try:
                self._zeroconf.unregister_service(self._zc_info)
                self._zeroconf.close()
            except Exception:
                pass
            self._zeroconf = None
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        with self._lock:
            had_viewers = bool(self.viewers)
            self.viewers.clear()
        if had_viewers:
            self.ctrl.on_viewers_changed([])

    def _advertise(self):
        try:
            from zeroconf import ServiceInfo, Zeroconf
            from .network import _rank, local_addresses
            host = socket.gethostname()
            addrs = local_addresses()
            # Android resolves a single address: leave out VPN / Hyper-V / WSL adapters when possible
            home = [a for a in addrs if _rank(a) < 2]
            addrs = home or addrs
            self._zc_info = ServiceInfo(
                SERVICE_TYPE, f"{host}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(a) for a in addrs], port=self.port,
                properties={"name": host, "fp": self.fingerprint[:16], "v": APP_VERSION},
                server=f"{host}.local.")
            self._zeroconf = Zeroconf()
            self._zeroconf.register_service(self._zc_info)
        except Exception:
            log.exception("mDNS advertising unavailable (phones can still type the address)")

    # --- data for the phone
    def status(self):
        ctrl = self.ctrl
        today = ctrl.stats.today()
        if ctrl.paused or not ctrl.uses_camera:
            state = "unknown"
        elif ctrl.break_active:
            state = "break"
        elif ctrl.state == "away":
            state = "away"
        else:
            state = "working"
        return {"state": state, "since": int(time.time() - (time.monotonic() - ctrl.state_since)),
                "water_today": today["water"], "work_seconds_today": today["work_seconds"],
                "water_goal_minutes": ctrl.cfg["water_reminder_minutes"],
                "camera_allowed": bool(ctrl.cfg["mobile"]["allow_camera"]),
                "camera_available": ctrl.camera_lent_to is None,
                "name": socket.gethostname(), "version": APP_VERSION}

    def add_viewer(self, name):
        with self._lock:
            sid = secrets.token_hex(4)
            self.viewers[sid] = name
            names = list(self.viewers.values())
        self.ctrl.on_viewers_changed(names)
        return sid

    def remove_viewer(self, sid):
        with self._lock:
            self.viewers.pop(sid, None)
            names = list(self.viewers.values())
        self.ctrl.on_viewers_changed(names)


class _Handler(BaseHTTPRequestHandler):
    server_version = "DeskPresence"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; errors are logged where they happen
        pass

    @property
    def companion(self):
        return self.server.companion

    # --- helpers
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 10_000:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _auth(self):
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        device_id, device = self.companion.device_for(token)
        if device is None:
            self._json(401, {"error": "unpaired"})
            return None, None
        self.companion.touch(device_id)
        return device_id, device

    # --- routes
    def do_GET(self):
        c = self.companion
        if self.path == "/api/info":
            return self._json(200, {"name": socket.gethostname(), "version": APP_VERSION,
                                    "fingerprint": c.fingerprint, "pc_pub": e2e.public_b64(c.identity)})
        device_id, device = self._auth()
        if device is None:
            return
        if self.path.startswith("/api/camera"):
            return self._camera(device)
        self._json(*c.dispatch(device_id, device, "GET", self.path, {}))

    def do_POST(self):
        c = self.companion
        if self.path == "/api/pair":
            body = self._body()
            result = c.pair(body.get("code", ""), body.get("name", ""), body.get("pub"))
            if result is None:
                return self._json(403, {"error": "bad_code"})
            return self._json(200, c.pair_reply(*result))
        device_id, device = self._auth()
        if device is None:
            return
        self._json(*c.dispatch(device_id, device, "POST", self.path, self._body()))

    def _camera(self, device):
        c = self.companion
        denied = c.camera_denied(device)
        if denied:
            return self._json(denied[0], {"error": denied[1]})
        sid = c.add_viewer(device["name"])
        log.info("%s started watching the webcam", device["name"])
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            for data in c.frames(lambda: True):
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                self.wfile.flush()
        except (ConnectionError, ssl.SSLError, OSError):
            pass  # the phone closed the stream
        except Exception:
            log.exception("Webcam stream failed")
        finally:
            c.remove_viewer(sid)
            log.info("%s stopped watching the webcam", device["name"])
        self.close_connection = True
