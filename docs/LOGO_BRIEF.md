# DeskPresence: logo brief

## About the app

**DeskPresence** is a free, open-source Windows tray app by **Usef Farahmand**. It uses the webcam to tell whether you are sitting at your desk:

- You get up → it pauses the music, pauses videos and turns the monitors off. The computer stays on.
- You come back → the monitors turn on and the music plays again.
- It moves the mouse cursor to the monitor you are looking at (setups with two monitors).
- It reminds you to drink water every hour.
- After 90 minutes of work it covers the screens for a 10-minute break. The break timer only runs while you are away from the desk.
- It works together with a laptop: one mouse controls both, and notifications are shown on a single screen.

**The idea in one sentence:** *the computer knows when you are there.* The logo should say: a person, a desk/monitor, and something watching kindly. That "something" should feel like a friendly eye or presence, not a surveillance camera. The app is about health and comfort, not monitoring.

**Tone:** calm, friendly, modern, trustworthy. Not creepy, not "security camera", not "spy".

## Brand family (must match)

The logo sits next to two other apps by the same author:

- Image Format Converter: <https://github.com/Usef-Farahmand/image-format-converter>
- SnapshotAll: <https://github.com/Usef-Farahmand/SnapshotAll>

Their shared style:

- An **app tile**: a square with large rounded corners (about 22% corner radius), filled with an **orange vertical gradient**.
- A **white, flat, bold glyph** in the middle (simple shapes, no thin lines).
- Often a small **round dark badge** in the bottom-right corner with an orange symbol.
- No text inside the icon.

### Colours

| Use | Hex |
|---|---|
| Orange (main) | `#F97316` |
| Orange light (gradient top) | `#FB923C` |
| Orange dark (gradient bottom) | `#EA580C` |
| Dark background / badge | `#110D0A` |
| Dark panel | `#1F1813` |
| Text on dark | `#F5EEE8` |
| Muted text | `#A99B8E` |
| Glyph | `#FFFFFF` |

## Requirements

- **Format:** PNG, **1024 × 1024**, transparent background outside the rounded tile. An SVG would be ideal.
- **Must stay readable at 16 × 16 px.** It appears in the Windows tray next to the clock. Use 1 to 3 bold shapes.
- The tray version gets a small coloured **status dot** in the bottom-right corner (green / yellow / blue / grey), drawn by the app. Leave that corner relatively calm, or make the badge there.
- No text, no letters, no photographic detail, no 3D, no drop shadows except a soft one under the badge.

## Ideas to explore

1. **Monitor + person + eye badge** (the current placeholder): a white monitor outline with a person's head and shoulders inside it, and a dark round badge with an orange eye.
2. **Chair + glow:** a simple office chair silhouette with a soft "presence" arc above it.
3. **Person + pause symbol:** a head-and-shoulders silhouette whose body forms a ‖ pause sign. This works well because the app pauses media when you leave.
4. **Monitor with a sleeping moon / waking sun** in the badge: monitors off when away, on when back.

## Prompt for an AI image generator (English)

```
App icon for a Windows desktop utility called "DeskPresence".
A rounded-square app tile (iOS/Windows 11 style, large corner radius) filled with a vertical
orange gradient from #FB923C at the top to #EA580C at the bottom. In the centre, a bold flat
white glyph: a computer monitor with a simple person (round head and shoulders) inside it.
In the bottom-right corner, a small round dark-brown badge (#110D0A) containing a friendly
orange (#F97316) eye symbol. Flat vector style, minimal, crisp geometric shapes, no text,
no letters, no gradients on the glyph, transparent background outside the tile,
centred, 1024x1024, must remain legible at 16x16 pixels.
```

Variant prompt (pause idea):

```
Flat vector app icon, rounded-square tile with orange gradient (#FB923C to #EA580C).
White minimal glyph: a head-and-shoulders silhouette whose torso is shaped like a pause
symbol (two vertical rounded bars). Small dark (#110D0A) circular badge bottom-right with
an orange dot. No text, transparent background, 1024x1024, simple enough for a 16px tray icon.
```

## How to hand it over

Send the final **1024 × 1024 PNG** (and SVG if you have it). The icon files are generated from it:

- `assets/logo.png` (512 px): About window and README
- `assets/logo_64.png`: About window
- `assets/icon.ico` (16 to 256 px): the exe icon
- the tray icon with its status dot
- `docs/social-preview.png`: GitHub social preview
