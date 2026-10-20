# Privacy

DeskPresence uses your webcam, so here is exactly what it does with it.

- **Frames stay in memory.** Each webcam frame is analysed on your PC to find a face and its head direction, then discarded. Nothing is written to disk, recorded or uploaded.
- **No internet access.** The app does not send data anywhere. The only network traffic is optional and stays on your local network: the link to your own laptop (`away` / `back` / `break` events and the text of forwarded notifications, protected by a shared token) and the phones you pair (see below).
- **Eye tracking** (optional) runs the MediaPipe face model on the same in-memory frames. Only the fitted calibration numbers are stored.
- **Phone presence** (optional) only asks Windows whether your paired phone answers over Bluetooth. Nothing is sent to the phone, and no app is installed on it.
- **Webcam sharing** reads which apps Windows recorded as using the webcam (the list in Windows Settings → Privacy → Camera), so DeskPresence can step aside for them. It does not change those records.
- **Android app** (optional, off until you turn it on): phones you pair can see whether you are at the desk, your water and work totals for today, and — if you allow it — watch the webcam live. While any phone watches, a banner on your monitor names it. The stream goes directly from your PC to the phone over an encrypted local connection; nothing is recorded. You can turn webcam viewing off for everyone or per phone, and remove phones at any time.
- **No telemetry, no accounts, no ads.**
- **What is stored:** `%APPDATA%\DeskPresence\config.json` (your settings and gaze calibration numbers, which are a few numbers per monitor, not images) and `log.txt` (status messages).
- **Turning the camera off:** tray menu → *Pause* releases the webcam completely.

The source code is public. You can check all of this yourself.
