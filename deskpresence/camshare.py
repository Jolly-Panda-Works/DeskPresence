"""Notices when another app wants the webcam, so DeskPresence can hand it over.

Most webcams can only be used by one app at a time, and Windows does not tell the app holding it
when another app tries and fails. So two signals are combined:

1. A camera app starts. Windows lists every app that has ever used the webcam under
   HKCU\\...\\CapabilityAccessManager\\ConsentStore\\webcam; together with a list of well-known
   video apps, a newly started process from that list counts as a request.
2. Another app actually starts using the webcam (cameras that can be shared): a new
   LastUsedTimeStart in that same registry list.

After handing the webcam over, it is taken back when that app has finished with it (its
LastUsedTimeStop), when the app exits, or when it did not use the camera within 3 minutes.
"""
import ctypes
import logging
import sys
import time
import winreg
from ctypes import wintypes

log = logging.getLogger(__name__)

BASE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"

# exe name -> display name; apps that usually open the camera when they start or join a call
KNOWN_CAMERA_APPS = {
    "zoom.exe": "Zoom",
    "ms-teams.exe": "Microsoft Teams",
    "teams.exe": "Microsoft Teams",
    "windowscamera.exe": "Camera",
    "obs64.exe": "OBS Studio",
    "skype.exe": "Skype",
    "webex.exe": "Webex",
    "ciscocollabhost.exe": "Webex",
    "googlemeet.exe": "Google Meet",
    "manycam.exe": "ManyCam",
}
# packaged apps in the registry list -> their exe
PACKAGED_EXE = {
    "microsoft.windowscamera": "windowscamera.exe",
    "msteams": "ms-teams.exe",
    "microsoft.skypeapp": "skype.exe",
}
# starting these does not mean the camera is wanted (they are always open)
NEVER_ASK = {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe", "explorer.exe",
             "deskpresence.exe", "python.exe", "pythonw.exe", "discord.exe", "slack.exe", "telegram.exe",
             "whatsapp.exe", "amdprivacyview.exe"}


# ---------------------------------------------------------------- registry
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
    """{app key: (start, stop)} (FILETIME) for every app Windows has seen using the webcam."""
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


def exe_of_key(key):
    """Registry key -> lower-case exe name ('zoom.exe'), or None."""
    last = key.split("\\")[-1]
    if "#" in last:
        return last.split("#")[-1].lower()
    return PACKAGED_EXE.get(last.split("_")[0].lower())


def in_use(times):
    start, stop = times
    return start > 0 and (stop == 0 or start > stop)


def filetime_now():
    return int((time.time() + 11644473600) * 10_000_000)


# ---------------------------------------------------------------- processes
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


def processes():
    """{pid: lower-case exe name} of running processes."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    out = {}
    if not snap or snap == wintypes.HANDLE(-1).value:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out[entry.th32ProcessID] = entry.szExeFile.lower()
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


# ---------------------------------------------------------------- watcher
class Lend:
    """The webcam is lent to another app (or released by hand when exe is None)."""

    def __init__(self, name, exe=None, key=None, pid=None):
        self.name, self.exe, self.key, self.pid = name, exe, key, pid
        self.since = time.monotonic()
        self.since_ft = filetime_now()
        self.used = False
        self.free_since = None

    @property
    def manual(self):
        return self.exe is None and self.key is None


class CameraShare:
    def __init__(self):
        self._last = snapshot()
        self._pids = processes()

    @staticmethod
    def _is_own(key):
        path = key.split("\\")[-1].replace("#", "\\").lower()
        return path.endswith("\\deskpresence.exe") or path == sys.executable.lower()

    def camera_apps(self):
        """exe -> display name: the well-known list plus every app Windows saw using the webcam."""
        apps = dict(KNOWN_CAMERA_APPS)
        for key in self._last:
            exe = exe_of_key(key)
            if exe and exe not in NEVER_ASK and not self._is_own(key):
                apps.setdefault(exe, app_name(key))
        return apps

    def new_requests(self):
        """[(name, exe, registry key or None, pid or None)] that want the webcam since the last call."""
        found = []
        now = snapshot()
        for key, times in now.items():
            if self._is_own(key) or exe_of_key(key) in NEVER_ASK:
                continue
            if times[0] > self._last.get(key, (0, 0))[0]:
                found.append((app_name(key), exe_of_key(key), key, None))
        self._last = now

        procs = processes()
        apps = self.camera_apps()
        for pid, exe in procs.items():
            if pid not in self._pids and exe in apps and not any(f[1] == exe for f in found):
                found.append((apps[exe], exe, None, pid))
        self._pids = procs
        return found

    def finished(self, lend, grace=3.0):
        """True when the app the webcam was lent to is done with it."""
        if lend.manual:
            return False
        now = time.monotonic()
        snap = snapshot()
        times = None
        if lend.key and lend.key in snap:
            times = snap[lend.key]
        elif lend.exe:
            times = next((v for k, v in snap.items() if exe_of_key(k) == lend.exe), None)
        busy = False
        if times and times[0] >= lend.since_ft - 50_000_000:  # it (re)started using the camera after we lent it
            lend.used = True
            busy = in_use(times)
        if lend.pid is not None and lend.pid not in processes():
            return True  # the app exited
        if not lend.used:
            return now - lend.since > 180  # it never picked the camera up
        if busy:
            lend.free_since = None
            return False
        if lend.free_since is None:
            lend.free_since = now
        return now - lend.free_since >= grace
