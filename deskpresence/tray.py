import logging
import os
import sys
import threading
import winreg

import pystray
from PIL import Image, ImageDraw

from . import APP_NAME, winapi
from .config import APP_DIR, CONFIG_PATH

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
COLORS = {"present": "#2ecc71", "away": "#f39c12", "paused": "#7f8c8d", "error": "#e74c3c"}


def _icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    d.ellipse((22, 14, 42, 34), fill="white")        # head
    d.pieslice((14, 34, 50, 70), 180, 360, fill="white")  # shoulders
    return img


def _launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


class Tray:
    def __init__(self, ctrl, cfg, ui):
        self.ctrl, self.cfg, self.ui = ctrl, cfg, ui
        I, M = pystray.MenuItem, pystray.Menu
        menu = M(
            I(lambda _: self._status_text(), None, enabled=False),
            M.SEPARATOR,
            I("توقف موقت", self._toggle_pause, checked=lambda _: ctrl.paused),
            I("موس دنبال نگاه من بیاید", self._toggle_gaze, checked=lambda _: cfg["gaze_follow"],
              visible=lambda _: ctrl.uses_camera),
            I("کالیبره کردن نگاه…", lambda: ctrl.start_calibration(), visible=lambda _: ctrl.uses_camera),
            I("تست: خاموش کردن مانیتورها", lambda: winapi.monitors_off()),
            M.SEPARATOR,
            I("اجرا همراه ویندوز", self._toggle_autostart, checked=lambda _: autostart_enabled()),
            I("ویرایش تنظیمات", lambda: os.startfile(CONFIG_PATH)),
            I("اعمال تنظیمات ذخیره‌شده", self._reload),
            I("پوشه برنامه و لاگ", lambda: os.startfile(APP_DIR)),
            M.SEPARATOR,
            I("خروج", self._quit),
        )
        self.icon = pystray.Icon(APP_NAME, _icon(COLORS["present"]), APP_NAME, menu)

    def _status_text(self):
        role = "کامپیوتر" if self.ctrl.role == "desktop" else "لپ‌تاپ"
        text = f"{role}: {self.ctrl.status}"
        if self.cfg["network_enabled"]:
            text += "  •  اتصال: " + ("برقرار" if self.ctrl.peer_connected else "قطع")
        return text

    def refresh(self):
        if self.ctrl.paused:
            key = "paused"
        elif self.ctrl.status.startswith("خطا"):
            key = "error"
        else:
            key = self.ctrl.state
        try:
            self.icon.icon = _icon(COLORS.get(key, COLORS["present"]))
            self.icon.title = f"{APP_NAME} - {self.ctrl.status}"
            self.icon.update_menu()
        except Exception:
            pass

    def start(self):
        threading.Thread(target=self.icon.run, daemon=True, name="tray").start()

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass

    def _toggle_pause(self):
        self.ctrl.set_paused(not self.ctrl.paused)

    def _toggle_gaze(self):
        self.cfg.set("gaze_follow", not self.cfg["gaze_follow"])

    def _toggle_autostart(self):
        set_autostart(not autostart_enabled())

    def _reload(self):
        self.ctrl.reload()
        self.ctrl.popup("تنظیمات اعمال شد",
                        "تغییر role یا تنظیمات شبکه بعد از بستن و باز کردن دوباره برنامه اعمال می‌شود.")

    def _quit(self):
        self.ctrl.stop()
        self.stop()
        self.ui.quit()
