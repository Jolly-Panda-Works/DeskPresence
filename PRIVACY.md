# Privacy

DeskPresence uses your webcam, so here is exactly what it does with it.

- **Frames stay in memory.** Each webcam frame is analysed on your PC to find a face, its head direction or a person, then discarded. Nothing is written to disk, recorded or uploaded.
- **No internet access.** The app does not send data anywhere. The only network traffic is the optional link to your own laptop on your local network. That link carries `away` / `back` / `break` events and the text of forwarded notifications, and it is protected by a shared token.
- **Eye tracking** (optional) runs the MediaPipe face model on the same in-memory frames. Only the fitted calibration numbers are stored.
- **Only me** (optional): *Teach my face* stores up to 12 face descriptors (128 numbers each, computed by the SFace model) in config.json. They are not pictures and a face cannot be rebuilt from them. *Forget* deletes them.
- **Desk exercises** (optional) run the MediaPipe pose model on the same in-memory frames to count repetitions. Nothing from the exercises is stored.
- **Phone presence** (optional) only asks Windows whether your paired phone answers over Bluetooth. Nothing is sent to the phone, and no app is installed on it.
- **Webcam sharing** reads which apps Windows recorded as using the webcam (the list in Windows Settings → Privacy → Camera), so DeskPresence can step aside for them. It does not change those records.
- **No telemetry, no accounts, no ads.**
- **What is stored:** `%APPDATA%\DeskPresence\config.json` (your settings and gaze calibration numbers, which are a few numbers per monitor, not images) and `log.txt` (status messages).
- **Turning the camera off:** tray menu → *Pause* releases the webcam completely.

The source code is public. You can check all of this yourself.
