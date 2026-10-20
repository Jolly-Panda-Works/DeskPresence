"""Pauses media while you are on a phone call (through Windows Phone Link).

Phone Link (PhoneExperienceHost.exe) connects your phone to the PC over Bluetooth. Two signals:

  ringing  - Phone Link shows an incoming-call notification
  talking  - Phone Link has an active audio session (the call audio plays through the PC)

A call starts when either appears and ends when both have been gone for a few seconds.
Needs: Phone Link set up with calls, and notification access for desktop apps
(Windows Settings -> Privacy & security -> Notifications).
"""
import asyncio
import logging
import threading
import time

from . import winrt_thread

log = logging.getLogger(__name__)

try:
    import winrt.windows.foundation  # noqa: F401
    import winrt.windows.foundation.collections  # noqa: F401
    import winrt.windows.applicationmodel  # noqa: F401
    from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
    from winrt.windows.ui.notifications.management import (
        UserNotificationListener, UserNotificationListenerAccessStatus)
    HAVE_LISTENER = True
except Exception:  # pragma: no cover
    HAVE_LISTENER = False

PHONE_LINK_IDS = ("microsoft.yourphone", "phoneexperiencehost", "phone link")
PHONE_LINK_EXE = "phoneexperiencehost.exe"
# whole phrases only: a text message that merely contains the word "call" must not pause anything
CALL_WORDS = ("incoming call", "incoming voice call", "call from", "تماس ورودی", "تماس دریافتی",
              "eingehender anruf", "appel entrant", "llamada entrante", "chiamata in arrivo", "входящий вызов",
              "gelen arama")
NOT_A_CALL = ("missed", "voicemail", "بی‌پاسخ", "از دست رفته", "پیام صوتی", "verpasst", "manqué", "perdida")


def is_call_text(texts):
    blob = " ".join(texts).lower()
    return any(w in blob for w in CALL_WORDS) and not any(w in blob for w in NOT_A_CALL)


def phone_link_audio_active():
    """True while Phone Link plays audio (an ongoing call)."""
    try:
        from pycaw.pycaw import AudioUtilities
        for s in AudioUtilities.GetAllSessions():
            if s.Process is not None and s.Process.name().lower() == PHONE_LINK_EXE and s.State == 1:
                return True
    except Exception:
        log.debug("Audio session check failed", exc_info=True)
    return False


class CallWatcher(threading.Thread):
    def __init__(self, on_start, on_end, end_grace=4.0, interval=1.0):
        super().__init__(daemon=True, name="calls")
        self.on_start, self.on_end = on_start, on_end
        self.end_grace, self.interval = end_grace, interval
        self.in_call = False
        self._quiet_since = None
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    async def _ringing(self, listener):
        if listener is None:
            return False
        ringing = False
        for n in await winrt_thread.guarded(listener.get_notifications_async(NotificationKinds.TOAST), 5):
            try:
                aumid = (n.app_info.app_user_model_id or "").lower()
                name = (n.app_info.display_info.display_name or "").lower()
            except Exception:
                continue
            if not any(p in aumid or p in name for p in PHONE_LINK_IDS):
                continue
            texts = []
            try:
                binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
                if binding is not None:
                    texts = [t.text for t in binding.get_text_elements()]
            except Exception:
                pass
            # never log the texts: they contain contact names and message previews
            if is_call_text(texts):
                ringing = True
        return ringing

    async def _main(self):
        listener = None
        if HAVE_LISTENER:
            try:
                listener = UserNotificationListener.current
                status = await winrt_thread.guarded(listener.request_access_async(), 10)
                if status != UserNotificationListenerAccessStatus.ALLOWED:
                    log.warning("No notification access: incoming calls are only noticed once answered")
                    listener = None
            except Exception:
                log.exception("Notification listener unavailable")
                listener = None
        while not self._stop.is_set():
            try:
                active = await self._ringing(listener) or phone_link_audio_active()
            except Exception:
                log.debug("Call check failed", exc_info=True)
                active = False
            now = time.monotonic()
            if active:
                self._quiet_since = None
                if not self.in_call:
                    self.in_call = True
                    log.info("Phone call started")
                    self._fire(self.on_start)
            elif self.in_call:
                if self._quiet_since is None:
                    self._quiet_since = now
                elif now - self._quiet_since >= self.end_grace:
                    self.in_call = False
                    log.info("Phone call ended")
                    self._fire(self.on_end)
            await asyncio.sleep(self.interval)

    @staticmethod
    def _fire(callback):
        # callbacks use asyncio.run() themselves, which cannot run inside this thread's event loop
        threading.Thread(target=callback, daemon=True).start()

    def run(self):
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("Call watcher crashed")
