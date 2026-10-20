"""Pause / resume whatever is playing, via Windows' media sessions (SMTC).

Only sessions that were actually playing are paused, and only those are resumed,
so music you had paused yourself is never started by accident.
"""
import asyncio
import logging

from . import winapi

log = logging.getLogger(__name__)

try:
    import winrt.windows.foundation  # noqa: F401
    import winrt.windows.foundation.collections  # noqa: F401
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    HAVE_SMTC = True
except Exception:  # pragma: no cover - depends on the machine
    log.warning("WinRT media control unavailable, falling back to the media key")
    HAVE_SMTC = False


class MediaController:
    def __init__(self):
        self._paused_ids = []
        self._fallback_paused = False

    async def _pause(self):
        mgr = await SessionManager.request_async()
        paused = []
        for s in mgr.get_sessions():
            try:
                if s.get_playback_info().playback_status == PlaybackStatus.PLAYING:
                    if await s.try_pause_async():
                        paused.append(s.source_app_user_model_id)
            except Exception:
                log.exception("Pausing a session failed")
        return paused

    async def _resume(self, ids):
        mgr = await SessionManager.request_async()
        for s in mgr.get_sessions():
            try:
                if s.source_app_user_model_id in ids and \
                        s.get_playback_info().playback_status != PlaybackStatus.PLAYING:
                    await s.try_play_async()
            except Exception:
                log.exception("Resuming a session failed")

    def pause(self):
        if HAVE_SMTC:
            try:
                self._paused_ids = asyncio.run(self._pause())
                log.info("Paused media: %s", self._paused_ids)
                return
            except Exception:
                log.exception("SMTC pause failed")
        winapi.press_media_play_pause()
        self._fallback_paused = True

    def resume(self):
        if HAVE_SMTC and self._paused_ids:
            try:
                asyncio.run(self._resume(self._paused_ids))
                log.info("Resumed media: %s", self._paused_ids)
            except Exception:
                log.exception("SMTC resume failed")
            self._paused_ids = []
        elif self._fallback_paused:
            winapi.press_media_play_pause()
        self._fallback_paused = False
