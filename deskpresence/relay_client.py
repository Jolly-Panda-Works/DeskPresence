"""Keeps this PC connected to the DeskPresence relay so phones can reach it from anywhere.

One outgoing WebSocket (works behind any router / CGNAT). The relay hands over the phones'
requests as end-to-end encrypted envelopes; this side opens them with the phone's key (e2e.py),
runs them through the same API as the local server (Companion.dispatch) and seals the reply.
Pairing requests are the only plaintext ones (they carry the one-time code and public keys).
"""
import asyncio
import logging
import struct
import threading

from . import e2e

log = logging.getLogger(__name__)


class RelayClient:
    def __init__(self, companion, url, hub_id, hub_secret):
        self.companion = companion
        self.url = url.rstrip("/")
        self.hub_id, self.hub_secret = hub_id, hub_secret
        self.connected = False
        self.error = None
        self._loop = None
        self._ws = None
        self._streams = {}  # stream id -> threading.Event (set = stop)
        self._stop = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def start(self):
        threading.Thread(target=self._thread, daemon=True, name="relay").start()

    def stop(self):
        self._stop.set()
        for ev in self._streams.values():
            ev.set()
        if self._loop and self._ws is not None:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

    def _thread(self):
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._run())
        except Exception:
            log.exception("Relay client crashed")

    async def _run(self):
        import aiohttp
        delay = 2
        ws_url = self.url.replace("https://", "wss://").replace("http://", "ws://") + f"/v1/hub?id={self.hub_id}"
        while not self._stop.is_set():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(ws_url, headers={"X-Hub-Secret": self.hub_secret},
                                                  heartbeat=25, max_msg_size=1 << 20) as ws:
                        self._ws, self.connected, self.error, delay = ws, True, None, 2
                        log.info("Connected to the relay %s", self.url)
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                asyncio.get_running_loop().create_task(self._on_message(ws, msg.json()))
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except Exception as e:
                self.error = str(e)[:120] or type(e).__name__
                log.info("Relay unavailable: %s", self.error)
            finally:
                self.connected, self._ws = False, None
                for ev in self._streams.values():
                    ev.set()
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 60)

    # ------------------------------------------------------------ requests
    async def _on_message(self, ws, msg):
        kind = msg.get("t")
        if kind == "call":
            status, body = await asyncio.to_thread(self.handle_call, msg.get("body") or {})
            await ws.send_json({"t": "reply", "id": msg.get("id"), "status": status, "body": body})
        elif kind == "stream":
            await self._start_stream(ws, msg.get("id"), msg.get("body") or {})
        elif kind == "stream_end":
            ev = self._streams.pop(msg.get("id"), None)
            if ev:
                ev.set()

    def open_envelope(self, envelope):
        """(device_id, device, key, request) or raises PermissionError."""
        c = self.companion
        device_id = str(envelope.get("d", ""))
        device = c.cfg["mobile"]["devices"].get(device_id)
        key = c.device_key(device_id) if device else None
        if key is None:
            raise PermissionError("unpaired")
        try:
            request = e2e.open_sealed(key, envelope, device_id)
        except Exception:
            raise PermissionError("bad_seal")
        if not c.replay.check(envelope.get("n"), request.get("t", 0)):
            raise PermissionError("replay")
        c.touch(device_id)
        return device_id, device, key, request

    def handle_call(self, body):
        """Runs one relayed request (thread pool). Returns (relay status, json)."""
        c = self.companion
        if "pair" in body:  # the only plaintext request: one-time code + public keys
            p = body["pair"] or {}
            result = c.pair(p.get("code", ""), p.get("name", ""), p.get("pub"))
            if result is None:
                return 403, {"error": "bad_code"}
            return 200, c.pair_reply(*result)
        try:
            device_id, device, key, req = self.open_envelope(body)
        except PermissionError as e:
            return 401, {"error": "unpaired" if str(e) != "replay" else "replay"}
        status, reply = c.dispatch(device_id, device, str(req.get("m", "GET")), str(req.get("p", "")),
                                   req.get("b") or {})
        return 200, e2e.seal(key, {"s": status, "b": reply}, device_id)

    async def _start_stream(self, ws, sid, body):
        c = self.companion
        try:
            device_id, device, key, req = self.open_envelope(body)
        except PermissionError:
            await ws.send_json({"t": "stream_end", "id": sid})
            return
        denied = c.camera_denied(device)
        if denied:
            # tell the phone why, as a sealed error frame, then end
            frame = e2e.seal_bytes(key, ('{"error":"%s"}' % denied[1]).encode(), device_id)
            await ws.send_bytes(struct.pack(">I", sid) + frame)
            await ws.send_json({"t": "stream_end", "id": sid})
            return
        stop = threading.Event()
        self._streams[sid] = stop
        loop = asyncio.get_running_loop()

        def pump():
            viewer = c.add_viewer(device["name"])
            log.info("%s started watching the webcam (remote)", device["name"])
            try:
                for jpg in c.frames(lambda: not stop.is_set()):
                    data = struct.pack(">I", sid) + e2e.seal_bytes(key, jpg, device_id)
                    fut = asyncio.run_coroutine_threadsafe(ws.send_bytes(data), loop)
                    fut.result(timeout=10)
            except Exception as e:
                log.info("Remote webcam stream ended: %s", e)
            finally:
                c.remove_viewer(viewer)
                self._streams.pop(sid, None)
                log.info("%s stopped watching the webcam (remote)", device["name"])

        threading.Thread(target=pump, daemon=True, name=f"stream-{sid}").start()
