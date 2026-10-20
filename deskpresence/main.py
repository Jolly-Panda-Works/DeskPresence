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


def main():
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
