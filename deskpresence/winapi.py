"""Thin ctypes wrappers around the Win32 calls we need."""
import ctypes
import logging
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
MONITORINFOF_PRIMARY = 1
MOUSEEVENTF_MOVE = 0x0001
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL, VK_MENU = 0x11, 0x12
VK_F1 = 0x70
VK_LBUTTON, VK_RBUTTON = 0x01, 0x02
VK_MEDIA_PLAY_PAUSE = 0xB3
ES_CONTINUOUS, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000002


def set_dpi_aware():
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


# ---------------------------------------------------------------- monitors
class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


class Monitor:
    def __init__(self, index, rect, work, primary, device):
        self.index, self.rect, self.work, self.primary, self.device = index, rect, work, primary, device

    @property
    def name(self):
        return f"monitor{self.index}"

    @property
    def center(self):
        l, t, r, b = self.rect
        return (l + r) // 2, (t + b) // 2

    def contains(self, x, y):
        l, t, r, b = self.rect
        return l <= x < r and t <= y < b

    def __repr__(self):
        return f"<Monitor {self.index} {self.rect} primary={self.primary}>"


MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)


def list_monitors():
    """Monitors sorted left-to-right (then top-to-bottom), indexed from 0."""
    raw = []

    def cb(hmon, _hdc, _rect, _lp):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            m, w = info.rcMonitor, info.rcWork
            raw.append(((m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom),
                        bool(info.dwFlags & MONITORINFOF_PRIMARY), info.szDevice))
        return 1

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)
    raw.sort(key=lambda r: (r[0][0], r[0][1]))
    return [Monitor(i, *r) for i, r in enumerate(raw)]


def pick_monitor(monitors, index):
    if not monitors:  # e.g. a headless session
        return Monitor(0, (0, 0, 1920, 1080), (0, 0, 1920, 1040), True, "")
    if 0 <= index < len(monitors):
        return monitors[index]
    return next((m for m in monitors if m.primary), monitors[0])


# ---------------------------------------------------------------- cursor / input
def get_cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor(x, y):
    user32.SetCursorPos(int(x), int(y))


def mouse_button_down():
    return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000 or user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds():
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    tick = kernel32.GetTickCount() & 0xFFFFFFFF
    return ((tick - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def _key(vk, up=False):
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


def press_media_play_pause():
    _key(VK_MEDIA_PLAY_PAUSE)
    _key(VK_MEDIA_PLAY_PAUSE, up=True)


def press_ctrl_alt_f(n):
    """Mouse Without Borders 'switch to machine N' shortcut (Ctrl+Alt+F1..F4)."""
    vk = VK_F1 + max(0, min(3, n - 1))
    _key(VK_CONTROL); _key(VK_MENU); _key(vk)
    _key(vk, True); _key(VK_MENU, True); _key(VK_CONTROL, True)


# ---------------------------------------------------------------- monitors power
def monitors_off():
    log.info("Turning monitors off")
    user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)


def monitors_on():
    log.info("Turning monitors on")
    user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, -1)
    kernel32.SetThreadExecutionState(ES_DISPLAY_REQUIRED)
    # a tiny synthetic mouse move is the most reliable way to wake displays
    user32.mouse_event(MOUSEEVENTF_MOVE, 0, 1, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_MOVE, 0, -1, 0, 0)


def beep():
    user32.MessageBeep(0x40)  # MB_ICONASTERISK


def lock_workstation():
    log.info("Locking workstation")
    user32.LockWorkStation()


# ---------------------------------------------------------------- single instance
_mutex = None


def acquire_single_instance(name):
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
