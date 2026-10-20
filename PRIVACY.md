# Privacy

DeskPresence uses your webcam, so here is exactly what it does with it.

- **Frames stay in memory.** Each webcam frame is analysed on your PC to find a face and its head direction, then discarded. Nothing is written to disk, recorded or uploaded.
- **No internet access.** The app does not send data anywhere. The only network traffic is the optional link to your own laptop on your local network. That link carries `away` / `back` / `break` events and the text of forwarded notifications, and it is protected by a shared token.
- **No telemetry, no accounts, no ads.**
- **What is stored:** `%APPDATA%\DeskPresence\config.json` (your settings and gaze calibration numbers, which are a few numbers per monitor, not images) and `log.txt` (status messages).
- **Turning the camera off:** tray menu → *Pause* releases the webcam completely.

The source code is public. You can check all of this yourself.
