"""Reads Windows toast notifications (used on the laptop to forward them)."""
import asyncio
import logging
import threading
import time

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


class NotificationWatcher(threading.Thread):
    def __init__(self, on_notification, dismiss=False, interval=2.0):
        super().__init__(daemon=True, name="notifications")
        self.on_notification = on_notification
        self.dismiss = dismiss
        self.interval = interval
        self._stop = threading.Event()
        self._seen = set()

    def stop(self):
        self._stop.set()

    async def _poll(self, listener, first):
        items = await listener.get_notifications_async(NotificationKinds.TOAST)
        current = set()
        for n in items:
            current.add(n.id)
            if n.id in self._seen:
                continue
            self._seen.add(n.id)
            if first:  # don't re-send everything already in the action center
                continue
            try:
                app = n.app_info.display_info.display_name
            except Exception:
                app = ""
            texts = []
            try:
                binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
                if binding is not None:
                    texts = [t.text for t in binding.get_text_elements()]
            except Exception:
                log.exception("Reading notification text failed")
            title = texts[0] if texts else app
            body = "\n".join(texts[1:])
            self.on_notification(app, title, body)
            if self.dismiss:
                try:
                    listener.remove_notification(n.id)
                except Exception:
                    pass
        if len(self._seen) > 2000:  # keep the set bounded
            self._seen = current

    async def _main(self):
        listener = UserNotificationListener.current
        status = await listener.request_access_async()
        if status != UserNotificationListenerAccessStatus.ALLOWED:
            log.error("Notification access denied (%s). Enable it in Settings > Privacy > Notifications", status)
            return
        first = True
        while not self._stop.is_set():
            try:
                await self._poll(listener, first)
            except Exception:
                log.exception("Notification poll failed")
            first = False
            await asyncio.sleep(self.interval)

    def run(self):
        if not HAVE_LISTENER:
            log.error("WinRT notification listener unavailable")
            return
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("Notification watcher crashed")
            time.sleep(1)
