"""Presence through your phone over Bluetooth.

Every few seconds the paired phone is "paged" with an uncached service query. A phone that is
in range (about 5-10 m) answers within a fraction of a second; when it is gone the query times
out after ~5 s with no services. That works without any app on the phone - it only has to be
paired with this PC and have Bluetooth on.
"""
import logging
import threading
import time

from . import winrt_thread

log = logging.getLogger(__name__)

try:
    import winrt.windows.foundation  # noqa: F401
    import winrt.windows.foundation.collections  # noqa: F401
    import winrt.windows.devices.bluetooth.rfcomm  # noqa: F401
    from winrt.windows.devices.bluetooth import (
        BluetoothCacheMode, BluetoothConnectionStatus, BluetoothDevice)
    from winrt.windows.devices.enumeration import DeviceInformation
    HAVE_BT = True
except Exception:  # pragma: no cover
    HAVE_BT = False

PHONE_MAJOR_CLASS = 2  # Bluetooth class of device: Phone


async def _paired():
    out = []
    selector = BluetoothDevice.get_device_selector_from_pairing_state(True)
    for d in await winrt_thread.guarded(DeviceInformation.find_all_async_aqs_filter(selector), 10):
        is_phone = False
        try:
            dev = await winrt_thread.guarded(BluetoothDevice.from_id_async(d.id), 5)
            if dev is not None:
                is_phone = int(dev.class_of_device.major_class) == PHONE_MAJOR_CLASS
                dev.close()
        except Exception:
            pass
        out.append({"id": d.id, "name": d.name or "?", "phone": is_phone})
    out.sort(key=lambda d: (not d["phone"], d["name"].lower()))
    return out


def paired_devices():
    """[{"id", "name", "phone"}] of paired Bluetooth devices, phones first."""
    if not HAVE_BT:
        return []
    try:
        return winrt_thread.run(_paired, timeout=30)
    except Exception:
        log.exception("Listing Bluetooth devices failed")
        return []


async def _probe(device_id):
    dev = await winrt_thread.guarded(BluetoothDevice.from_id_async(device_id), 5)
    if dev is None:
        return False
    try:
        if dev.connection_status == BluetoothConnectionStatus.CONNECTED:
            return True
        res = await winrt_thread.guarded(dev.get_rfcomm_services_with_cache_mode_async(BluetoothCacheMode.UNCACHED), 10)
        return len(res.services) > 0
    finally:
        dev.close()


def probe(device_id):
    """True when the device answered (in range), False otherwise."""
    if not HAVE_BT or not device_id:
        return False
    try:
        return winrt_thread.run(lambda: _probe(device_id), timeout=20)
    except Exception:
        log.debug("Bluetooth probe failed", exc_info=True)
        return False


class PhoneWatcher(threading.Thread):
    """Keeps `near` up to date: True (in range), False (gone) or None (not known yet)."""

    def __init__(self, device_id, check_seconds=8, away_checks=2):
        super().__init__(daemon=True, name="phone")
        self.device_id = device_id
        self.check_seconds = check_seconds
        self.away_checks = max(1, away_checks)
        self.near = None
        self.last_seen = 0.0
        self._misses = 0
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            t0 = time.monotonic()
            if probe(self.device_id):
                self._misses = 0
                if self.near is not True:
                    log.info("Phone is near")
                self.near = True
                self.last_seen = time.monotonic()
            else:
                self._misses += 1
                if self._misses >= self.away_checks and self.near is not False:
                    log.info("Phone is gone")
                    self.near = False
            # check more often while the phone is gone, so coming back is noticed quickly
            interval = self.check_seconds if self.near else 2
            self._stop.wait(max(0.5, interval - (time.monotonic() - t0)))
