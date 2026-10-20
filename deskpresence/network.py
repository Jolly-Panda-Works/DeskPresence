"""Tiny JSON-lines link between the desktop (server) and the laptop (client).

Messages: {"type": "hello"|"welcome"|"away"|"back"|"break"|"notification"|"ping", ...}
The laptop's first message is a hello carrying the shared token; the desktop answers with
a welcome (or closes the connection when the token is wrong).

The desktop also answers UDP broadcasts on the same port, so the laptop can find it
without typing an IP address (see discover()).
"""
import hmac
import json
import logging
import select
import socket
import threading
import time

log = logging.getLogger(__name__)

DISCOVER_MSG = b"DESKPRESENCE_DISCOVER"
DISCOVER_REPLY = b"DESKPRESENCE_HERE"


def _send(sock, msg):
    sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))


def _lines(sock):
    buf = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                yield json.loads(line.decode("utf-8"))


def local_addresses():
    """IPv4 addresses of this PC on the local network."""
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    try:  # the address used for the default route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted((a for a in addrs if not a.startswith("127.")), key=lambda a: (_rank(a), a))


def discover(port, timeout=2.5):
    """Broadcasts on every network adapter and returns [(ip, hostname)] of desktops running DeskPresence.

    One socket per local address: with a VPN installed, a plain broadcast would only leave
    through the VPN adapter and never reach the other PC on the home network.
    """
    found = {}
    socks = []
    for local in local_addresses() + ["0.0.0.0"]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind((local, 0))
            s.setblocking(False)
            targets = ["255.255.255.255"]
            if local != "0.0.0.0":
                prefix = local.rsplit(".", 1)[0]
                targets.append(prefix + ".255")  # the usual /24 home network
                # many Wi-Fi routers drop broadcasts: also ask every address of the /24 directly
                targets += [f"{prefix}.{i}" for i in range(1, 255)]
            for target in targets:
                try:
                    s.sendto(DISCOVER_MSG, (target, port))
                except OSError:
                    pass
            socks.append(s)
        except OSError:
            continue
    try:
        end = time.monotonic() + timeout
        while time.monotonic() < end and socks:
            ready, _, _ = select.select(socks, [], [], 0.2)
            for s in ready:
                try:
                    data, addr = s.recvfrom(1024)
                except OSError:
                    continue
                if data.startswith(DISCOVER_REPLY):
                    found[addr[0]] = data[len(DISCOVER_REPLY):].decode("utf-8", "replace").strip()
    finally:
        for s in socks:
            s.close()
    # one address per PC, preferring the home network over VPN / Hyper-V / WSL adapters
    best = {}
    for ip, name in found.items():
        if name not in best or _rank(ip) < _rank(best[name]):
            best[name] = ip
    return sorted((ip, name) for name, ip in best.items())


def _rank(ip):
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    return 2  # 172.16-31: usually VPN, Hyper-V or WSL


def test_connection(host, port, token, timeout=4.0):
    """Returns "ok", "bad_token" or "unreachable"."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return "unreachable"
    try:
        sock.settimeout(timeout)
        _send(sock, {"type": "hello", "token": token, "name": socket.gethostname(), "test": True})
        for msg in _lines(sock):
            if msg.get("type") == "welcome":
                return "ok"
        return "bad_token"
    except (OSError, ValueError):
        return "bad_token"
    finally:
        sock.close()


class Link:
    def __init__(self, role, port, token, host=None, on_message=None, on_status=None):
        self.role, self.port, self.token, self.host = role, port, token, host
        self.on_message = on_message or (lambda m: None)
        self.on_status = on_status or (lambda s: None)
        self._peers = {}  # socket -> peer name
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server = None
        self._udp = None
        self.listening = False
        self.error = None

    @property
    def connected(self):
        with self._lock:
            return bool(self._peers)

    @property
    def peer_names(self):
        with self._lock:
            return list(self._peers.values())

    def start(self):
        if self.role == "desktop":
            threading.Thread(target=self._serve, daemon=True, name="link").start()
            threading.Thread(target=self._answer_discovery, daemon=True, name="discovery").start()
        else:
            threading.Thread(target=self._connect_loop, daemon=True, name="link").start()

    def stop(self):
        self._stop.set()
        for s in (self._server, self._udp):
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        with self._lock:
            peers = list(self._peers)
        for p in peers:
            try:
                p.close()
            except Exception:
                pass

    def send(self, msg):
        with self._lock:
            peers = list(self._peers)
        for p in peers:
            try:
                _send(p, msg)
            except Exception:
                log.warning("Send failed, dropping peer")
                self._drop(p)

    def _drop(self, sock):
        with self._lock:
            self._peers.pop(sock, None)
        try:
            sock.close()
        except Exception:
            pass
        self.on_status(self.connected)

    def _add(self, sock, name):
        with self._lock:
            self._peers[sock] = name
        self.on_status(True)
        log.info("Peer connected: %s", name)

    def _handle_server_side(self, sock):
        try:
            it = _lines(sock)
            sock.settimeout(5)
            hello = next(it)
            if hello.get("type") != "hello" or not hmac.compare_digest(str(hello.get("token", "")), self.token):
                log.warning("Rejected peer with bad token")
                sock.close()
                return
            _send(sock, {"type": "welcome", "name": socket.gethostname()})
            if hello.get("test"):
                sock.close()
                return
            sock.settimeout(None)
            self._add(sock, str(hello.get("name", "?")))
            for msg in it:
                if msg.get("type") != "ping":
                    self.on_message(msg)
        except Exception as e:
            log.info("Peer disconnected: %s", e)
        finally:
            self._drop(sock)

    def _handle_client_side(self, sock):
        try:
            for msg in _lines(sock):
                kind = msg.get("type")
                if kind == "welcome":
                    self._add(sock, str(msg.get("name", self.host)))
                elif kind != "ping":
                    self.on_message(msg)
        except Exception as e:
            log.info("Disconnected from desktop: %s", e)
        finally:
            self._drop(sock)

    def _serve(self):
        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind(("0.0.0.0", self.port))
            self._server.listen(4)
        except OSError as e:
            log.exception("Cannot listen on port %s", self.port)
            self.error = str(e)
            return
        self.listening = True
        log.info("Listening on port %s", self.port)
        threading.Thread(target=self._keepalive, daemon=True).start()
        while not self._stop.is_set():
            try:
                conn, addr = self._server.accept()
            except OSError:
                break
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            log.info("Incoming connection from %s", addr)
            threading.Thread(target=self._handle_server_side, args=(conn,), daemon=True).start()

    def _answer_discovery(self):
        try:
            self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp.bind(("0.0.0.0", self.port))
        except OSError:
            log.warning("Discovery responder unavailable")
            return
        reply = DISCOVER_REPLY + socket.gethostname().encode("utf-8")
        while not self._stop.is_set():
            try:
                data, addr = self._udp.recvfrom(1024)
            except OSError:
                break
            if data == DISCOVER_MSG:
                try:
                    self._udp.sendto(reply, addr)
                except OSError:
                    pass

    def _keepalive(self):
        while not self._stop.wait(20):
            self.send({"type": "ping"})

    def _connect_loop(self):
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=5)
                sock.settimeout(None)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                _send(sock, {"type": "hello", "token": self.token, "name": socket.gethostname()})
                self._handle_client_side(sock)
            except Exception as e:
                log.debug("Connect to %s failed: %s", self.host, e)
            self._stop.wait(5)
