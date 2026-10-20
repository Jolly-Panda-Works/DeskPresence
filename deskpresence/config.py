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
    "camera_index": 0,
    "camera_fps": 8,
    "away_seconds": 10,          # no face for this long -> away
    "back_frames": 3,            # consecutive frames with a face -> back
    "idle_guard_seconds": 20,    # never go "away" if keyboard/mouse was used this recently
    "wake_on_input": True,       # touching the keyboard/mouse while away counts as "back"
    "laptop_use_camera": False,  # laptop role: also run its own webcam detection

    # --- actions ---
    "pause_media": True,
    # per-app media handling, chosen from the tray menu: app id -> "auto" | "music" | "video" | "ignore"
    # music = pause + resume, video = pause only, ignore = leave alone
    "media_apps": {},
    "turn_off_monitors": True,
    "lock_after_away_minutes": 0,     # 0 = never lock
    "break_reminder_minutes": 50,     # 0 = off
    "water_reminder_minutes": 60,     # 0 = off

    # after work_minutes at the desk, the screens are covered for a break.
    # The break countdown only runs while the camera does NOT see you.
    "forced_break": {
        "enabled": True,
        "work_minutes": 90,
        "break_minutes": 10,
        "allow_skip": True,           # emergency skip button (needs a double click)
    },

    # --- gaze -> mouse ---
    "gaze_follow": True,
    "gaze_stable_seconds": 0.6,
    "gaze_mouse_quiet_seconds": 0.8,  # don't steal the cursor right after you moved it
    "calibration": {},                # target name -> [yaw, pitch]

    # --- Mouse Without Borders (PowerToys) integration ---
    "mwb": {
        "enabled": False,
        "desktop_hotkey": 1,   # Ctrl+Alt+F1
        "laptop_hotkey": 2,    # Ctrl+Alt+F2
    },

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


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "calibration":
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
            self.data = _merge(DEFAULTS, user)
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
