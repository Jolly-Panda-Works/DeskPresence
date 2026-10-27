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
    _catch_crashes()


_crash_file = None


def _catch_crashes():
    """Every unhandled error ends up in log.txt; hard crashes of native code in crash.txt."""
    global _crash_file
    import faulthandler
    import os
    import threading
    log = logging.getLogger("crash")

    def on_exception(exc_type, exc, tb):
        log.critical("Unhandled error", exc_info=(exc_type, exc, tb))

    def on_thread_exception(args):
        log.critical("Unhandled error in thread %s", args.thread.name if args.thread else "?",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = on_exception
    threading.excepthook = on_thread_exception
    try:
        _crash_file = open(os.path.join(os.path.dirname(LOG_PATH), "crash.txt"), "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        log.exception("faulthandler unavailable")


def self_test():
    """Used by CI on the built app: every module and model loads. Exit code 0 = fine."""
    import os
    import tempfile
    import traceback
    try:
        import cv2  # noqa: F401
        import customtkinter  # noqa: F401
        from . import (calls, camshare, controller, eyetrack, firewall, media, notifications,  # noqa: F401
                       phone, settings_ui, tray, widget)
        calls.phone_link_audio_active()
        import pycaw.pycaw  # noqa: F401
        import cv2 as _cv2
        from .vision import IDENTITY_MODEL, PERSON_MODEL, PersonDetector, _model_path
        assert _model_path(), "YuNet model missing"
        assert _model_path(PERSON_MODEL), "person detector model missing"
        PersonDetector(_model_path(PERSON_MODEL)).close()
        assert _model_path(IDENTITY_MODEL), "face recognition model missing"
        _cv2.FaceRecognizerSF.create(_model_path(IDENTITY_MODEL), "")
        from . import exercise, exercise_ui  # noqa: F401
        assert exercise.available(), "body-tracking model missing"
        exercise.PoseTracker().close()
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
    from .widget import Widget

    ui = UI()
    ctrl = Controller(cfg, ui)
    tray = Tray(ctrl, cfg, ui)
    tray.widget = Widget(ui, ctrl, cfg, tray.open_settings)
    ctrl.on_state = tray.refresh
    ctrl.start()
    tray.start()

    if cfg["widget"]["enabled"] and ctrl.uses_camera:
        ui.call(tray.widget.show)
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
