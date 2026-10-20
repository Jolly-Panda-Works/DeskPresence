import ctypes
import logging
import sys
from logging.handlers import RotatingFileHandler

from . import APP_NAME, APP_VERSION, winapi
from .config import LOG_PATH, Config
from .i18n import set_language, t


def _setup_logging():
    handlers = [RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def self_test():
    """Used by CI on the built app: every module and model loads. Exit code 0 = fine."""
    import os
    import tempfile
    import traceback
    try:
        import cv2  # noqa: F401
        import customtkinter  # noqa: F401
        from . import camshare, controller, eyetrack, media, notifications, phone, settings_ui, tray  # noqa: F401
        from .vision import _model_path
        assert _model_path(), "YuNet model missing"
        assert eyetrack.available(), "eye-tracking model or mediapipe missing"
        eyetrack.EyeTracker().close()
        assert media.HAVE_SMTC and phone.HAVE_BT and notifications.HAVE_LISTENER, "WinRT modules missing"
        return 0
    except Exception:
        with open(os.path.join(tempfile.gettempdir(), "deskpresence-selftest.txt"), "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        if sys.stderr is not None:
            traceback.print_exc()
        return 1


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    winapi.set_dpi_aware()
    cfg = Config()
    set_language(cfg["language"])
    if not winapi.acquire_single_instance(APP_NAME):
        ctypes.windll.user32.MessageBoxW(None, t("app.running"), APP_NAME, 0x40)
        return

    _setup_logging()
    log = logging.getLogger(APP_NAME)
    log.info("Starting %s %s as %s", APP_NAME, APP_VERSION, cfg["role"])

    # imported late so logging is ready before heavy modules load
    from .controller import Controller
    from .tray import Tray
    from .ui import UI

    ui = UI()
    ctrl = Controller(cfg, ui)
    tray = Tray(ctrl, cfg, ui)
    ctrl.on_state = tray.refresh
    ctrl.start()
    tray.start()

    if cfg["role"] == "desktop" and len(cfg["calibration"]) < 2 and len(winapi.list_monitors()) > 1:
        ctrl.popup(t("welcome.title"), t("welcome.body"))

    try:
        ui.run()
    finally:
        ctrl.stop()
        tray.stop()
        log.info("Exited")


if __name__ == "__main__":
    main()
