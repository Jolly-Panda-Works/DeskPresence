#!/usr/bin/env python3
"""Generate the app icons with Pillow, using the dark + orange palette shared with
Image Format Converter and SnapshotAll. Run from the repository root when the artwork changes:

    python tools/make_icons.py

Outputs
  assets/logo.png            512 x 512 logo
  assets/logo_64.png          64 x  64 logo (About window)
  assets/icon.ico            multi-size Windows icon (exe)
  docs/social-preview.png    1280 x 640 image for GitHub -> Settings -> Social preview
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DOCS = ROOT / "docs"

BG = "#110D0A"
PANEL = "#1F1813"
FG = "#F5EEE8"
MUTED = "#A99B8E"
ORANGE = "#F97316"
ORANGE_H = "#FB923C"
ORANGE_D = "#EA580C"
ON_ORANGE = "#1A0E05"

SIZE = 1024


def _hex(c, a=255):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def _gradient(size, top, bottom):
    w, h = size
    a, b = _hex(top), _hex(bottom)
    img = Image.new("RGBA", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        k = y / max(h - 1, 1)
        draw.line([(0, y), (w, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(4)))
    return img


def draw_logo(size=SIZE):
    """Orange tile, a white person at a monitor, and a dark badge with an orange 'eye' (= the webcam sees you)."""
    s = size / 1024
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((int(48 * s), int(48 * s), int(976 * s), int(976 * s)),
                                           radius=int(220 * s), fill=255)
    canvas.paste(_gradient((size, size), ORANGE_H, ORANGE_D), (0, 0), mask)

    d = ImageDraw.Draw(canvas)
    white = _hex("#FFFFFF")
    # monitor
    d.rounded_rectangle((int(210 * s), int(200 * s), int(814 * s), int(600 * s)), radius=int(40 * s),
                        outline=white, width=int(44 * s))
    d.rectangle((int(470 * s), int(600 * s), int(554 * s), int(690 * s)), fill=white)
    d.rounded_rectangle((int(360 * s), int(680 * s), int(664 * s), int(730 * s)), radius=int(25 * s), fill=white)
    # person inside the monitor
    d.ellipse((int(450 * s), int(280 * s), int(574 * s), int(404 * s)), fill=white)
    d.pieslice((int(380 * s), int(430 * s), int(644 * s), int(694 * s)), 180, 360, fill=white)

    # badge with an eye
    bx0, by0, bx1, by1 = int(600 * s), int(600 * s), int(940 * s), int(940 * s)
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((bx0, by0 + int(14 * s), bx1, by1 + int(14 * s)), fill=(0, 0, 0, 110))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(int(18 * s))))
    d = ImageDraw.Draw(canvas)
    d.ellipse((bx0, by0, bx1, by1), fill=_hex(BG))
    cx, cy = (bx0 + bx1) // 2, (by0 + by1) // 2
    # almond-shaped eye: two sine arcs
    ew, eh = 120 * s, 72 * s
    steps = 40
    top = [(cx - ew + 2 * ew * i / steps, cy - eh * math.sin(math.pi * i / steps)) for i in range(steps + 1)]
    bottom = [(x, 2 * cy - y) for x, y in reversed(top)]
    d.polygon(top + bottom, fill=_hex(ORANGE))
    d.ellipse((cx - 50 * s, cy - 50 * s, cx + 50 * s, cy + 50 * s), fill=_hex(BG))
    d.ellipse((cx - 26 * s, cy - 26 * s, cx + 26 * s, cy + 26 * s), fill=_hex(ORANGE))
    return canvas


def _font(size, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arialbd.ttf" if bold else "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def social_preview(logo):
    img = Image.new("RGBA", (1280, 640), _hex(BG))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, 1240, 600), radius=36, fill=_hex(PANEL))
    img.alpha_composite(logo.resize((300, 300), Image.LANCZOS), (110, 170))
    d.text((470, 200), "DeskPresence", font=_font(84, True), fill=_hex(FG))
    d.text((474, 310), "Your PC knows when you leave the desk.", font=_font(34), fill=_hex(MUTED))
    d.text((474, 370), "Pause music · monitors off · mouse follows your gaze", font=_font(28), fill=_hex(ORANGE))
    d.text((474, 470), "Windows · Open source · Usef Farahmand", font=_font(24), fill=_hex(MUTED))
    return img


def main():
    ASSETS.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    logo = draw_logo()
    logo.resize((512, 512), Image.LANCZOS).save(ASSETS / "logo.png")
    logo.resize((64, 64), Image.LANCZOS).save(ASSETS / "logo_64.png")
    logo.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    social_preview(logo).convert("RGB").save(DOCS / "social-preview.png")
    print("Icons written to", ASSETS)


if __name__ == "__main__":
    main()
