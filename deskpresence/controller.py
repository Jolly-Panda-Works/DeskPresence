"""The brain: presence state machine, gaze->cursor, desktop<->laptop sync."""
import logging
import threading
import time

from . import winapi
from .i18n import t
from .media import MediaController
from .network import Link
from .notifications import NotificationWatcher
from .vision import FaceSensor, GazeClassifier

log = logging.getLogger(__name__)

PRESENT, AWAY = "present", "away"
LAPTOP = "laptop"


class Controller:
    def __init__(self, cfg, ui):
        self.cfg, self.ui = cfg, ui
        self.on_state = lambda: None
        self.media = MediaController(cfg)
        self.state = PRESENT
        self.paused = False
        self.calibrating = False
        self.status = "starting"
        self.peer_connected = False
        self.monitors = winapi.list_monitors()
        self._monitors_at = time.monotonic()
        self.gaze = GazeClassifier(cfg["calibration"], cfg["gaze_stable_seconds"])
        self.sensor = None
        self.link = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._reopen = False
        self._last_obs = None
        self._last_obs_at = 0.0
        self._last_pos = {}
        self._pending_target = None
        self._on_laptop = False
        now = time.monotonic()
        self._last_face = now
        self._face_streak = 0
        self._away_since = now
        self._present_since = now
        self._locked = False
        self._break_reminded = False
        # water reminder + forced break
        self._next_water = now + self.cfg["water_reminder_minutes"] * 60
        self._work_since = now
        self.break_active = False
        self._break_left = 0.0
        self._break_ui_at = 0.0
        self._break_sent_at = 0.0
        self._break_done_notice = False
        self._last_tick = now
        self._status_refresh_at = now

    # ------------------------------------------------------------ lifecycle
    @property
    def role(self):
        return self.cfg["role"]

    @property
    def uses_camera(self):
        return self.role == "desktop" or self.cfg["laptop_use_camera"]

    def start(self):
        if self.cfg["network_enabled"]:
            self.link = Link(self.role, self.cfg["port"], self.cfg["token"], self.cfg["desktop_host"],
                             on_message=self._on_remote, on_status=self._on_link_status)
            self.link.start()
        if self.role == LAPTOP and self.cfg["network_enabled"] and self.cfg["forward_notifications"]:
            NotificationWatcher(self._forward_notification, self.cfg["dismiss_forwarded"]).start()
        threading.Thread(target=self._run, daemon=True, name="controller").start()

    def stop(self):
        self._stop.set()
        if self.state == AWAY:
            self.come_back(local=True)
        if self.link:
            self.link.stop()

    def reload(self):
        old_cam = self.cfg["camera_index"]
        self.cfg.load()
        self.gaze = GazeClassifier(self.cfg["calibration"], self.cfg["gaze_stable_seconds"])
        self.monitors = winapi.list_monitors()
        if self.cfg["camera_index"] != old_cam:
            self._reopen = True
        self._set_status(self.status)

    def set_paused(self, paused):
        self.paused = paused
        if paused and self.break_active:
            self.end_break(skipped=True)
        if paused and self.state == AWAY:
            self.come_back(local=True)
        self._set_status("paused" if paused else "starting")

    def _set_status(self, text):
        self.status = text
        try:
            self.on_state()
        except Exception:
            log.exception("on_state failed")

    # ------------------------------------------------------------ main loop
    def _run(self):
        if not self.uses_camera:
            self._set_status("laptop_wait")
            self._stop.wait()
            return
        errors = 0
        while not self._stop.is_set():
            if self.paused:
                self._close_sensor()
                self._stop.wait(0.5)
                continue
            if self.sensor is None or self._reopen:
                self._reopen = False
                self._close_sensor()
                try:
                    self.sensor = FaceSensor(self.cfg["camera_index"])
                    self._last_face = time.monotonic()
                    self._set_status(self.state)
                except Exception as e:
                    log.error("Camera error: %s", e)
                    self._set_status("camera_error")
                    self._stop.wait(5)
                    continue
            t0 = time.monotonic()
            obs = self.sensor.read()
            if obs is None:
                errors += 1
                if errors > 20:
                    errors = 0
                    self._reopen = True
                self._stop.wait(0.2)
                continue
            errors = 0
            try:
                self._process(obs, time.monotonic())
            except Exception:
                log.exception("process failed")
            period = 1.0 / max(1, self.cfg["camera_fps"])
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))
        self._close_sensor()

    def _close_sensor(self):
        if self.sensor:
            self.sensor.close()
            self.sensor = None

    def _process(self, obs, now):
        if obs.face:
            self._last_face = now
            self._face_streak += 1
            self._last_obs, self._last_obs_at = obs, now
        else:
            self._face_streak = 0
        if self.calibrating:
            self._last_tick = now
            return

        if self.state == PRESENT:
            if now - self._last_face >= self.cfg["away_seconds"] \
                    and winapi.idle_seconds() >= self.cfg["idle_guard_seconds"]:
                self.go_away(local=True)
            elif not self.break_active:
                self._gaze_step(obs, now)
                self._break_step(now)
                self._water_step(now)
                self._work_step(now)
        else:
            back_input = self.cfg["wake_on_input"] and winapi.idle_seconds() < 1.0
            if self._face_streak >= self.cfg["back_frames"] or back_input:
                self.come_back(local=True)
            elif self.cfg["lock_after_away_minutes"] > 0 and not self._locked \
                    and now - self._away_since >= self.cfg["lock_after_away_minutes"] * 60:
                self._locked = True
                winapi.lock_workstation()

        if self.break_active:
            self._forced_break_tick(now)
        self._last_tick = now
        if now - self._status_refresh_at >= 60:  # keeps "next break in X min" fresh
            self._status_refresh_at = now
            self._set_status(self.status)

    # ------------------------------------------------------------ presence actions
    def go_away(self, local):
        with self._lock:
            if self.state == AWAY:
                return
            log.info("AWAY (local=%s)", local)
            self.state = AWAY
            self._away_since = time.monotonic()
            self._locked = False
            if self.cfg["pause_media"]:
                self.media.pause()
            if self.cfg["turn_off_monitors"]:
                time.sleep(0.3)
                winapi.monitors_off()
            if local and self.link:
                self.link.send({"type": "away"})
        self._set_status(AWAY)

    def come_back(self, local):
        with self._lock:
            if self.state == PRESENT:
                return
            log.info("BACK (local=%s)", local)
            self.state = PRESENT
            now = time.monotonic()
            self._present_since = self._last_face = now
            self._break_reminded = False
            # being away for a full break length counts as a break
            if now - self._away_since >= self.cfg["forced_break"]["break_minutes"] * 60:
                self._work_since = now
            self.gaze.reset()
            if self.cfg["turn_off_monitors"]:
                winapi.monitors_on()
            if self.cfg["pause_media"]:
                self.media.resume()
            if local and self.link:
                self.link.send({"type": "back"})
        self._set_status("break" if self.break_active else PRESENT)
        if self._break_done_notice:
            self._break_done_notice = False
            self.popup(t("break.done.title"), t("break.done.body"))

    # ------------------------------------------------------------ water + forced break
    def _water_step(self, now):
        mins = self.cfg["water_reminder_minutes"]
        if mins > 0 and now >= self._next_water:
            self._next_water = now + mins * 60
            winapi.beep()
            self.popup(t("water.title"), t("water.body"), seconds=15)

    def _work_step(self, now):
        fb = self.cfg["forced_break"]
        if fb["enabled"] and now - self._work_since >= fb["work_minutes"] * 60:
            self.start_break()

    def next_break_minutes(self):
        fb = self.cfg["forced_break"]
        if not fb["enabled"] or not self.uses_camera:
            return None
        left = fb["work_minutes"] * 60 - (time.monotonic() - self._work_since)
        return max(0, int(left // 60))

    def start_break(self):
        with self._lock:
            if self.break_active:
                return
            fb = self.cfg["forced_break"]
            log.info("Forced break started")
            self.break_active = True
            self._break_left = fb["break_minutes"] * 60.0
            self._pending_target = None
            self.ui.break_show(winapi.list_monitors(), fb["allow_skip"],
                               lambda: self.end_break(skipped=True))
            self._push_break(time.monotonic(), counting=False, force=True)
        winapi.beep()
        self._set_status("break")

    def end_break(self, skipped=False):
        with self._lock:
            if not self.break_active:
                return
            log.info("Forced break ended (skipped=%s)", skipped)
            self.break_active = False
            self._work_since = time.monotonic()
            self.ui.break_hide()
            if self.link:
                self.link.send({"type": "break", "active": False})
            if not skipped:
                if self.state == AWAY:
                    self._break_done_notice = True
                else:
                    self.popup(t("break.done.title"), t("break.done.body"))
        self._set_status(self.state)

    def _forced_break_tick(self, now):
        # the countdown only runs while the camera does not see you
        absent = self.state == AWAY or now - self._last_face >= self.cfg["away_seconds"]
        if absent:
            self._break_left -= max(0.0, min(2.0, now - self._last_tick))
        if self._break_left <= 0:
            self.end_break()
            return
        self._push_break(now, counting=absent)

    def _push_break(self, now, counting, force=False):
        if force or now - self._break_ui_at >= 0.5:
            self._break_ui_at = now
            self.ui.break_update(self._break_left, counting)
        if self.link and (force or now - self._break_sent_at >= 3):
            self._break_sent_at = now
            self.link.send({"type": "break", "active": True, "left": self._break_left, "counting": counting})

    def _break_step(self, now):
        mins = self.cfg["break_reminder_minutes"]
        if mins > 0 and not self._break_reminded and now - self._present_since >= mins * 60:
            self._break_reminded = True
            self.popup(t("remind.title"), t("remind.body", mins=mins))

    # ------------------------------------------------------------ gaze -> cursor
    def _gaze_step(self, obs, now):
        if not (self.cfg["gaze_follow"] and self.sensor and self.sensor.supports_gaze and self.gaze.ready):
            return
        if obs.face:
            target = self.gaze.update(obs.yaw, obs.pitch, now)
            if target:
                self._pending_target = target
        if self._pending_target is None:
            return
        if winapi.mouse_button_down() or winapi.idle_seconds() < self.cfg["gaze_mouse_quiet_seconds"]:
            return  # wait until the user stops using the mouse/keyboard
        target, self._pending_target = self._pending_target, None
        self._focus(target)

    def _monitor_by_name(self, name):
        if time.monotonic() - self._monitors_at > 30:
            self.monitors = winapi.list_monitors()
            self._monitors_at = time.monotonic()
        return next((m for m in self.monitors if m.name == name), None)

    def _focus(self, target):
        mwb = self.cfg["mwb"]
        x, y = winapi.get_cursor()
        cur = next((m for m in self.monitors if m.contains(x, y)), None)

        if target == LAPTOP:
            if mwb["enabled"] and not self._on_laptop:
                if cur:
                    self._last_pos[cur.name] = (x, y)
                winapi.press_ctrl_alt_f(mwb["laptop_hotkey"])
                self._on_laptop = True
                log.info("Gaze -> laptop")
            return

        mon = self._monitor_by_name(target)
        if mon is None:
            return
        if self._on_laptop and mwb["enabled"]:
            winapi.press_ctrl_alt_f(mwb["desktop_hotkey"])
            self._on_laptop = False
            time.sleep(0.15)
        elif cur is not None and cur.name == target:
            return
        if cur is not None:
            self._last_pos[cur.name] = (x, y)
        px, py = self._last_pos.get(target, mon.center)
        if not mon.contains(px, py):
            px, py = mon.center
        winapi.set_cursor(px, py)
        log.info("Gaze -> %s", target)

    # ------------------------------------------------------------ calibration
    def calibration_targets(self):
        self.monitors = winapi.list_monitors()
        targets = [(m.name, t("cal.look_monitor", n=m.index + 1), m) for m in self.monitors]
        if self.cfg["mwb"]["enabled"]:
            primary = winapi.pick_monitor(self.monitors, -1)
            targets.append((LAPTOP, t("cal.look_laptop"), primary))
        return targets

    def start_calibration(self):
        if not self.uses_camera:
            self.popup(t("cal.title"), t("cal.no_camera"))
            return
        if self.sensor is None or not self.sensor.supports_gaze:
            self.popup(t("cal.title"), t("cal.not_ready"))
            return
        self.calibrating = True

        def sample():
            if self._last_obs and time.monotonic() - self._last_obs_at < 0.4:
                return self._last_obs.yaw, self._last_obs.pitch
            return None

        self.ui.calibrate(self.calibration_targets(), sample, self._calibration_done)

    def _calibration_done(self, results):
        self.calibrating = False
        self._last_face = time.monotonic()
        if results is None:
            self.popup(t("cal.cancelled"), "")
            return
        good = {k: v for k, v in results.items() if v}
        failed = [k for k, v in results.items() if not v]
        if len(good) < 2:
            self.popup(t("cal.failed"), t("cal.failed_body"))
            return
        self.cfg.set("calibration", good)
        self.gaze = GazeClassifier(good, self.cfg["gaze_stable_seconds"])
        msg = t("cal.done_body")
        if failed:
            msg += "\n" + t("cal.missing", names=", ".join(failed))
        self.popup(t("cal.done"), msg)

    # ------------------------------------------------------------ network
    def _on_link_status(self, connected):
        self.peer_connected = connected
        self._set_status(self.status)

    def _on_remote(self, msg):
        kind = msg.get("type")
        if kind == "notification" and self.role == "desktop":
            self.popup(msg.get("title", ""), msg.get("body", ""), source=f"💻 {msg.get('app', 'Laptop')}")
        elif kind == "away" and self.role == LAPTOP and not self.paused:
            self.go_away(local=False)
        elif kind == "back" and self.role == LAPTOP:
            self.come_back(local=False)
        elif kind == "break" and self.role == LAPTOP:
            # the desktop drives the break; the laptop just mirrors the cover screen
            if msg.get("active"):
                if not self.break_active:
                    self.break_active = True
                    self.ui.break_show(winapi.list_monitors(), False, None)
                self.ui.break_update(float(msg.get("left", 0)), bool(msg.get("counting")))
            elif self.break_active:
                self.break_active = False
                self.ui.break_hide()

    def _forward_notification(self, app, title, body):
        if self.link:
            self.link.send({"type": "notification", "app": app, "title": title, "body": body})

    # ------------------------------------------------------------ helpers
    def popup(self, title, body, source="", seconds=None):
        mon = winapi.pick_monitor(winapi.list_monitors(), self.cfg["notification_monitor"])
        self.ui.popup(title, body, mon, seconds or self.cfg["notification_seconds"], source)
