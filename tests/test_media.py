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
