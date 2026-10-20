"""Tiny JSON-lines link between the desktop (server) and the laptop (client).

Messages: {"type": "away"|"back"|"notification"|"hello", ...}
The first message must be a hello carrying the shared token.
"""
import hmac
import json
import logging
import socket
import threading
import time

log = logging.getLogger(__name__)


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


class Link:
    def __init__(self, role, port, token, host=None, on_message=None, on_status=None):
        self.role, self.port, self.token, self.host = role, port, token, host
        self.on_message = on_message or (lambda m: None)
        self.on_status = on_status or (lambda s: None)
        self._peers = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server = None

    @property
    def connected(self):
        with self._lock:
            return bool(self._peers)

    def start(self):
        target = self._serve if self.role == "desktop" else self._connect_loop
        threading.Thread(target=target, daemon=True, name="link").start()

    def stop(self):
        self._stop.set()
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
        with self._lock:
            for p in self._peers:
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
            if sock in self._peers:
                self._peers.remove(sock)
        try:
            sock.close()
        except Exception:
            pass
        self.on_status(self.connected)

    def _handle(self, sock, expect_hello):
        try:
            it = _lines(sock)
            if expect_hello:
                sock.settimeout(5)
                hello = next(it)
                if hello.get("type") != "hello" or not hmac.compare_digest(str(hello.get("token", "")), self.token):
                    log.warning("Rejected peer with bad token")
                    sock.close()
                    return
                sock.settimeout(None)
            with self._lock:
                self._peers.append(sock)
            self.on_status(True)
            log.info("Peer connected")
            for msg in it:
                if msg.get("type") != "ping":
                    self.on_message(msg)
        except Exception as e:
            log.info("Peer disconnected: %s", e)
        finally:
            self._drop(sock)

    def _serve(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("0.0.0.0", self.port))
        self._server.listen(4)
        log.info("Listening on port %s", self.port)
        threading.Thread(target=self._keepalive, daemon=True).start()
        while not self._stop.is_set():
            try:
                conn, addr = self._server.accept()
            except OSError:
                break
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            log.info("Incoming connection from %s", addr)
            threading.Thread(target=self._handle, args=(conn, True), daemon=True).start()

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
                self._handle(sock, expect_hello=False)
            except Exception as e:
                log.debug("Connect to %s failed: %s", self.host, e)
            self._stop.wait(5)
