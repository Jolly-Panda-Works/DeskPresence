"""Pause / resume media through Windows' media sessions (SMTC).

Every app that plays audio or video through Windows' media controls (the ones shown in the
volume flyout) is detected automatically. Each one is classified as:

  music  -> paused when you leave, resumed when you come back   (Spotify, Radio Javan, ...)
  video  -> paused when you leave, NOT resumed                  (YouTube, Movies & TV, ...)
  ignore -> left alone

Classification order: your choice in the tray menu -> the built-in list of known apps ->
what the app itself reports to Windows (music / video) -> for browsers, a track with an
album is music, anything else is video.
Only sessions that were actually playing are paused, and only those are resumed.
"""
import asyncio
import logging
import threading

from . import winapi, winrt_thread

log = logging.getLogger(__name__)

try:
    import winrt.windows.foundation  # noqa: F401
    import winrt.windows.foundation.collections  # noqa: F401
    import winrt.windows.media  # noqa: F401  (MediaPlaybackType)
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    HAVE_SMTC = True
except Exception:  # pragma: no cover - depends on the machine
    log.warning("WinRT media control unavailable, falling back to the media key")
    HAVE_SMTC = False

AUTO, MUSIC, VIDEO, IGNORE = "auto", "music", "video", "ignore"
MODES = (AUTO, MUSIC, VIDEO, IGNORE)

# MediaPlaybackType values reported by apps
_TYPE_MUSIC, _TYPE_VIDEO = 1, 2

# (substring of the app id, kind or None = ask the app, display name)
KNOWN_APPS = [
    ("spotify", MUSIC, "Spotify"),
    ("radiojavan", MUSIC, "Radio Javan"),
    ("radio javan", MUSIC, "Radio Javan"),
    ("zunemusic", None, "Media Player"),            # Windows 11 Media Player: music and video
    ("zunevideo", VIDEO, "Movies & TV"),
    ("wmplayer", None, "Windows Media Player"),
    ("cinhimbnkkaeohfgghhklpknlkffjgod", MUSIC, "YouTube Music"),  # Chrome/Edge app
    ("agimnkijcamfeangaknmldooml", VIDEO, "YouTube"),               # Chrome/Edge app
    ("youtube music", MUSIC, "YouTube Music"),
    ("youtube", VIDEO, "YouTube"),
    ("applemusic", MUSIC, "Apple Music"),
    ("itunes", MUSIC, "iTunes"),
    ("foobar2000", MUSIC, "foobar2000"),
    ("aimp", MUSIC, "AIMP"),
    ("musicbee", MUSIC, "MusicBee"),
    ("winamp", MUSIC, "Winamp"),
    ("deezer", MUSIC, "Deezer"),
    ("tidal", MUSIC, "TIDAL"),
    ("soundcloud", MUSIC, "SoundCloud"),
    ("amazonmusic", MUSIC, "Amazon Music"),
    ("vlc", None, "VLC"),
    ("mpc-hc", VIDEO, "MPC-HC"),
    ("mpc-be", VIDEO, "MPC-BE"),
    ("potplayer", VIDEO, "PotPlayer"),
    ("kmplayer", VIDEO, "KMPlayer"),
    ("netflix", VIDEO, "Netflix"),
    ("primevideo", VIDEO, "Prime Video"),
    ("disney", VIDEO, "Disney+"),
]

BROWSERS = [
    ("msedge", "Microsoft Edge"),
    ("chrome", "Google Chrome"),
    ("308046b0af4a39cb", "Firefox"),
    ("firefox", "Firefox"),
    ("opera", "Opera"),
    ("brave", "Brave"),
    ("vivaldi", "Vivaldi"),
]


def app_key(aumid):
    return (aumid or "").strip().lower()


def display_name(aumid):
    key = app_key(aumid)
    for needle, _kind, name in KNOWN_APPS:
        if needle in key:
            return name
    for needle, name in BROWSERS:
        if needle in key:
            return name
    name = (aumid or "?").split("!")[-1]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name


def is_browser(aumid):
    key = app_key(aumid)
    return any(n in key for n, _ in BROWSERS) and not any(n in key for n, _k, _d in KNOWN_APPS)


