import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deskpresence import config, controller, winapi  # noqa: E402
from deskpresence.vision import Observation  # noqa: E402


class FakeConfig(dict):
    def set(self, key, value):
        self[key] = value

    def load(self):
        pass


class FakeUI:
    def __init__(self):
        self.log = []
        self.last_break = None

    def popup(self, title, *_a):
        self.log.append(("popup", title))

    def break_show(self, *_a):
        self.log.append(("show",))

    def break_update(self, left, counting):
        self.last_break = (round(left), counting)

    def break_hide(self):
        self.log.append(("hide",))


class Sim:
    """Drives the controller with a fake clock and fake camera frames."""

    def __init__(self, ctrl, ui, clock):
        self.ctrl, self.ui, self.clock = ctrl, ui, clock

    def run(self, seconds, face):
        end = self.clock["t"] + seconds
        while self.clock["t"] < end:
            self.clock["t"] += 0.5
            self.ctrl._process(Observation(face=face), self.clock["t"])


@pytest.fixture
def sim(monkeypatch):
    monkeypatch.setattr(winapi, "idle_seconds", lambda: 100.0)
    monkeypatch.setattr(winapi, "beep", lambda: None)
    monkeypatch.setattr(winapi, "monitors_off", lambda: None)
    monkeypatch.setattr(winapi, "monitors_on", lambda: None)
    cfg = FakeConfig(copy.deepcopy(config.DEFAULTS))
    cfg.update(pause_media=False, turn_off_monitors=False, gaze_follow=False, break_reminder_minutes=0)
    ui = FakeUI()
    clock = {"t": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["t"])
    ctrl = controller.Controller(cfg, ui)
    return Sim(ctrl, ui, clock)
