import copy
import json
import logging
import os
import secrets
import threading

from . import APP_NAME

log = logging.getLogger(__name__)

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "log.txt")

DEFAULTS = {
    # "desktop" = the PC with the webcam; "laptop" = the companion device
    "role": "desktop",
    "language": "auto",          # "auto" (Windows language), "fa" or "en"

    # --- presence detection ---
    # what tells DeskPresence you are at the desk:
    #   "camera" = webcam, "phone" = your phone over Bluetooth, "both" = away only when neither sees you
    "presence_source": "camera",
    "phone": {
        "device_id": "",       # a paired Bluetooth device, chosen in the settings window
        "name": "",
        "check_seconds": 8,    # how often the phone is probed
        "away_checks": 2,      # failed probes in a row before it counts as gone
    },
    # when another app wants the webcam: "ask", "always" (hand it over), "never"
    "camera_share": "ask",
    # with no camera or phone available, keyboard/mouse inactivity this long means away
    "idle_fallback_minutes": 5,
    "camera_index": 0,
    "camera_fps": 8,
    "away_seconds": 10,          # no face for this long -> away
    "back_frames": 3,            # consecutive frames with a face -> back
    "idle_guard_seconds": 20,    # never go "away" if keyboard/mouse was used this recently
    "wake_on_input": True,       # touching the keyboard/mouse while away counts as "back"
    # before going away: a countdown on every monitor while the screens fade to black
    "away_countdown": True,
    "countdown_seconds": 15,     # the countdown shows during the last N seconds
    "laptop_use_camera": False,  # laptop role: also run its own webcam detection

    # --- actions ---
    "pause_media": True,
    "pause_on_call": True,            # pause media during phone calls (Windows Phone Link)
    # per-app media handling, chosen from the tray menu: app id -> "auto" | "music" | "video" | "ignore"
    # music = pause + resume, video = pause only, ignore = leave alone
    "media_apps": {},
    "turn_off_monitors": True,
    "lock_after_away_minutes": 0,     # 0 = never lock
    "break_reminder_minutes": 50,     # 0 = off
    "water_reminder_minutes": 60,     # 0 = off
    # timers only count time at the desk; an absence this long resets the break / stand-up timers
    "timer_reset_away_minutes": 10,

    # after work_minutes at the desk, the screens are covered for a break.
    # The break countdown only runs while the camera does NOT see you.
    "forced_break": {
        "enabled": True,
        "work_minutes": 90,
        "break_minutes": 10,
        "allow_skip": True,           # emergency skip button (needs a double click)
    },

    # --- mouse ---
    # "off", "monitor" (cursor jumps to the monitor you face) or "eyes" (cursor follows your eyes)
    "mouse_mode": "monitor",
    "gaze_stable_seconds": 0.6,
    "gaze_mouse_quiet_seconds": 0.8,  # don't steal the cursor right after you moved it
    "calibration": {},                # target name -> [yaw, pitch]
    "eye_calibration": {},            # regression weights from the eye calibration
    "eye_deadzone_px": 90,            # ignore gaze changes smaller than this
    "eye_pause_after_mouse_seconds": 1.5,

    # --- Mouse Without Borders (PowerToys) integration ---
    "mwb": {
        "enabled": False,
        "desktop_hotkey": 1,   # Ctrl+Alt+F1
        "laptop_hotkey": 2,    # Ctrl+Alt+F2
    },

    # --- floating timer widget ---
    "widget": {"enabled": True, "x": None, "y": None, "minimized": False,
               "opacity": 90},          # percent; the widget is fully opaque while the mouse is over it

    # --- notifications ---
    "notification_monitor": -1,       # -1 = primary, else index counted left to right from 0
    "notification_seconds": 7,
    "forward_notifications": True,    # laptop role: send laptop toasts to the desktop
    "dismiss_forwarded": False,       # laptop role: remove toast from laptop after forwarding

    # --- network link between desktop and laptop ---
    "network_enabled": False,
    "port": 47821,
    "desktop_host": "192.168.1.10",   # laptop role: IP of the desktop
    "token": "",
}


# dicts that are stored as a whole instead of merged key by key with the defaults
WHOLE_DICTS = ("calibration", "eye_calibration", "media_apps")


def _migrate(user):
    """Older config files -> current keys."""
    if "mouse_mode" not in user and "gaze_follow" in user:
        user["mouse_mode"] = "monitor" if user["gaze_follow"] else "off"
    user.pop("gaze_follow", None)
    return user


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in WHOLE_DICTS:
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        os.makedirs(APP_DIR, exist_ok=True)
        user = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    user = json.load(f)
            except Exception:
                log.exception("Invalid config.json, using defaults")
        with self._lock:
            self.data = _merge(DEFAULTS, _migrate(user))
            if not self.data["token"]:
                self.data["token"] = secrets.token_urlsafe(16)
        self.save()

    def save(self):
        with self._lock:
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_PATH)

    def __getitem__(self, key):
        return self.data[key]

    def set(self, key, value):
        self.data[key] = value
        self.save()
