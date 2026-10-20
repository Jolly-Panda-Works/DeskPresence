"""The brain: presence state machine, gaze->cursor, desktop<->laptop sync."""
import copy
import logging
import math
import threading
import time

from . import eyetrack, winapi
from .i18n import t
from .media import MediaController
from .network import Link
from .camshare import CameraShare
from .notifications import NotificationWatcher
from .phone import PhoneWatcher
from .vision import FaceSensor, GazeClassifier

log = logging.getLogger(__name__)

PRESENT, AWAY = "present", "away"
LAPTOP = "laptop"
MOUSE_OFF, MOUSE_MONITOR, MOUSE_EYES = "off", "monitor", "eyes"
NETWORK_KEYS = ("network_enabled", "role", "port", "desktop_host", "token",
                "forward_notifications", "dismiss_forwarded")


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
        self._watcher = None
        # eye tracking (mouse_mode == "eyes")
        self._eye = None
        self._eye_failed = False
        self.eye_active = True                 # toggled with Ctrl+Alt+E
        self.eye_mapper = eyetrack.GazeMapper(cfg["eye_calibration"])
        self._eye_filter = eyetrack.OneEuro()
        self._eye_feat = None
        self._eye_feat_at = 0.0
        self._eye_set = None
        self._eye_prev = None
        self._eye_hold_until = 0.0
        self._hotkey_down = False
        # phone over Bluetooth
        self._phone = None
        self._phone_at_away = None
        # webcam sharing with other apps
        self._camshare = None
        self._share_checked_at = 0.0
        self._share_declined = {}
        self._asking = False
        self.camera_lent_to = None             # (registry key, app name) while another app has it
        self._lent_free_since = None
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
        self._start_network()
        threading.Thread(target=self._run, daemon=True, name="controller").start()

    def _start_network(self):
        if self.cfg["network_enabled"]:
            self.link = Link(self.role, self.cfg["port"], self.cfg["token"], self.cfg["desktop_host"],
                             on_message=self._on_remote, on_status=self._on_link_status)
            self.link.start()
        if self.role == LAPTOP and self.cfg["network_enabled"] and self.cfg["forward_notifications"]:
            self._watcher = NotificationWatcher(self._forward_notification, self.cfg["dismiss_forwarded"])
            self._watcher.start()

    def _stop_network(self):
        if self.link:
            self.link.stop()
            self.link = None
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        self.peer_connected = False

    def stop(self):
        self._stop.set()
        if self.state == AWAY:
            self.come_back(local=True)
        self._stop_network()

    def reload(self):
        """Re-reads config.json from disk (after editing it by hand)."""
        old = copy.deepcopy(self.cfg.data)
        self.cfg.load()
        self.apply_settings(old)

    def apply_settings(self, old):
        """Applies changed settings at once; called after the settings window saves."""
        new = self.cfg.data
        self.gaze = GazeClassifier(new["calibration"], new["gaze_stable_seconds"])
        self.eye_mapper = eyetrack.GazeMapper(new["eye_calibration"])
        self.monitors = winapi.list_monitors()
        if new["camera_index"] != old.get("camera_index"):
            self._reopen = True
        if any(new.get(k) != old.get(k) for k in NETWORK_KEYS):
            log.info("Network settings changed, restarting the link")
            self._stop_network()
            self._start_network()
        if new["water_reminder_minutes"] != old.get("water_reminder_minutes"):
            self._next_water = time.monotonic() + new["water_reminder_minutes"] * 60
        if new["mouse_mode"] != MOUSE_EYES:
            self._close_eye()
        self._set_status(self.state if self.uses_camera else "laptop_wait")

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
    @property
    def camera_wanted(self):
        return (self.uses_camera and not self.paused and self.camera_lent_to is None
                and (self.cfg["presence_source"] in ("camera", "both") or self.cfg["mouse_mode"] != MOUSE_OFF))

    @property
    def phone_wanted(self):
        return (self.uses_camera and not self.paused and self.cfg["presence_source"] in ("phone", "both")
                and bool(self.cfg["phone"]["device_id"]))

    def _run(self):
        errors = 0
        camera_retry_at = 0.0
        while not self._stop.is_set():
            if not self.uses_camera:  # laptop role: the desktop drives everything
                self._close_sensor()
                self._sync_phone()
                if self.status != "laptop_wait":
                    self._set_status("laptop_wait")
                self._stop.wait(0.5)
                continue
            if self.paused:
                self._close_sensor()
                self._sync_phone()
                self._stop.wait(0.5)
                continue
            t0 = time.monotonic()
            self._sync_phone()
            self._camera_share_step(t0)

            obs = None
            if not self.camera_wanted:
                self._close_sensor()
            else:
                if (self.sensor is None or self._reopen) and t0 >= camera_retry_at:
                    self._reopen = False
                    self._close_sensor()
                    try:
                        self.sensor = FaceSensor(self.cfg["camera_index"])
                        self._last_face = time.monotonic()
                        self._set_status(self.state)
                    except Exception as e:
                        log.error("Camera error: %s", e)
                        self._set_status("camera_error")
                        camera_retry_at = t0 + 5
                if self.sensor is not None:
                    obs = self.sensor.read()
                    if obs is None:
                        errors += 1
                        if errors > 20:
                            errors = 0
                            self._reopen = True
                    else:
                        errors = 0
            try:
                self._process(obs, time.monotonic())
            except Exception:
                log.exception("process failed")
            if self.sensor is not None:
                fps = self.cfg["camera_fps"]
                if self.cfg["mouse_mode"] == MOUSE_EYES:
                    fps = max(fps, 15)  # eye control needs a smoother stream
                period = 1.0 / max(1, fps)
            else:
                period = 0.5
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))
        self._close_sensor()
        self._stop_phone()

    def _close_sensor(self):
        if self.sensor:
            self.sensor.close()
            self.sensor = None
        self._close_eye()

    def _close_eye(self):
        if self._eye:
            self._eye.close()
            self._eye = None
        self._eye_feat = None

    # ------------------------------------------------------------ phone
    def _sync_phone(self):
        """Starts / stops the Bluetooth watcher to match the settings."""
        ph = self.cfg["phone"]
        want = self.phone_wanted
        if self._phone and (not want or self._phone.device_id != ph["device_id"]):
            self._stop_phone()
        if want and self._phone is None:
            self._phone = PhoneWatcher(ph["device_id"], ph["check_seconds"], ph["away_checks"])
            self._phone.start()

    def _stop_phone(self):
        if self._phone:
            self._phone.stop()
            self._phone = None

    @property
    def phone_near(self):
        return self._phone.near if self._phone else None

    # ------------------------------------------------------------ webcam sharing
    def _camera_share_step(self, now):
        if now - self._share_checked_at < 1.0 or self.cfg["camera_share"] == "never":
            return
        self._share_checked_at = now
        if self._camshare is None:
            try:
                self._camshare = CameraShare()
            except Exception:
                log.exception("Webcam sharing unavailable")
                self.cfg.data["camera_share"] = "never"
                return
            return
        if self.camera_lent_to is not None:
            key, name = self.camera_lent_to
            if self._camshare.still_using(key):
                self._lent_free_since = None
            elif self._lent_free_since is None:
                self._lent_free_since = now
            elif now - self._lent_free_since >= 3:
                log.info("%s released the webcam, taking it back", name)
                self.camera_lent_to = None
                self._camshare.new_requests()  # don't treat our own reopen as a request
                self.popup(t("cam.back.title"), t("cam.back.body", app=name))
            return
        requests = self._camshare.new_requests()
        if self.sensor is None:
            return
        for key, name in requests:
            if self._asking or self._share_declined.get(key, 0) > now:
                continue
            if self.cfg["camera_share"] == "always":
                self._lend_camera(key, name)
            else:
                self._asking = True
                self.ui.ask(t("cam.ask.title", app=name), t("cam.ask.body", app=name),
                            t("cam.ask.yes"), t("cam.ask.no"),
                            lambda yes, k=key, n=name: self._answer_share(yes, k, n),
                            winapi.pick_monitor(self.monitors, self.cfg["notification_monitor"]))
            break

    def _answer_share(self, yes, key, name):
        self._asking = False
        if yes:
            self._lend_camera(key, name)
        else:
            self._share_declined[key] = time.monotonic() + 120

    def _lend_camera(self, key, name):
        log.info("Handing the webcam to %s", name)
        self.camera_lent_to = (key, name)
        self._lent_free_since = None
        self._reopen = True
        self._set_status("camera_lent")
        self.popup(t("cam.lent.title", app=name), t("cam.lent.body"), seconds=10)

    # ------------------------------------------------------------ presence
    def _process(self, obs, now):
        """One tick. obs is the webcam observation, or None when the webcam is not in use."""
        if obs is not None:
            if obs.face:
                self._last_face = now
                self._face_streak += 1
                self._last_obs, self._last_obs_at = obs, now
            else:
                self._face_streak = 0
        phone = self.phone_near
        if phone:
            self._last_face = now
        have_source = obs is not None or phone is not None

        eyes = (obs is not None and self.cfg["mouse_mode"] == MOUSE_EYES
                and self.state == PRESENT and not self.break_active)
        if eyes:
            self._eye_features(now)
        if self.calibrating:
            self._last_tick = now
            return

        idle = winapi.idle_seconds()
        if self.state == PRESENT:
            if have_source:
                gone = now - self._last_face >= self.cfg["away_seconds"] and idle >= self.cfg["idle_guard_seconds"]
            else:  # no webcam and no phone: only keyboard / mouse inactivity is left
                gone = idle >= self.cfg["idle_fallback_minutes"] * 60
            if gone:
                self.go_away(local=True)
            elif not self.break_active:
                if eyes:
                    self._eye_hotkey()
                    self._eye_step(now)
                elif obs is not None:
                    self._gaze_step(obs, now)
                self._break_step(now)
                self._water_step(now)
                self._work_step(now)
        else:
            back_input = self.cfg["wake_on_input"] and idle < 1.0
            back_phone = phone is True and self._phone_at_away is not True
            if self._face_streak >= self.cfg["back_frames"] or back_input or back_phone:
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
            self._phone_at_away = self.phone_near
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
        if not (self.cfg["mouse_mode"] == MOUSE_MONITOR and self.sensor and self.sensor.supports_gaze and self.gaze.ready):
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

    # ------------------------------------------------------------ eyes -> cursor
    def _eye_features(self, now):
        if self._eye is None:
            if self._eye_failed or not eyetrack.available():
                self._eye_failed = True
                return
            try:
                self._eye = eyetrack.EyeTracker()
                self._eye_filter.reset()
                log.info("Eye tracker ready")
            except Exception:
                log.exception("Eye tracker unavailable")
                self._eye_failed = True
                return
        frame = self.sensor.last_frame if self.sensor else None
        if frame is None:
            return
        try:
            self._eye_feat = self._eye.features(frame, now)
            self._eye_feat_at = now
        except Exception:
            log.exception("Eye tracking failed")
            self._eye_feat = None

    def _eye_hotkey(self):
        down = winapi.keys_down(winapi.VK_CONTROL, winapi.VK_MENU, 0x45)  # Ctrl+Alt+E
        if down and not self._hotkey_down:
            self.eye_active = not self.eye_active
            self._eye_filter.reset()
            self.popup(t("eyes.on") if self.eye_active else t("eyes.off"), t("eyes.hotkey"), seconds=3)
        self._hotkey_down = down

    def _eye_step(self, now):
        if not (self.eye_active and self.eye_mapper.ok) or self._eye_feat is None:
            return
        x, y = self._eye_filter(self.eye_mapper.predict(self._eye_feat), now)
        x, y = self._clamp_to_monitors(x, y)
        cur = winapi.get_cursor()
        # the user moved the mouse themselves -> step aside for a moment
        if self._eye_prev is not None and cur != self._eye_prev and cur != self._eye_set:
            self._eye_hold_until = now + self.cfg["eye_pause_after_mouse_seconds"]
        self._eye_prev = cur
        if now < self._eye_hold_until or winapi.mouse_button_down():
            return
        if math.hypot(x - cur[0], y - cur[1]) < self.cfg["eye_deadzone_px"]:
            return
        self._eye_set = (int(x), int(y))
        winapi.set_cursor(*self._eye_set)
        self._eye_prev = winapi.get_cursor()

    def _clamp_to_monitors(self, x, y):
        best, best_d = (x, y), None
        for m in self.monitors:
            l, t_, r, b = m.rect
            cx, cy = min(max(x, l), r - 1), min(max(y, t_), b - 1)
            d = (cx - x) ** 2 + (cy - y) ** 2
            if best_d is None or d < best_d:
                best, best_d = (cx, cy), d
        return best

    def eye_calibration_points(self):
        self.monitors = winapi.list_monitors()
        points = []
        for m in self.monitors:
            l, t_, r, b = m.rect
            w, h = r - l, b - t_
            for fx, fy in ((0.5, 0.5), (0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)):
                points.append((m, int(l + fx * w), int(t_ + fy * h)))
        return points

    def start_eye_calibration(self):
        if not self.uses_camera:
            self.popup(t("cal.title"), t("cal.no_camera"))
            return
        if not eyetrack.available():
            self.popup(t("cal.title"), t("eyes.unavailable"))
            return
        if self.cfg["mouse_mode"] != MOUSE_EYES:
            self.cfg.set("mouse_mode", MOUSE_EYES)
        self._eye_failed = False
        threading.Thread(target=self._eye_calibration_when_ready, daemon=True).start()

    def _eye_calibration_when_ready(self):
        # switching to eye mode may first have to open the webcam and load the model
        end = time.monotonic() + 10
        while time.monotonic() < end and not (self._eye is not None and self.sensor is not None):
            if self._eye_failed:
                break
            time.sleep(0.2)
        if self._eye is None or self.sensor is None:
            self.popup(t("cal.title"), t("cal.not_ready"))
            return
        self.calibrating = True

        def sample():
            if self._eye_feat is not None and time.monotonic() - self._eye_feat_at < 0.3:
                return self._eye_feat.tolist()
            return None

        self.ui.calibrate_points(self.eye_calibration_points(), sample, self._eye_calibration_done)

    def _eye_calibration_done(self, samples):
        self.calibrating = False
        self._last_face = time.monotonic()
        if samples is None:
            self.popup(t("cal.cancelled"), "")
            return
        if len(samples) < 30:
            self.popup(t("cal.failed"), t("cal.failed_body"))
            return
        feats = [s[0] for s in samples]
        pts = [s[1] for s in samples]
        mapper, err = eyetrack.GazeMapper.fit(feats, pts)
        data = mapper.to_dict()
        data["error_px"] = round(err)
        self.cfg.set("eye_calibration", data)
        self.eye_mapper = mapper
        self._eye_filter.reset()
        self.eye_active = True
        log.info("Eye calibration: %d samples, median error %d px", len(samples), err)
        self.popup(t("cal.done"), t("eyes.done_body", px=round(err)), seconds=10)

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
