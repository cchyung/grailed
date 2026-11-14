#!/usr/bin/env python3
"""Labeled contact sheets for eyeballing a batch of photos.

  .venv/bin/python tools/contact_sheet.py intake photos/ SHEET_DIR
      Loose IMG_*.JPG in capture order (EXIF DateTimeOriginal), 12 per sheet, labeled with the
      file number. Use it to group shots into items: consecutive runs of the same garment.

  .venv/bin/python tools/contact_sheet.py review photos/out SHEET_DIR
      One row per item folder showing the processed 01.jpg.. in order. Use it to QA crops/color.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
FONT = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)


def capture_time(p):
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    try:
        exif = Image.open(p).getexif().get_ifd(0x8769)
        return exif.get(36867) or ""  # DateTimeOriginal
    except Exception:
        return ""


def intake(src, dest, tile=420, per=12):
    files = sorted((f for f in Path(src).iterdir() if f.suffix.lower() in EXTS), key=lambda f: (capture_time(f), f.name))
    for k in range(0, len(files), per):
        sheet = Image.new("RGB", (4 * tile, 3 * tile), (20, 20, 20))
        d = ImageDraw.Draw(sheet)
        for i, f in enumerate(files[k:k + per]):
            im = ImageOps.exif_transpose(Image.open(f))
            im.draft("RGB", (tile * 2, tile * 2))
            im.thumbnail((tile - 6, tile - 6))
            x, y = (i % 4) * tile, (i // 4) * tile
            sheet.paste(im, (x + 3, y + 3))
            d.rectangle([x + 3, y + 3, x + 150, y + 40], fill=(0, 0, 0))
            d.text((x + 8, y + 6), f.stem[-4:], fill=(255, 230, 0), font=FONT)
        out = Path(dest) / f"intake{k // per + 1}.jpg"
        sheet.save(out, quality=80)
        print(out)


def review(src, dest, tw=225, th=300, rows=5):
    items = sorted(d for d in Path(src).iterdir() if d.is_dir())
    for n in range(0, len(items), rows):
        chunk = items[n:n + rows]
        sheet = Image.new("RGB", (8 * tw, len(chunk) * (th + 30)), (20, 20, 20))
        d = ImageDraw.Draw(sheet)
        for r, item in enumerate(chunk):
            d.text((6, r * (th + 30) + 2), item.name, fill=(255, 230, 0), font=ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20))
            for c, f in enumerate(sorted(item.glob("0*.jpg"))[:8]):
                im = Image.open(f)
                im.thumbnail((tw - 4, th - 4))
                sheet.paste(im, (c * tw + 2, r * (th + 30) + 30))
        out = Path(dest) / f"review{n // rows + 1}.jpg"
        sheet.save(out, quality=82)
        print(out)


if __name__ == "__main__":
    mode, src, dest = sys.argv[1:4]
    Path(dest).mkdir(parents=True, exist_ok=True)
    {"intake": intake, "review": review}[mode](src, dest)
