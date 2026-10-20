# Changelog

Release builds are published automatically from `main`. See the
[Releases page](https://github.com/Jolly-Panda-Works/DeskPresence/releases) for every build's notes.

## 1.5

- Android app: working / not here / on a break, glasses of water and hours worked today, live webcam view and messages to the PC.
- Pair any number of phones with a 6-digit code; rename them, allow or deny the webcam per phone, remove them.
- While a phone watches the webcam, a banner on the monitor says who is watching.
- The PC is the server (encrypted HTTPS, pinned certificate, found automatically on the Wi-Fi network).
- Every unhandled error is written to log.txt, native crashes to crash.txt.

## 1.4

- Floating timer widget (water, break, time at the desk, eye-control and webcam buttons).
- “I drank water” button in the reminder, the widget, the tray menu and Settings; “In 10 minutes” snoozes.
- Timers count only time at the desk: they pause while you are away; 10+ minutes away restarts the break and stand-up timers.
- Phone calls through Windows Phone Link pause music and video; music resumes afterwards.
- Webcam sharing now notices video apps starting (Windows does not report failed camera opens), plus a manual Release / Take back button.
- Eye control on/off from the widget, the tray menu or Ctrl+Alt+E.
- Laptop link: settings save automatically, discovery asks every address on the home network (works with VPNs and routers that drop broadcasts), “Allow in firewall” button, clearer error messages.

## 1.3

- Settings window for every option: live webcam preview, phone range test, laptop pairing with automatic discovery and a connection test.
- Installer (asks for the install folder, desktop shortcut, start with Windows; English and Persian) and a portable zip.
- Cursor follows your eyes: MediaPipe iris tracking with a 5-dots-per-monitor calibration (Ctrl+Alt+E to toggle).
- Presence through your phone over Bluetooth, with or without the webcam.
- Webcam sharing: asks before handing the webcam to another app and takes it back afterwards.

## 1.2

- Music and video are handled differently: music (Spotify, Radio Javan, Media Player, ...) is paused and resumed; videos (YouTube, Media Player, Movies & TV, ...) are only paused.
- Media apps are detected automatically; tray menu → Music & video apps lets you change any app.

## 1.1

- Hourly water reminder.
- Forced break after 90 minutes of work: every screen is covered for 10 minutes, and the countdown only runs while the camera does not see you.
- The break screen is mirrored on the laptop.
- Persian and English interface (tray menu → Language).
- New icon and dark + orange theme shared with Image Format Converter and SnapshotAll.
- About window, automatic versioning and a GitHub Release on every push to `main`.

## 1.0

- Webcam presence detection: pause media and turn monitors off when you leave, resume when you return.
- Mouse follows the monitor you look at (after calibration).
- Laptop companion: screen and media sync, notification forwarding.
