"""Windows Firewall rule for the desktop <-> laptop link.

When the "allow access" prompt was dismissed, Windows silently adds BLOCK rules for the app,
which override any allow rule. allow() removes every rule for this exe and adds one allow rule
(asks for administrator rights once).
"""
import ctypes
import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)

RULE = "DeskPresence"
CREATE_NO_WINDOW = 0x08000000


def exe_path():
    return os.path.abspath(sys.executable)


def rule_exists():
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE}"],
                           capture_output=True, text=True, timeout=10, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0 and "Allow" in r.stdout
    except Exception:
        log.debug("Firewall check failed", exc_info=True)
        return False


def allow():
    """Opens a UAC prompt; returns True when the elevated command was started."""
    exe = exe_path()
    cmd = (f'/c netsh advfirewall firewall delete rule name=all program="{exe}" & '
           f'netsh advfirewall firewall delete rule name="{RULE}" & '
           f'netsh advfirewall firewall add rule name="{RULE}" dir=in action=allow '
           f'program="{exe}" enable=yes profile=any')
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd, None, 0)
    log.info("Firewall rule requested (%s)", rc)
    return rc > 32
