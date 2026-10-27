"""The brain: presence state machine, gaze->cursor, desktop<->laptop sync."""
import copy
import logging
import math
import threading
import time

from . import camshare, eyetrack, winapi
from .i18n import t
from .media import MediaController
from .network import Link
from .calls import CallWatcher
from .camshare import CameraShare, Lend
from .notifications import NotificationWatcher
from .phone import PhoneWatcher
from .vision import FaceSensor, GazeClassifier

log = logging.getLogger(__name__)

PRESENT, AWAY = "present", "away"
LAPTOP = "laptop"
MOUSE_OFF, MOUSE_MONITOR, MOUSE_EYES = "off", "monitor", "eyes"
SLEEP_GAP_SECONDS = 120
CAMERA_WARMUP = 1.5      # a webcam that was just opened needs a moment before its frames are useful
AWAY_LOOK_SECONDS = 6    # interval mode, while away: how long each short look lasts
ENROLL_SECONDS = 6       # "Teach my face" collects the face this long
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
        self.eye_mapper = eyetrack.GazeMapper(cfg["eye_calibration"])
        self._eye_filter = eyetrack.OneEuro()
        self._eye_feat = None
        self._eye_feat_at = 0.0
        self._eye_set = None
        self._eye_prev = None
        self._eye_hold_until = 0.0
        self._hotkey_down = False
        self._eye_close_wanted = False
        self._calls = None
        self._last_wall = time.time()
        self._countdown_shown = False
        self._countdown_total = 1.0
        # phone over Bluetooth
        self._phone = None
        self._phone_at_away = None
        # webcam sharing with other apps
        self._camshare = None
        self._share_checked_at = 0.0
        self._share_declined = set()
        self._asking = False
        self._lend = None
        self.camera_lent_to = None             # (registry key, app name) while another app has it
        # interval mode: the webcam is off and only opens for a look every few minutes
        self._check_until = None               # end of the current look (math.inf = until you are seen)
        self._next_check_at = 0.0
        self.camera_hold = False               # the settings preview keeps the webcam on
        self._camera_failed = False
        # only the owner turns the PC back on
        self._identity_ok = None               # does the open webcam sensor support face recognition
        self._owner_streak = 0
        self._input_wake_at = None             # keyboard/mouse used while away: who is it?
        self._enroll = None                    # "Teach my face" in progress
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
        self._locked = False
        self._break_reminded = False
        # water reminder + forced break
        # timers count time AT THE DESK: they pause while you are away (see _count_desk_time)
        self.water_elapsed = 0.0
        self.work_elapsed = 0.0
        self.sit_elapsed = 0.0
        self._water_asking = False
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
        self._sync_calls()
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
        if self._calls:
            self._calls.stop()
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
        if new["camera_mode"] != old.get("camera_mode") or new["check_every_minutes"] != old.get("check_every_minutes"):
            self._check_until = None
            self._next_check_at = 0.0  # look right away, then on the new schedule
        if self.sensor is not None:
            self.sensor.owner_faces = new["owner_faces"]
        if any(new.get(k) != old.get(k) for k in NETWORK_KEYS):
            log.info("Network settings changed, restarting the link")
            self._stop_network()
            self._start_network()
        self._sync_calls()
        if new["mouse_mode"] != MOUSE_EYES:
            self._eye_close_wanted = True  # closed by the camera thread, which may be using it
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
    def interval_mode(self):
        """The webcam only opens for a short look every few minutes (presence by webcam only)."""
        return self.cfg["camera_mode"] == "interval" and self.cfg["presence_source"] in ("camera", "both")

    @property
    def camera_wanted(self):
        if not self.uses_camera or self.paused or self.camera_lent_to is not None:
            return False
        if self.camera_hold or self._enroll is not None:
            return True
        if self.interval_mode:
            return self._check_until is not None
        return self.cfg["presence_source"] in ("camera", "both") or self.cfg["mouse_mode"] != MOUSE_OFF

    @property
    def owner_lock(self):
        """Only the owner's face may turn the PC back on (when it can be checked at all)."""
        return (self.cfg["owner_only"] and bool(self.cfg["owner_faces"]) and self._identity_ok is not False
                and self.uses_camera and self.camera_lent_to is None and not self._camera_failed)

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
            self._check_resume(time.time())
            if self._eye_close_wanted:
                self._eye_close_wanted = False
                if self.cfg["mouse_mode"] != MOUSE_EYES:
                    self._close_eye()
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
                        self.sensor = FaceSensor(self.cfg["camera_index"], self.cfg["owner_faces"])
                        self._camera_failed = False
                        self._identity_ok = self.sensor.supports_identity
                        self._last_face = time.monotonic() + (CAMERA_WARMUP if self.interval_mode else 0.0)
                        self._set_status(self.state)
                    except Exception as e:
                        # usually another app (a video call) is holding the webcam
                        busy = self._camshare and any(
                            camshare.in_use(v) for k, v in camshare.snapshot().items()
                            if not camshare.CameraShare._is_own(k))
                        log.warning("Camera unavailable (%s)%s", e, " - in use by another app" if busy else "")
                        self._set_status("camera_busy" if busy else "camera_error")
                        self._camera_failed = True
                        camera_retry_at = t0 + 5
                if self.sensor is not None:
                    self.sensor.check_owner = self._enroll is not None or (self.state == AWAY and self.owner_lock)
                    obs = self.sensor.read()
                    if obs is None:
                        errors += 1
                        if errors > 20:
                            errors = 0
                            self._reopen = True
                    else:
                        errors = 0
            try:
                if self._enroll is not None:
                    self._enroll_step(obs, time.monotonic())
                self._process(obs, time.monotonic())
            except Exception:
                log.exception("process failed")
            if self.sensor is not None:
                fps = self.cfg["camera_fps"]
                if self.cfg["mouse_mode"] == MOUSE_EYES and not self.interval_mode:
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

    # ------------------------------------------------------------ phone calls
    def _sync_calls(self):
        want = self.cfg["pause_on_call"]
        if want and self._calls is None:
            self._calls = CallWatcher(self._on_call_start, self._on_call_end)
            self._calls.start()
        elif not want and self._calls is not None:
            self._calls.stop()
            self._calls = None

    def _on_call_start(self):
        self.media.pause("call")
        self.popup(t("call.title"), t("call.body"), seconds=5)
        if self.link:
            self.link.send({"type": "call", "active": True})

    def _on_call_end(self):
        if self.state == AWAY:
            self.media.move("call", "away")  # played again when you are back
        else:
            self.media.resume("call")
        if self.link:
            self.link.send({"type": "call", "active": False})

    # ------------------------------------------------------------ webcam sharing
    def _camera_share_step(self, now):
        if now - self._share_checked_at < 1.0:
            return
        self._share_checked_at = now
        if self._camshare is None:
            try:
                self._camshare = CameraShare()
            except Exception:
                log.exception("Webcam sharing unavailable")
                self._camshare = False
            return
        if self._camshare is False:
            return
        if self._lend is not None:
            if self._camshare.finished(self._lend):
                name = self._lend.name
                log.info("%s is done with the webcam, taking it back", name)
                self._end_lend()
                self.popup(t("cam.back.title"), t("cam.back.body", app=name))
            return
        requests = self._camshare.new_requests()
        if self.sensor is None or self.cfg["camera_share"] == "never" or self._asking:
            return
        for name, exe, key, pid in requests:
            ident = pid or key
            if ident in self._share_declined:
                continue
            log.info("%s wants the webcam", name)
            if self.cfg["camera_share"] == "always":
                self._lend_camera(name, exe, key, pid)
            else:
                self._asking = True
                self.ui.ask(t("cam.ask.title", app=name), t("cam.ask.body", app=name),
                            t("cam.ask.yes"), t("cam.ask.no"),
                            lambda yes, a=(name, exe, key, pid): self._answer_share(yes, *a),
                            winapi.pick_monitor(self.monitors, self.cfg["notification_monitor"]))
            break

    def _answer_share(self, yes, name, exe, key, pid):
        self._asking = False
        if yes:
            self._lend_camera(name, exe, key, pid)
        else:
            self._share_declined.add(pid or key)

    def _lend_camera(self, name, exe=None, key=None, pid=None):
        log.info("Handing the webcam to %s", name)
        self._lend = Lend(name, exe, key, pid)
        self.camera_lent_to = (key, name)
        self._reopen = True
        self._set_status("camera_lent")
        if exe or key:
            self.popup(t("cam.lent.title", app=name), t("cam.lent.body"), seconds=10)

    def _end_lend(self):
        self._lend = None
        self.camera_lent_to = None
        self._last_face = time.monotonic()
        if self._camshare:
            self._camshare.new_requests()  # our own reopening is not a request
        self._set_status(self.state)

    def release_camera(self):
        """The "release webcam" button: any app can use it until you take it back."""
        self._lend_camera(t("cam.manual"))
        self.popup(t("cam.released.title"), t("cam.released.body"), seconds=8)

    def take_camera_back(self):
        if self._lend is not None:
            self._end_lend()

    # ------------------------------------------------------------ eye control on / off
    def set_eye_follow(self, on):
        old = copy.deepcopy(self.cfg.data)
        if on:
            self.cfg.set("mouse_mode", MOUSE_EYES)
        else:
            self.cfg.set("mouse_mode", MOUSE_MONITOR if len(self.cfg["calibration"]) >= 2 else MOUSE_OFF)
        self.apply_settings(old)
        if on and not self.eye_mapper.ok:
            self.start_eye_calibration()
        else:
            self.popup(t("eyes.on") if on else t("eyes.off"), t("eyes.hotkey"), seconds=3)
        self._set_status(self.status)

    # ------------------------------------------------------------ presence
    def _process(self, obs, now):
        """One tick. obs is the webcam observation, or None when the webcam is not in use."""
        self._interval_step(now)
        if obs is not None:
            # with "body", turning your head away (no face) still counts: the person detector sees you
            seen = obs.person if self.cfg["presence_by"] == "body" else obs.face
            if seen:
                self._last_face = now
                self._face_streak += 1
            else:
                self._face_streak = 0
            if obs.face:
                self._last_obs, self._last_obs_at = obs, now
            self._owner_streak = self._owner_streak + 1 if obs.owner else 0
            if seen and self.state == PRESENT and not self.break_active and self._check_until is not None:
                self._end_check(now)  # you are here: the webcam goes off until the next look
        # interval mode, between two looks: the last look saw you, so you are still here
        between = (self.interval_mode and obs is None and self._check_until is None
                   and self.camera_lent_to is None)
        if between and self.state == PRESENT:
            self._last_face = now
        phone = self.phone_near
        if phone:
            self._last_face = now
        have_source = obs is not None or phone is not None or between

        eyes = (obs is not None and self.cfg["mouse_mode"] == MOUSE_EYES and not self.interval_mode
                and self.state == PRESENT and not self.break_active)
        if eyes:
            self._eye_features(now)
        if self.calibrating:
            self._last_tick = now
            return

        idle = winapi.idle_seconds()
        if self.state == PRESENT:
            if have_source:
                face_gap = now - self._last_face
                left = max(self.cfg["away_seconds"] - face_gap, self.cfg["idle_guard_seconds"] - idle)
                noticed = face_gap >= 2  # a single missed frame is not "leaving"
            else:  # no webcam and no phone: only keyboard / mouse inactivity is left
                left = self.cfg["idle_fallback_minutes"] * 60 - idle
                noticed = True
            if left <= 0:
                self.go_away(local=True)
            else:
                self._countdown_step(left if noticed and not self.break_active else None)
            if left > 0 and not self.break_active:
                self._count_desk_time(now)
                if obs is not None:
                    self._eye_hotkey()
                if eyes:
                    self._eye_step(now)
                elif obs is not None and not self.interval_mode:
                    self._gaze_step(obs, now)
                self._break_step(now)
                self._water_step(now)
                self._work_step(now)
        else:
            back_input = self.cfg["wake_on_input"] and idle < 1.0
            back_phone = phone is True and self._phone_at_away is not True
            if self.owner_lock:
                back_seen = self._owner_streak >= self.cfg["back_frames"]
                if back_input:
                    back_input = False
                    self._owner_input_check(now)
                self._owner_input_timeout(now)
            else:
                back_seen = self._face_streak >= self.cfg["back_frames"]
            if back_seen or back_input or back_phone:
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

    # ------------------------------------------------------------ interval mode
    def _interval_step(self, now):
        """Opens the webcam for a look when one is due; it stays off in between."""
        if not self.interval_mode:
            self._check_until = None
            return
        if self._check_until is not None:
            if now >= self._check_until:
                self._end_check(now)
            return
        present = self.state == PRESENT
        # a forced break needs to see that you left, so the webcam stays on while you sit there
        if self.calibrating or (now < self._next_check_at and not (present and self.break_active)):
            return
        if present and not self.break_active and winapi.idle_seconds() < self.cfg["idle_guard_seconds"]:
            self._next_check_at = now + self.cfg["check_every_minutes"] * 60  # you are typing: clearly here
            return
        self._start_check(now, None if present else AWAY_LOOK_SECONDS)

    def _start_check(self, now, seconds):
        """seconds=None: look until you are seen (or until you count as away)."""
        if self._check_until is None:
            log.debug("Webcam look started")
        self._check_until = math.inf if seconds is None else max(self._check_until or 0.0, now + seconds)

    def _end_check(self, now):
        self._check_until = None
        every = self.cfg["check_every_minutes"] * 60 if self.state == PRESENT else self.cfg["away_check_seconds"]
        self._next_check_at = now + every

    def next_check_seconds(self):
        """Seconds to the next look in interval mode, None while looking or not in interval mode."""
        if not self.interval_mode or self._check_until is not None:
            return None
        return max(0.0, self._next_check_at - time.monotonic())

    # ------------------------------------------------------------ owner only
    def _owner_input_check(self, now):
        """Keyboard/mouse while away: Windows wakes the screens, the webcam checks who it is."""
        if self._input_wake_at is None:
            log.info("Input while away: checking for the owner")
            self._input_wake_at = now
            self._start_check(now, AWAY_LOOK_SECONDS + CAMERA_WARMUP)

    def _owner_input_timeout(self, now):
        if self._input_wake_at is None or now - self._input_wake_at < AWAY_LOOK_SECONDS + CAMERA_WARMUP:
            return
        self._input_wake_at = None
        log.info("Not the owner: the screens stay off")
        if self.cfg["turn_off_monitors"]:
            winapi.monitors_off()

    def teach_owner(self, done=None):
        """Collects the owner's face for a few seconds; done(count) is called when finished."""
        if not self.uses_camera:
            self.popup(t("owner.title"), t("cal.no_camera"))
            return
        if self._enroll is None:
            log.info("Learning the owner's face")
            self._enroll = {"until": time.monotonic() + ENROLL_SECONDS + CAMERA_WARMUP, "feats": [], "done": done}

    def forget_owner(self):
        self.cfg.set("owner_faces", [])
        if self.sensor is not None:
            self.sensor.owner_faces = []
        log.info("Owner face removed")

    def _enroll_step(self, obs, now):
        en = self._enroll
        if self.sensor is not None and not self.sensor.supports_identity:
            self._enroll = None
            self.popup(t("owner.title"), t("owner.unavailable"))
            if en["done"]:
                en["done"](0)
            return
        if obs is not None and obs.face and self.sensor.last_feature is not None and obs.faces == 1:
            en["feats"].append([round(float(v), 5) for v in self.sensor.last_feature])
        if now < en["until"]:
            return
        self._enroll = None
        feats = en["feats"]
        if len(feats) < 5:
            self.popup(t("owner.title"), t("owner.failed"))
        else:
            step = max(1, len(feats) // 12)
            feats = feats[::step][:12]
            self.cfg.set("owner_faces", feats)
            if self.sensor is not None:
                self.sensor.owner_faces = feats
            log.info("Owner face saved (%d samples)", len(feats))
            self.popup(t("owner.title"), t("owner.done"))
        if en["done"]:
            en["done"](len(feats) if len(feats) >= 5 else 0)

    # ------------------------------------------------------------ presence actions
    def _countdown_step(self, left):
        """Countdown on screen while the screens fade to black; None hides it."""
        window = self.cfg["countdown_seconds"]
        if left is None or not self.cfg["away_countdown"] or left > window:
            if self._countdown_shown:
                self._countdown_shown = False
                self.ui.away_countdown_hide()
            return
        if not self._countdown_shown:
            self._countdown_shown = True
            self._countdown_total = max(1.0, left)
            log.info("Away countdown started (%.0f s)", left)
        darkness = 1.0 - left / self._countdown_total
        self.ui.away_countdown(left, darkness, self.monitors)

    def go_away(self, local):
        with self._lock:
            if self.state == AWAY:
                return
            log.info("AWAY (local=%s)", local)
            self.state = AWAY
            self._away_since = time.monotonic()
            self._check_until = None
            self._next_check_at = self._away_since + self.cfg["away_check_seconds"]
            self._input_wake_at = None
            self._phone_at_away = self.phone_near
            self._locked = False
            if self.cfg["pause_media"]:
                self.media.pause()
            if self.cfg["turn_off_monitors"]:
                time.sleep(0.3)
                winapi.monitors_off()
            if self._countdown_shown:  # the screens are dark now: remove the countdown
                self._countdown_shown = False
                self.ui.away_countdown_hide()
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
            self._last_face = now
            self._check_until = None
            self._next_check_at = now + self.cfg["check_every_minutes"] * 60
            self._input_wake_at = None
            # a long absence counts as a break: the break and stand-up timers start over.
            # Shorter absences only pause them (they did not count while you were away).
            if now - self._away_since >= self.cfg["timer_reset_away_minutes"] * 60:
                self.work_elapsed = self.sit_elapsed = 0.0
                self._break_reminded = False
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

    # ------------------------------------------------------------ sleep / hibernate
    def _check_resume(self, wall_now):
        """The loop runs every half second; a big jump of the wall clock means the PC was asleep."""
        gap = wall_now - self._last_wall
        self._last_wall = wall_now
        if gap >= SLEEP_GAP_SECONDS:
            self.on_resume(gap)

    def on_resume(self, gap):
        """Back from sleep or hibernation: every timer starts over."""
        log.info("Resumed after %d s of sleep: timers restart", gap)
        if self.break_active:
            self.end_break(skipped=True)
        self.water_elapsed = self.work_elapsed = self.sit_elapsed = 0.0
        self._break_reminded = False
        self._water_asking = False
        self._last_face = self._last_tick = time.monotonic()
        self._check_until = None
        self._next_check_at = 0.0
        self._reopen = True  # the webcam handle does not survive sleep
        self._set_status(self.status)

    # ------------------------------------------------------------ water + forced break
    def _count_desk_time(self, now):
        dt = max(0.0, min(2.0, now - self._last_tick))
        self.water_elapsed += dt
        self.work_elapsed += dt
        self.sit_elapsed += dt

    def _water_step(self, now):
        mins = self.cfg["water_reminder_minutes"]
        if mins > 0 and not self._water_asking and self.water_elapsed >= mins * 60:
            self._water_asking = True
            winapi.beep()
            self.ui.ask(t("water.title"), t("water.body"), t("water.drank"), t("water.later"),
                        self._water_answer, winapi.pick_monitor(self.monitors, self.cfg["notification_monitor"]),
                        timeout=90)

    def _water_answer(self, answer):
        self._water_asking = False
        if answer is False:  # "later": ask again in 10 minutes
            self.water_elapsed = max(0.0, self.cfg["water_reminder_minutes"] * 60 - 10 * 60)
        else:  # drank, or no answer: the next reminder comes after the usual interval
            self.water_elapsed = 0.0
        self._set_status(self.status)

    def drank_water(self):
        """The "I drank water" button: restart the water timer."""
        self.water_elapsed = 0.0
        log.info("Water timer restarted")
        self._set_status(self.status)

    def _work_step(self, now):
        fb = self.cfg["forced_break"]
        if fb["enabled"] and self.work_elapsed >= fb["work_minutes"] * 60:
            self.start_break()

    def next_break_minutes(self):
        fb = self.cfg["forced_break"]
        if not fb["enabled"] or not self.uses_camera:
            return None
        left = fb["work_minutes"] * 60 - self.work_elapsed
        return max(0, int(left // 60))

    def timers(self):
        """Seconds left / elapsed for the widget and the settings window (None = turned off)."""
        fb = self.cfg["forced_break"]
        water = self.cfg["water_reminder_minutes"]
        return {
            "water_left": max(0.0, water * 60 - self.water_elapsed) if water > 0 else None,
            "break_left": max(0.0, fb["work_minutes"] * 60 - self.work_elapsed) if fb["enabled"] else None,
            "sitting": self.sit_elapsed,
            "break_active": self.break_active,
            "break_remaining": self._break_left if self.break_active else None,
        }

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
            self.work_elapsed = self.sit_elapsed = 0.0
            self._break_reminded = False
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
        if mins > 0 and not self._break_reminded and self.sit_elapsed >= mins * 60:
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
            self.set_eye_follow(self.cfg["mouse_mode"] != MOUSE_EYES)
        self._hotkey_down = down

    def _eye_step(self, now):
        if not self.eye_mapper.ok or self._eye_feat is None:
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
        elif kind == "call":  # a call on the other machine pauses this one's media too
            if msg.get("active"):
                self.media.pause("call")
            else:
                self.media.resume("call")
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
