"""Notices when another app wants the webcam, so DeskPresence can hand it over.

Windows records every app's webcam use under
HKCU\\...\\CapabilityAccessManager\\ConsentStore\\webcam (LastUsedTimeStart / LastUsedTimeStop).
A new start time from another app means it just opened, or tried to open, the camera.
"""
import logging
import sys
import winreg

log = logging.getLogger(__name__)

BASE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"


def _values(key):
    vals, i = {}, 0
    while True:
        try:
            name, value, _ = winreg.EnumValue(key, i)
        except OSError:
            return vals
        vals[name] = value
        i += 1


def _subkeys(key):
    i = 0
    while True:
        try:
            yield winreg.EnumKey(key, i)
        except OSError:
            return
        i += 1


def snapshot():
    """{app key: (start, stop)} for every app Windows has seen using the webcam."""
    out = {}

    def walk(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                vals = _values(k)
                if "LastUsedTimeStart" in vals:
                    out[path[len(BASE) + 1:]] = (int(vals.get("LastUsedTimeStart") or 0),
                                                 int(vals.get("LastUsedTimeStop") or 0))
                for sub in list(_subkeys(k)):
                    walk(path + "\\" + sub)
        except OSError:
            pass

    walk(BASE)
    return out


def app_name(key):
    """'NonPackaged\\C:#Program Files#Zoom#bin#Zoom.exe' -> 'Zoom'; 'MSTeams_8wekyb3d8bbwe' -> 'MSTeams'."""
    last = key.split("\\")[-1]
    if "#" in last:
        name = last.split("#")[-1]
        return name[:-4] if name.lower().endswith(".exe") else name
    name = last.split("_")[0]
    return name.split(".")[-1] if name.startswith("Microsoft.") else name


def in_use(times):
    start, stop = times
    return start > 0 and (stop == 0 or start > stop)


class CameraShare:
    def __init__(self):
        self._last = snapshot()

    @staticmethod
    def _is_own(key):
        path = key.split("\\")[-1].replace("#", "\\").lower()
        return path.endswith("\\deskpresence.exe") or path == sys.executable.lower()

    def new_requests(self):
        """Apps (other than us) that started using the webcam since the last call: [(key, name)]."""
        now = snapshot()
        found = []
        for key, times in now.items():
            if self._is_own(key):
                continue
            before = self._last.get(key, (0, 0))
            if times[0] > before[0]:
                found.append((key, app_name(key)))
        self._last = now
        return found

    def still_using(self, key):
        times = snapshot().get(key)
        return bool(times) and in_use(times)
