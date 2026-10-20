import copy
import logging
import os
import sys
import threading
import winreg

import pystray
from PIL import Image, ImageDraw

from . import APP_NAME, winapi
from .config import APP_DIR, CONFIG_PATH
from .media import AUTO, MODES
from .i18n import LANGUAGES, language, set_language, t

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# status dot on the orange logo
COLORS = {"present": "#4ADE80", "away": "#FBBF24", "break": "#60A5FA", "paused": "#A99B8E", "error": "#F87171"}


def _icon(color):
    """The orange DeskPresence tile with a small status dot."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill="#F97316")
    d.ellipse((92, 46, 164, 118), fill="white")                     # head
    d.rounded_rectangle((60, 128, 196, 230), radius=60, fill="white")  # shoulders
    d.rectangle((60, 200, 196, 248), fill="#F97316")                # cut the bottom flat
    d.ellipse((160, 160, 248, 248), fill="#110D0A")                 # status badge
    d.ellipse((176, 176, 232, 232), fill=color)
    return img.resize((64, 64), Image.LANCZOS)


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
        self._settings = None
        self.widget = None
        I, M = pystray.MenuItem, pystray.Menu

        def tr(key):  # menu text is evaluated each time the menu is rebuilt
            return lambda _: t(key)

        def lang_item(code):
            return I(LANGUAGES[code], lambda: self._set_language(code), radio=True,
                     checked=lambda _: language() == code)

        def mouse_item(mode, key):
            return I(tr(key), lambda: self._set_mouse_mode(mode), radio=True,
                     checked=lambda _: cfg["mouse_mode"] == mode)

        cam = lambda _: ctrl.uses_camera  # noqa: E731
        menu = M(
            I(lambda _: self._status_text(), None, enabled=False),
            M.SEPARATOR,
            I(tr("menu.open_settings"), self.open_settings, default=True),
            I(tr("menu.pause"), self._toggle_pause, checked=lambda _: ctrl.paused),
            I(tr("menu.drank"), lambda: ctrl.drank_water(),
              visible=lambda _: cfg["water_reminder_minutes"] > 0 and ctrl.uses_camera),
            I(tr("menu.eyes"), lambda: ctrl.set_eye_follow(cfg["mouse_mode"] != "eyes"),
              checked=lambda _: cfg["mouse_mode"] == "eyes", visible=cam),
            I(tr("menu.widget"), lambda: self.widget and self.widget.set_visible(not cfg["widget"]["enabled"]),
              checked=lambda _: cfg["widget"]["enabled"]),
            I(lambda _: t("menu.cam_take") if ctrl.camera_lent_to else t("menu.cam_give"),
              lambda: ctrl.take_camera_back() if ctrl.camera_lent_to else ctrl.release_camera(), visible=cam),
            I(tr("menu.mouse"), M(
                mouse_item("off", "set.mouse_off"),
                mouse_item("monitor", "set.mouse_monitor"),
                mouse_item("eyes", "set.mouse_eyes"),
                M.SEPARATOR,
                I(tr("menu.calibrate"), lambda: ctrl.start_calibration()),
                I(tr("set.eyes_cal"), lambda: ctrl.start_eye_calibration()),
            ), visible=cam),
            I(tr("menu.break_now"), lambda: ctrl.start_break(),
              visible=lambda _: ctrl.uses_camera and not ctrl.break_active),
            I(tr("menu.break_end"), lambda: ctrl.end_break(skipped=True),
              visible=lambda _: ctrl.uses_camera and ctrl.break_active),
            I(tr("menu.test_off"), lambda: winapi.monitors_off()),
            M.SEPARATOR,
            I(tr("menu.autostart"), self._toggle_autostart, checked=lambda _: autostart_enabled()),
            I(tr("menu.language"), M(lang_item("fa"), lang_item("en"))),
            I(tr("menu.media"), M(self._media_items), visible=lambda _: cfg["pause_media"]),
            I(tr("menu.settings_file"), lambda: os.startfile(CONFIG_PATH)),
            I(tr("menu.reload"), self._reload),
            I(tr("menu.folder"), lambda: os.startfile(APP_DIR)),
            M.SEPARATOR,
            I(tr("menu.about"), lambda: ui.about()),
            I(tr("menu.quit"), self._quit),
        )
        self.icon = pystray.Icon(APP_NAME, _icon(COLORS["present"]), APP_NAME, menu)

    def _media_items(self):
        """Built each time the submenu opens: every media app Windows has reported so far."""
        I, M = pystray.MenuItem, pystray.Menu
        seen = self.ctrl.media.scan()
        if not seen:
            yield I(t("media.scan_hint"), None, enabled=False)
            return
        overrides = self.cfg["media_apps"]

        def choice(key, mode):
            return I(t("media." + mode), lambda: self._set_media_mode(key, mode), radio=True,
                     checked=lambda _: overrides.get(key, AUTO) == mode)

        for key, (name, kind) in sorted(seen.items(), key=lambda kv: kv[1][0].lower()):
            yield I(f"{name}  ({t('media.kind.' + kind)})", M(*(choice(key, m) for m in MODES)))

    def _set_media_mode(self, key, mode):
        apps = dict(self.cfg["media_apps"])
        if mode == AUTO:
            apps.pop(key, None)
        else:
            apps[key] = mode
        self.cfg.set("media_apps", apps)

    def _status_text(self):
        text = f"{t('role.' + self.ctrl.role)}: {t('status.' + self.ctrl.status)}"
        mins = self.ctrl.next_break_minutes()
        if mins is not None and not self.ctrl.break_active:
            text += "  •  " + t("status.next_break", mins=mins)
        if self.cfg["network_enabled"]:
            state = t("status.link_on") if self.ctrl.peer_connected else t("status.link_off")
            text += "  •  " + t("status.link", state=state)
        return text

    def refresh(self):
        if self.ctrl.paused:
            key = "paused"
        elif self.ctrl.status == "camera_error":
            key = "error"
        elif self.ctrl.status in ("camera_busy", "camera_lent"):
            key = "paused"
        elif self.ctrl.break_active:
            key = "break"
        else:
            key = self.ctrl.state
        try:
            self.icon.icon = _icon(COLORS.get(key, COLORS["present"]))
            self.icon.title = f"{APP_NAME} - {t('status.' + self.ctrl.status)}"
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

    def _set_mouse_mode(self, mode):
        old = copy.deepcopy(self.cfg.data)
        self.cfg.set("mouse_mode", mode)
        self.ctrl.apply_settings(old)

    def open_settings(self):
        self.ui.call(self._open_settings)

    def _open_settings(self):  # runs on the Tk thread
        from .settings_ui import SettingsWindow
        if self._settings is not None and self._settings.alive:
            self._settings.lift()
            return
        self._settings = SettingsWindow(self.ui, self.ctrl, self.cfg, self._after_settings_saved)

    def _after_settings_saved(self):  # Tk thread
        self.refresh()
        if self.widget:
            if self.cfg["widget"]["enabled"] and self.ctrl.uses_camera:
                self.widget.show()
                self.widget.language_changed()
            else:
                self.widget.hide()

    def _toggle_autostart(self):
        set_autostart(not autostart_enabled())

    def _set_language(self, code):
        self.cfg.set("language", code)
        set_language(code)
        self.refresh()
        if self.widget:
            self.ui.call(self.widget.rebuild)

    def _reload(self):
        self.ctrl.reload()
        set_language(self.cfg["language"])
        self.refresh()
        self.ctrl.popup(t("reload.title"), t("reload.body"))

    def _quit(self):
        self.ctrl.stop()
        self.stop()
        self.ui.quit()