def classify(aumid, playback_type=0, album="", overrides=None):
    """Returns MUSIC, VIDEO or IGNORE for a media session."""
    key = app_key(aumid)
    mode = (overrides or {}).get(key, AUTO)
    if mode in (MUSIC, VIDEO, IGNORE):
        return mode
    for needle, kind, _name in KNOWN_APPS:
        if needle in key:
            if kind:
                return kind
            break
    if is_browser(aumid):
        # browsers report every tab as "music"; a real track has an album, a video does not
        return MUSIC if album else VIDEO
    if playback_type == _TYPE_VIDEO:
        return VIDEO
    return MUSIC


class MediaController:
    def __init__(self, cfg=None):
        self.cfg = cfg
        self._resume = {}  # reason ("away", "call") -> app ids to play again
        self._fallback_paused = False
        self.seen = {}  # app key -> (display name, last detected kind)
        self._lock = threading.Lock()
        self._refreshing = None
        self._mgr = None        # the session manager, requested once (WinRT thread only)
        self._mgr_task = None

    def _overrides(self):
        return dict(self.cfg["media_apps"]) if self.cfg is not None else {}

    async def _manager(self):
        """The media session manager. Requested once; while Windows has not answered yet no
        second request is started (a stuck request would otherwise pile up new ones)."""
        if self._mgr is not None:
            return self._mgr
        if self._mgr_task is None or self._mgr_task.done():
            self._mgr_task = asyncio.ensure_future(SessionManager.request_async())
        self._mgr = await winrt_thread.guarded(self._mgr_task, 5)
        return self._mgr

    async def _sessions(self):
        mgr = await self._manager()
        out = []
        for s in mgr.get_sessions():
            aumid = s.source_app_user_model_id
            ptype, album = 0, ""
            try:
                props = await winrt_thread.guarded(s.try_get_media_properties_async(), 3)
                ptype = int(props.playback_type or 0)
                album = props.album_title or ""
            except Exception:
                pass
            kind = classify(aumid, ptype, album, self._overrides())
            with self._lock:
                self.seen[app_key(aumid)] = (display_name(aumid), kind)
            out.append((s, aumid, kind))
        return out

    async def _pause(self):
        resume = []
        for s, aumid, kind in await self._sessions():
            try:
                if kind == IGNORE or s.get_playback_info().playback_status != PlaybackStatus.PLAYING:
                    continue
                if await winrt_thread.guarded(s.try_pause_async(), 3):
                    log.info("Paused %s (%s)", aumid, kind)
                    if kind == MUSIC:
                        resume.append(aumid)
            except Exception:
                log.exception("Pausing a session failed")
        return resume

    async def _resume_ids(self, ids):
        for s, aumid, _kind in await self._sessions():
            try:
                if aumid in ids and s.get_playback_info().playback_status != PlaybackStatus.PLAYING:
                    await winrt_thread.guarded(s.try_play_async(), 3)
                    log.info("Resumed %s", aumid)
            except Exception:
                log.exception("Resuming a session failed")

    def scan(self):
        """The media apps seen so far (for the tray menu / settings). Never blocks: it returns the
        cached list and refreshes it in the background on the WinRT thread."""
        if HAVE_SMTC and (self._refreshing is None or self._refreshing.done()):
            try:
                self._refreshing = winrt_thread.submit(self._sessions)
            except Exception:
                log.debug("Media scan failed", exc_info=True)
        with self._lock:
            return dict(self.seen)

    def pause(self, reason="away"):
        """Pauses what is playing. Music paused for `reason` is resumed by resume(reason)."""
        if HAVE_SMTC:
            try:
                ids = winrt_thread.run(self._pause, timeout=20)
                self._resume[reason] = self._resume.get(reason, []) + ids
                return
            except Exception as e:
                # Windows' media controls did not answer: do nothing rather than pressing the
                # play/pause key blindly (that would START music when nothing was playing)
                log.warning("Could not pause media: %s", e or type(e).__name__)
            return
        if reason == "away":  # no media controls on this Windows: the media key is all we have
            winapi.press_media_play_pause()
            self._fallback_paused = True

    def resume(self, reason="away"):
        ids = self._resume.pop(reason, [])
        if HAVE_SMTC and ids:
            try:
                winrt_thread.run(lambda: self._resume_ids(ids), timeout=20)
            except Exception as e:
                log.warning("Could not resume media: %s", e or type(e).__name__)
        elif reason == "away" and self._fallback_paused:
            winapi.press_media_play_pause()
        if reason == "away":
            self._fallback_paused = False

    def move(self, src, dst):
        """Hand paused music over to another reason (a call ended while you are away)."""
        ids = self._resume.pop(src, [])
        if ids:
            self._resume[dst] = self._resume.get(dst, []) + ids
