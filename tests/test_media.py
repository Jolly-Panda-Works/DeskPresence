from deskpresence.media import MUSIC, VIDEO, IGNORE, classify, display_name

ZUNE_MUSIC = "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"


def test_music_apps_pause_and_resume():
    assert classify("Spotify.exe") == MUSIC
    assert classify("Radio Javan.exe") == MUSIC
    assert classify("com.radiojavan.desktop") == MUSIC
    assert classify("foobar2000.exe") == MUSIC


def test_video_apps_pause_only():
    assert classify("Chrome._crx_agimnkijcamfeangaknmldooml") == VIDEO  # YouTube app
    assert classify("Microsoft.ZuneVideo_8wekyb3d8bbwe!Microsoft.ZuneVideo") == VIDEO
    assert classify("PotPlayerMini64.exe") == VIDEO


def test_media_player_uses_what_it_reports():
    assert classify(ZUNE_MUSIC, playback_type=1) == MUSIC
    assert classify(ZUNE_MUSIC, playback_type=2) == VIDEO


def test_browser_tabs():
    assert classify("Chrome", playback_type=1, album="") == VIDEO           # a YouTube video
    assert classify("MSEdge", playback_type=1, album="Some Album") == MUSIC  # a real track


def test_unknown_app_follows_reported_type():
    assert classify("SomePlayer.exe", playback_type=2) == VIDEO
    assert classify("SomePlayer.exe", playback_type=1) == MUSIC


def test_user_choice_wins():
    assert classify("Spotify.exe", overrides={"spotify.exe": IGNORE}) == IGNORE
    assert classify("Chrome", overrides={"chrome": MUSIC}) == MUSIC


def test_display_names():
    assert display_name("Spotify.exe") == "Spotify"
    assert display_name(ZUNE_MUSIC) == "Media Player"
    assert display_name("Chrome._crx_agimnkijcamfeangaknmldooml") == "YouTube"
    assert display_name("308046B0AF4A39CB") == "Firefox"


def test_guarded_gives_up_without_cancelling():
    """A WinRT operation that never finishes must not hang DeskPresence (and must not be cancelled)."""
    import asyncio
    import time

    from deskpresence import winrt_thread

    async def main():
        never = asyncio.get_running_loop().create_future()
        t = time.monotonic()
        try:
            await winrt_thread.guarded(never, 0.2)
            raise AssertionError("should have timed out")
        except TimeoutError:
            pass
        assert time.monotonic() - t < 1 and not never.cancelled()
        assert await winrt_thread.guarded(asyncio.sleep(0, "ok"), 1) == "ok"
    asyncio.run(main())


def test_scan_never_blocks(monkeypatch):
    """The tray menu reads the cached list; the real scan happens on the WinRT thread."""
    import time

    from deskpresence import media

    started = []
    monkeypatch.setattr(media.winrt_thread, "submit", lambda factory: started.append(1) or _Done())
    m = media.MediaController()
    m.seen = {"spotify.exe": ("Spotify", "music")}
    t = time.monotonic()
    assert m.scan() == {"spotify.exe": ("Spotify", "music")}
    assert time.monotonic() - t < 0.1 and started == [1]


class _Done:
    def done(self):
        return True
