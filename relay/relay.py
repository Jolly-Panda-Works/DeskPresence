"""DeskPresence relay: lets phones reach the PC (and each other) from anywhere.

Runs on your own VPS behind Caddy (HTTPS). Everybody connects *out* to it, so it works behind
any router, CGNAT or mobile network. It only forwards opaque, end-to-end encrypted envelopes:
the relay never sees webcam images, statuses or messages.

PC side (one WebSocket per PC):
  WS   /v1/hub?id=<hub_id>            header X-Hub-Secret; first connection registers the hub
       relay -> PC  {"t": "call",   "id": n, "body": <json>}
       PC -> relay  {"t": "reply",  "id": n, "status": 200, "body": <json>}
       relay -> PC  {"t": "stream", "id": n, "body": <json>} / {"t": "stream_end", "id": n}
       PC -> relay  binary: 4-byte stream id (big endian) + one encrypted frame
Phone -> PC:
  POST /v1/hub/<hub_id>/call          body: envelope (or a pairing request)  -> the PC's reply
  POST /v1/hub/<hub_id>/stream        body: envelope -> stream of [4-byte length + frame]
Phone <-> phone (no PC needed):
  POST /v1/phones                     -> {phone_id, secret}; later: header "Authorization: Phone id:secret"
  POST /v1/invites      {pub, name}   -> {code}            invite a phone (code valid 10 minutes)
  GET  /v1/invites/<code>             -> {phone_id, pub, name}
  POST /v1/invites/<code>/accept {pub, name}
  GET  /v1/invites/<code>/result      -> {phone_id, pub, name} of whoever accepted
  PUT  /v1/status       {"to": {phone_id: sealed}}   my encrypted status, one copy per contact
  GET  /v1/status                     -> {"from": {phone_id: {"sealed", "at"}}}
  DELETE /v1/contacts/<phone_id>      stop exchanging statuses with that phone
Web:
  GET  /p/ and /i/                    landing pages for pairing links (they open the app)
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import struct
import time
from collections import defaultdict, deque

from aiohttp import WSMsgType, web

log = logging.getLogger("relay")

DB_PATH = os.environ.get("RELAY_DB", "/data/relay.sqlite3")
CALL_TIMEOUT = 20
INVITE_SECONDS = 600
MAX_BODY = 64 * 1024
APK_URL = os.environ.get("APK_URL",
                         "https://github.com/Jolly-Panda-Works/DeskPresence/releases/latest/download/DeskPresence-Android.apk")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _h(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class RateLimit:
    """At most `limit` events per `window` seconds per key."""

    def __init__(self, limit, window):
        self.limit, self.window = limit, window
        self.events = defaultdict(deque)

    def allow(self, key):
        now = time.monotonic()
        q = self.events[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


class Relay:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS hubs (id TEXT PRIMARY KEY, secret TEXT, created INTEGER, seen INTEGER);
            CREATE TABLE IF NOT EXISTS phones (id TEXT PRIMARY KEY, secret TEXT, created INTEGER, seen INTEGER);
            CREATE TABLE IF NOT EXISTS invites (code TEXT PRIMARY KEY, phone_id TEXT, pub TEXT, name TEXT,
                                                expires INTEGER, tries INTEGER DEFAULT 0,
                                                acc_id TEXT, acc_pub TEXT, acc_name TEXT);
            CREATE TABLE IF NOT EXISTS contacts (a TEXT, b TEXT, PRIMARY KEY (a, b));
            CREATE TABLE IF NOT EXISTS status (sender TEXT, receiver TEXT, sealed TEXT, at INTEGER,
                                               PRIMARY KEY (sender, receiver));
        """)
        self.db.commit()
        self.hubs = {}           # hub id -> WebSocketResponse
        self.pending = {}        # call id -> Future
        self.streams = {}        # stream id -> StreamResponse
        self._next = 1
        self.ip_limit = RateLimit(120, 60)
        self.invite_limit = RateLimit(20, 60)

    def _id(self):
        self._next += 1
        return self._next

    # ------------------------------------------------------------ helpers
    def _ip(self, request):
        return request.headers.get("X-Forwarded-For", request.remote or "?").split(",")[0].strip()

    def _limited(self, request):
        if not self.ip_limit.allow(self._ip(request)):
            raise web.HTTPTooManyRequests(text='{"error":"slow_down"}', content_type="application/json")

    async def _json(self, request):
        if request.content_length and request.content_length > MAX_BODY:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=request.content_length)
        try:
            return await request.json()
        except Exception:
            raise web.HTTPBadRequest(text='{"error":"bad_json"}', content_type="application/json")

    def _phone(self, request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Phone ") or ":" not in auth:
            raise web.HTTPUnauthorized(text='{"error":"no_auth"}', content_type="application/json")
        pid, secret = auth[6:].split(":", 1)
        row = self.db.execute("SELECT secret FROM phones WHERE id=?", (pid,)).fetchone()
        if not row or not hmac.compare_digest(row[0], _h(secret)):
            raise web.HTTPUnauthorized(text='{"error":"bad_auth"}', content_type="application/json")
        self.db.execute("UPDATE phones SET seen=? WHERE id=?", (int(time.time()), pid))
        return pid

    # ------------------------------------------------------------ PC hub
    async def hub(self, request):
        hub_id = request.query.get("id", "")
        secret = request.headers.get("X-Hub-Secret", "")
        if not (8 <= len(hub_id) <= 40 and len(secret) >= 20):
            raise web.HTTPBadRequest(text="bad hub")
        row = self.db.execute("SELECT secret FROM hubs WHERE id=?", (hub_id,)).fetchone()
        if row is None:
            self.db.execute("INSERT INTO hubs VALUES (?,?,?,?)", (hub_id, _h(secret), int(time.time()), 0))
            self.db.commit()
            log.info("New hub %s", hub_id)
        elif not hmac.compare_digest(row[0], _h(secret)):
            raise web.HTTPForbidden(text="wrong hub secret")
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)
        old = self.hubs.get(hub_id)
        if old is not None and not old.closed:
            await old.close()
        self.hubs[hub_id] = ws
        self.db.execute("UPDATE hubs SET seen=? WHERE id=?", (int(time.time()), hub_id))
        self.db.commit()
        log.info("Hub %s online", hub_id)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("t") == "reply":
                        fut = self.pending.pop(data.get("id"), None)
                        if fut is not None and not fut.done():
                            fut.set_result(data)
                elif msg.type == WSMsgType.BINARY and len(msg.data) > 4:
                    sid = struct.unpack(">I", msg.data[:4])[0]
                    resp = self.streams.get(sid)
                    if resp is not None:
                        frame = msg.data[4:]
                        try:
                            await resp.write(struct.pack(">I", len(frame)) + frame)
                        except (ConnectionError, RuntimeError):
                            self.streams.pop(sid, None)
                            await ws.send_json({"t": "stream_end", "id": sid})
        finally:
            if self.hubs.get(hub_id) is ws:
                del self.hubs[hub_id]
            log.info("Hub %s offline", hub_id)
        return ws

    async def call(self, request):
        self._limited(request)
        hub_id = request.match_info["hub"]
        body = await self._json(request)
        ws = self.hubs.get(hub_id)
        if ws is None or ws.closed:
            return web.json_response({"error": "pc_offline"}, status=503)
        cid = self._id()
        fut = asyncio.get_running_loop().create_future()
        self.pending[cid] = fut
        await ws.send_json({"t": "call", "id": cid, "body": body})
        try:
            reply = await asyncio.wait_for(fut, CALL_TIMEOUT)
        except asyncio.TimeoutError:
            self.pending.pop(cid, None)
            return web.json_response({"error": "pc_timeout"}, status=504)
        return web.json_response(reply.get("body", {}), status=int(reply.get("status", 200)))

    async def stream(self, request):
        self._limited(request)
        hub_id = request.match_info["hub"]
        body = await self._json(request)
        ws = self.hubs.get(hub_id)
        if ws is None or ws.closed:
            return web.json_response({"error": "pc_offline"}, status=503)
        sid = self._id()
        resp = web.StreamResponse(headers={"Content-Type": "application/octet-stream", "Cache-Control": "no-store"})
        await resp.prepare(request)
        self.streams[sid] = resp
        await ws.send_json({"t": "stream", "id": sid, "body": body})
        try:
            while sid in self.streams and not ws.closed and request.transport is not None \
                    and not request.transport.is_closing():
                await asyncio.sleep(0.5)
        finally:
            self.streams.pop(sid, None)
            if not ws.closed:
                await ws.send_json({"t": "stream_end", "id": sid})
        return resp

    # ------------------------------------------------------------ phones
    async def register_phone(self, request):
        self._limited(request)
        pid, secret = secrets.token_hex(8), secrets.token_urlsafe(24)
        self.db.execute("INSERT INTO phones VALUES (?,?,?,?)", (pid, _h(secret), int(time.time()), int(time.time())))
        self.db.commit()
        return web.json_response({"phone_id": pid, "secret": secret})

    async def create_invite(self, request):
        self._limited(request)
        pid = self._phone(request)
        body = await self._json(request)
        pub, name = str(body.get("pub", ""))[:400], str(body.get("name", ""))[:40]
        if not pub:
            return web.json_response({"error": "no_pub"}, status=400)
        self.db.execute("DELETE FROM invites WHERE expires < ?", (int(time.time()),))
        for _ in range(20):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if not self.db.execute("SELECT 1 FROM invites WHERE code=?", (code,)).fetchone():
                break
        self.db.execute("INSERT INTO invites (code, phone_id, pub, name, expires) VALUES (?,?,?,?,?)",
                        (code, pid, pub, name, int(time.time()) + INVITE_SECONDS))
        self.db.commit()
        return web.json_response({"code": code, "expires_in": INVITE_SECONDS})

    def _invite(self, request, code):
        if not self.invite_limit.allow(self._ip(request)):  # 6-digit codes must not be guessable
            raise web.HTTPTooManyRequests(text='{"error":"slow_down"}', content_type="application/json")
        row = self.db.execute("SELECT phone_id, pub, name, expires, acc_id, acc_pub, acc_name FROM invites "
                              "WHERE code=?", (code,)).fetchone()
        if row is None or row[3] < time.time():
            raise web.HTTPNotFound(text='{"error":"bad_code"}', content_type="application/json")
        return row

    async def get_invite(self, request):
        self._phone(request)
        row = self._invite(request, request.match_info["code"])
        return web.json_response({"phone_id": row[0], "pub": row[1], "name": row[2]})

    async def accept_invite(self, request):
        pid = self._phone(request)
        code = request.match_info["code"]
        row = self._invite(request, code)
        if row[4]:
            return web.json_response({"error": "already_used"}, status=409)
        if row[0] == pid:
            return web.json_response({"error": "own_invite"}, status=400)
        body = await self._json(request)
        self.db.execute("UPDATE invites SET acc_id=?, acc_pub=?, acc_name=? WHERE code=?",
                        (pid, str(body.get("pub", ""))[:400], str(body.get("name", ""))[:40], code))
        self.db.execute("INSERT OR IGNORE INTO contacts VALUES (?,?)", (row[0], pid))
        self.db.execute("INSERT OR IGNORE INTO contacts VALUES (?,?)", (pid, row[0]))
        self.db.commit()
        return web.json_response({"ok": True})

    async def invite_result(self, request):
        pid = self._phone(request)
        row = self.db.execute("SELECT phone_id, acc_id, acc_pub, acc_name FROM invites WHERE code=?",
                              (request.match_info["code"],)).fetchone()
        if row is None or row[0] != pid:
            return web.json_response({"error": "bad_code"}, status=404)
        if not row[1]:
            return web.json_response({"waiting": True})
        return web.json_response({"phone_id": row[1], "pub": row[2], "name": row[3]})

    async def put_status(self, request):
        pid = self._phone(request)
        body = await self._json(request)
        now = int(time.time())
        for to, sealed in dict(body.get("to", {})).items():
            if self.db.execute("SELECT 1 FROM contacts WHERE a=? AND b=?", (pid, to)).fetchone():
                self.db.execute("INSERT OR REPLACE INTO status VALUES (?,?,?,?)", (pid, to, str(sealed)[:8000], now))
        self.db.commit()
        return web.json_response({"ok": True})

    async def get_status(self, request):
        pid = self._phone(request)
        rows = self.db.execute("SELECT s.sender, s.sealed, s.at FROM status s JOIN contacts c "
                               "ON c.a = s.receiver AND c.b = s.sender WHERE s.receiver=?", (pid,)).fetchall()
        return web.json_response({"from": {r[0]: {"sealed": r[1], "at": r[2]} for r in rows}})

    async def delete_contact(self, request):
        pid = self._phone(request)
        other = request.match_info["phone"]
        self.db.execute("DELETE FROM contacts WHERE (a=? AND b=?) OR (a=? AND b=?)", (pid, other, other, pid))
        self.db.execute("DELETE FROM status WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)",
                        (pid, other, other, pid))
        self.db.commit()
        return web.json_response({"ok": True})

    # ------------------------------------------------------------ web
    async def landing(self, request):
        kind = "pc" if request.path.startswith("/p") else "phone"
        with open(os.path.join(STATIC, "landing.html"), encoding="utf-8") as f:
            html = f.read().replace("{{KIND}}", kind).replace("{{APK_URL}}", APK_URL)
        return web.Response(text=html, content_type="text/html")

    async def health(self, _request):
        return web.json_response({"ok": True, "hubs_online": len(self.hubs)})


def make_app(db_path=DB_PATH):
    relay = Relay(db_path)
    app = web.Application(client_max_size=MAX_BODY)
    app.add_routes([
        web.get("/v1/hub", relay.hub),
        web.post("/v1/hub/{hub}/call", relay.call),
        web.post("/v1/hub/{hub}/stream", relay.stream),
        web.post("/v1/phones", relay.register_phone),
        web.post("/v1/invites", relay.create_invite),
        web.get("/v1/invites/{code}", relay.get_invite),
        web.post("/v1/invites/{code}/accept", relay.accept_invite),
        web.get("/v1/invites/{code}/result", relay.invite_result),
        web.put("/v1/status", relay.put_status),
        web.get("/v1/status", relay.get_status),
        web.delete("/v1/contacts/{phone}", relay.delete_contact),
        web.get("/p/", relay.landing),
        web.get("/i/", relay.landing),
        web.get("/health", relay.health),
    ])
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    web.run_app(make_app(), host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8080")))
