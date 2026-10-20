<p align="center">
  <img src="assets/logo.png" alt="DeskPresence logo" width="120">
</p>

# DeskPresence

**Your PC knows when you leave the desk. It uses the webcam to pause your music and turn the monitors off when you get up, and brings both back when you sit down again.**

[![Build](https://github.com/Jolly-Panda-Works/DeskPresence/actions/workflows/build.yml/badge.svg)](https://github.com/Jolly-Panda-Works/DeskPresence/actions/workflows/build.yml)
[![Latest release](https://img.shields.io/github/v/release/Jolly-Panda-Works/DeskPresence?display_name=tag&color=F97316)](https://github.com/Jolly-Panda-Works/DeskPresence/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Jolly-Panda-Works/DeskPresence/total?color=F97316)](https://github.com/Jolly-Panda-Works/DeskPresence/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-lightgrey)](#download)

[Download](https://github.com/Jolly-Panda-Works/DeskPresence/releases/latest/download/DeskPresence.exe) · [فارسی](README.fa.md) · [Report a bug](https://github.com/Jolly-Panda-Works/DeskPresence/issues/new?template=bug_report.md) · [Request a feature](https://github.com/Jolly-Panda-Works/DeskPresence/issues/new?template=feature_request.md)

---

## Features

| | |
|---|---|
| **Leave the desk** | No face for ~10 seconds (and no keyboard/mouse use) → music and videos pause and all monitors turn off. The PC keeps running. |
| **Come back** | Monitors turn back on and the **music** DeskPresence paused plays again. Videos stay paused. |
| **Mouse follows your gaze** | After a 10-second calibration, the cursor jumps to the monitor you turn to, back to where it was on that monitor. |
| **Water reminder** | Every hour: “Time to drink water!” (waits until you are at the desk). |
| **Forced break** | After 90 minutes of work, every screen is covered for a 10-minute break. The countdown **only runs while the camera does not see you**, so sitting there does not count. Leaving for 10+ minutes on your own counts as a break too. |
| **Laptop companion** | Run it on your laptop too: its screen and music follow the desktop, it shows the break screen, and its notifications are forwarded to one monitor of the desktop. |
| **Mouse Without Borders** | Use one mouse and keyboard for both machines (PowerToys). Optionally the cursor even moves to the laptop when you look at it. |
| **Persian and English** | Switch from the tray menu → Language. |

Everything runs locally. Webcam frames are processed in memory and are never saved or uploaded. See [PRIVACY.md](PRIVACY.md).

## Music & video apps

Apps are detected automatically through Windows' media controls, which list every app that shows up in the volume flyout:

| Kind | When you leave | When you come back | Examples |
|---|---|---|---|
| Music | pause | play again | Spotify, Radio Javan, Media Player (music), YouTube Music, foobar2000, AIMP, MusicBee, Apple Music, Deezer |
| Video | pause | stays paused | YouTube, Media Player (video), Movies & TV, VLC (video), PotPlayer, MPC-HC, Netflix |

Apps that are not in the built-in list are classified by what they report to Windows (music or video). Browser tabs count as music when the track has an album (YouTube Music, Spotify web, ...) and as video otherwise.
To change any app: tray menu → **Music & video apps** → *Music: pause and resume* / *Video: pause only* / *Leave alone*. An app appears in that list once it has played something.

## Download

1. Download **[DeskPresence.exe](https://github.com/Jolly-Panda-Works/DeskPresence/releases/latest/download/DeskPresence.exe)** from the latest release. It is a single portable file, so there is nothing to install.
2. Run it. An orange icon appears next to the clock. The coloured dot shows the status: green = at the desk, yellow = away, blue = on a break, grey = paused.
3. Tray menu → **Calibrate gaze…** and look at the dot on each monitor.
4. Tray menu → **Start with Windows**.

> Windows SmartScreen may warn about an unsigned app the first time: *More info → Run anyway*. The SHA-256 checksum of every release is in `SHA256SUMS.txt`.

## Laptop setup

1. Install **[PowerToys](https://learn.microsoft.com/windows/powertoys/)** on both machines and pair them in **Mouse Without Borders**.
2. On the desktop: tray menu → *Edit settings*, set `"network_enabled": true` and copy the `token`.
3. On the laptop, in its settings file:
   ```json
   "role": "laptop",
   "network_enabled": true,
   "desktop_host": "192.168.1.10",
   "token": "<the desktop's token>"
   ```
4. Restart DeskPresence on both. Allow it on **Private** networks if the Windows firewall asks.
5. On the laptop, turn on **Do not disturb**. Its notifications are still forwarded and are shown on the desktop monitor set in `notification_monitor`.

Windows always shows the desktop's own notifications on the *main display*. To choose which monitor that is: Settings → System → Display → *Make this my main display*.

**Gaze → laptop (experimental):** in Mouse Without Borders, set the *switch between machines* shortcut to Ctrl+Alt+F1…F4. Then set `"mwb": {"enabled": true, "desktop_hotkey": 1, "laptop_hotkey": 2}` and calibrate again.

## Settings

The settings file is `%APPDATA%\DeskPresence\config.json` (tray menu → *Edit settings*, then *Apply saved settings*).

| Key | Default | Meaning |
|---|---|---|
| `language` | `auto` | `auto`, `fa` or `en` |
| `away_seconds` | 10 | Seconds without a face before you count as away |
| `idle_guard_seconds` | 20 | Never turn anything off if the keyboard/mouse was used this recently |
| `wake_on_input` | true | Touching the keyboard/mouse also means you are back |
| `camera_index` | 0 | Which webcam to use |
| `water_reminder_minutes` | 60 | `0` = off |
| `forced_break` | 90 / 10 | `work_minutes`, `break_minutes`, `enabled`, `allow_skip` |
| `break_reminder_minutes` | 50 | A gentle “stand up” popup (`0` = off) |
| `lock_after_away_minutes` | 0 | Lock Windows after being away this long (`0` = never) |
| `gaze_stable_seconds` | 0.6 | How long you must look at a monitor before the cursor moves |
| `notification_monitor` | -1 | `-1` = main display, else 0, 1, … from left to right |

## Run from source

```bash
pip install -r requirements-dev.txt
```
```bash
python scripts/download_model.py
```
```bash
python run.py
```

Run the tests with `python -m pytest`. Regenerate the icons with `python tools/make_icons.py`.

## How the GitHub Action builds it

Every push builds `DeskPresence.exe` on `windows-latest` after the tests pass, and keeps it for 14 days under *Actions → the run → Artifacts*.

| Build from | Version | Published |
|---|---|---|
| `main` | `MAJOR.MINOR.<run number>`, e.g. `1.1.42` | Git tag + public GitHub Release with the exe |
| a tag `vX.Y.Z` | `X.Y.Z` | GitHub Release |
| any other branch / PR | `MAJOR.MINOR.0-dev.<run>` | Artifact only |

`MAJOR.MINOR` comes from the [`VERSION`](VERSION) file. The version shows up in the About window, the exe's file properties and the release name.

## Project structure

```
deskpresence/
  controller.py     presence state machine, breaks, water, gaze -> cursor, laptop sync
  vision.py         webcam + YuNet face detector + head-pose estimate
  media.py          pause / resume through Windows media sessions
  winapi.py         monitors, cursor, power, keyboard (ctypes)
  network.py        desktop <-> laptop link (JSON lines over TCP, shared token)
  notifications.py  reads Windows notifications on the laptop
  ui.py             popups, break screen, calibration, About (Tk)
  tray.py           tray icon and menu
  i18n.py           Persian / English strings
tools/              set_version.py, make_icons.py
tests/              pytest suite (runs in CI before every build)
```

## Contributing

Pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Please report security issues privately as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 [Usef Farahmand](https://github.com/Usef-Farahmand) · [useffarahmand.com](https://www.useffarahmand.com/)

Face detection uses the [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) model from OpenCV Zoo (MIT).
