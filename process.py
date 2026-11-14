#!/usr/bin/env python3
"""Batch-clean listing photos.

Layout:
  photos/raw/<item folder>/*.jpg|heic|png   ->   photos/out/<item folder>/01.jpg ...
                                                 photos/out/<item folder>/_sheet.jpg (review contact sheet)

Per photo:
  1. EXIF-rotate, HEIC -> RGB
  2. Segment subject (rembg / isnet) -> bounding box
  3. Crop to target aspect around the subject with margin (pads with sampled bg if needed)
  4. White balance anchored on the wood floor (one global gain per photo), tone to the reference look, sharpen
  5. Resize, save JPEG with all metadata stripped (no GPS leaking into listings)
  5b. Picks with "dewrinkle": true get wrinkle shading turned down (tools/dewrinkle.py, nothing generated)
  6. --ai: background cleanup on full-garment shots via tools/ai_edit.py. The garment is copied back from
     step 5 and verified pixel-identical; a shot that fails a check ships without the AI pass.
     Results land in photos/out/<item>/_verify.json and _ai_compare.jpg.

Usage:
  .venv/bin/python process.py                       # all items, 4:5
  .venv/bin/python process.py --aspect 1:1 --item "Burberry Trench"
  .venv/bin/python process.py --ai --item "Acne Studios Puffer"
  .venv/bin/python process.py --white-bg            # replace background with clean off-white
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from rembg import new_session, remove

register_heif_opener()

ROOT = Path(__file__).parent
RAW = ROOT / "photos" / "raw"
OUT = ROOT / "photos" / "out"
PICKS = ROOT / "picks.json"
AI_CACHE = ROOT / "photos" / "ai-cache"
FULL_ANGLES = ("front", "back", "side", "inside")
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}


def load(path, rotate=0):
    img = ImageOps.exif_transpose(Image.open(path))
    if rotate:
        img = img.rotate(rotate, expand=True)
    return np.array(img.convert("RGB"))


def subject_mask(rgb, session):
    # Segment on a downscaled copy for speed, upscale the mask back
    h, w = rgb.shape[:2]
    scale = min(1.0, 1024 / max(h, w))
    small = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    m = remove(Image.fromarray(small), session=session, only_mask=True)
    m = cv2.resize(np.array(m), (w, h), interpolation=cv2.INTER_LINEAR)
    return m.astype(np.float32) / 255.0


def subject_bbox(mask):
    ys, xs = np.where(mask > 0.5)
    if len(xs) == 0:
        h, w = mask.shape
        return 0, 0, w, h
    # Percentiles instead of min/max so stray specks don't blow up the box
    return (int(np.percentile(xs, 0.2)), int(np.percentile(ys, 0.2)),
            int(np.percentile(xs, 99.8)) + 1, int(np.percentile(ys, 99.8)) + 1)


def extend_floor(rgb, mask, pt, pb, pl, pr):
    """Grow the canvas by mirroring the surrounding floor, so a garment that fills a landscape frame can sit
    whole in a portrait crop. Any garment that gets mirrored into the new area is painted over with floor,
    and the seams get a light blur so the join doesn't read."""
    h, w = rgb.shape[:2]
    big = cv2.copyMakeBorder(rgb, pt, pb, pl, pr, cv2.BORDER_REFLECT_101)
    mirrored = cv2.copyMakeBorder((mask > 0.3).astype(np.uint8), pt, pb, pl, pr, cv2.BORDER_REFLECT_101)
    new_area = np.ones(big.shape[:2], np.uint8)
    new_area[pt:pt + h, pl:pl + w] = 0
    # Wide dilation: the garment's cast shadow sits outside the mask and would otherwise mirror in as a dark smear
    hole = cv2.dilate(mirrored & new_area, np.ones((141, 141), np.uint8)) & new_area
    if hole.any():
        s = 0.25  # inpaint at quarter res; big holes are slow at full size
        small = cv2.resize(big, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        hs = cv2.resize(hole, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
        filled = cv2.resize(cv2.inpaint(small, hs, 9, cv2.INPAINT_TELEA), (big.shape[1], big.shape[0]))
        big[hole > 0] = filled[hole > 0]
    seam = np.zeros(big.shape[:2], np.float32)
    if pt: seam[pt - 12:pt + 12] = 1
    if pb: seam[pt + h - 12:pt + h + 12] = 1
    if pl: seam[:, pl - 12:pl + 12] = 1
    if pr: seam[:, pl + w - 12:pl + w + 12] = 1
    seam = cv2.GaussianBlur(seam, (0, 0), 8)[..., None]
    big = (big * (1 - seam) + cv2.GaussianBlur(big, (0, 0), 5) * seam).astype(np.uint8)
    big_mask = cv2.copyMakeBorder(mask, pt, pb, pl, pr, cv2.BORDER_CONSTANT, value=0)
    return big, big_mask


def crop_to_aspect(rgb, mask, bbox, aspect, margin, extend=False):
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    pad = margin * max(bw, bh)
    cw, ch = bw + 2 * pad, bh + 2 * pad
    if cw / ch > aspect:
        ch = cw / aspect
    else:
        cw = ch * aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    # Window around the bare garment (no margin) at this aspect; only extend if *that* doesn't fit, i.e. the
    # garment itself would be clipped. Shots that only lose margin keep the plain shrink-to-fit crop.
    cw0, ch0 = (bw, bw / aspect) if bw / max(bh, 1) > aspect else (bh * aspect, bh)
    if extend and (cw0 > w or ch0 > h):
        # Full-garment shot that can't fit at this aspect (e.g. a jacket shot sideways, rotated upright into a
        # landscape frame): grow the floor instead of clipping sleeves
        ex, ey = max(0, int(np.ceil(cw - w))), max(0, int(np.ceil(ch - h)))
        pl, pt = ex // 2, ey // 2
        rgb, mask = extend_floor(rgb, mask, pt, ey - pt, pl, ex - pl)
        h, w = rgb.shape[:2]
        cx, cy = cx + pl, cy + pt
    # Otherwise never pad: if the window is bigger than the frame, shrink it (losing margin first) so it fits
    fit = min(1.0, w / cw, h / ch)
    cw, ch = cw * fit, ch * fit
    left, top = int(round(cx - cw / 2)), int(round(cy - ch / 2))
    cw, ch = int(round(cw)), int(round(ch))

    # Slide the window inside the frame where possible; pad only if the window is bigger than the frame
    if cw <= w:
        left = min(max(left, 0), w - cw)
    if ch <= h:
        top = min(max(top, 0), h - ch)

    pl, pt = max(0, -left), max(0, -top)
    pr, pb = max(0, left + cw - w), max(0, top + ch - h)
    if pl or pt or pr or pb:
        bg = background_color(rgb, mask)
        rgb = cv2.copyMakeBorder(rgb, pt, pb, pl, pr, cv2.BORDER_CONSTANT, value=bg.tolist())
        mask = cv2.copyMakeBorder(mask, pt, pb, pl, pr, cv2.BORDER_CONSTANT, value=0)
        left += pl
        top += pt
    return rgb[top:top + ch, left:left + cw], mask[top:top + ch, left:left + cw]


def background_color(rgb, mask):
    bg = rgb[mask < 0.1]
    return np.median(bg, axis=0).astype(np.uint8) if len(bg) > 500 else np.array([240, 240, 238], np.uint8)


# White balance. The iPhone compensates for the warm floor, so whites come out green-cyan and the
# cast changes shot to shot as the room light changes. The floor itself is the one constant in every
# frame, so it is the reference: each photo gets one global R/G/B gain (in linear light) that puts the
# floor at the colour it has when a known white reads neutral.
# FLOOR_TARGET = linear (R/G, B/G) of the oak floor, measured on 6 shots (IMG_7110, 7139-41, 7146, 7171)
# after neutralising the white stool legs in frame. Different floor -> remeasure with --wb-calibrate.
FLOOR_TARGET = (1.57, 0.51)
LUMA = np.array([0.2126, 0.7152, 0.0722])


def to_linear(rgb):
    x = rgb.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def to_srgb(lin):
    x = np.clip(lin, 0, 1)
    return np.clip(np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055) * 255 + 0.5, 0, 255).astype(np.uint8)


def wood_pixels(rgb, mask=None):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    wood = (h >= 3) & (h <= 30) & (s > 40) & (v > 40)
    return wood & (mask < 0.1) if mask is not None else wood


def floor_gains(rgb, mask=None, min_frac=0.08, strength=1.0):
    """Per-channel linear gains that move this frame's floor to FLOOR_TARGET, or None if too little floor shows.
    Luminance of the floor is preserved, so this changes colour only."""
    wood = wood_pixels(rgb, mask)
    if wood.mean() < min_frac:
        return None
    f = np.median(to_linear(rgb)[wood], axis=0)
    g = np.array([FLOOR_TARGET[0] / (f[0] / f[1]), 1.0, FLOOR_TARGET[1] / (f[2] / f[1])])
    g = np.clip(1 + (g - 1) * strength, 0.7, 1.4)
    return g * (LUMA @ f) / (LUMA @ (f * g))


def label_gains(rgb, min_frac=0.05, strength=0.8):
    """Tag shots: the printed label is white, so neutralise on it. Only used when the pick's angle says
    "tag" or "label" - a cream garment would otherwise be read as a white label and turned grey."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    white = (hsv[..., 2] > 185) & (hsv[..., 1] < 45)
    if white.mean() < min_frac:
        return None
    w = np.median(to_linear(rgb)[white], axis=0)
    g = np.clip(1 + (np.array([w[1] / w[0], 1.0, w[1] / w[2]]) - 1) * strength, 0.7, 1.4)
    return g * (LUMA @ w) / (LUMA @ (w * g))


def apply_gains(rgb, gains):
    return to_srgb(to_linear(rgb) * gains.astype(np.float32))


def wb_calibrate(paths):
    """Print the floor's (R/G, B/G) after neutralising a white object in each frame (stool legs, paper)."""
    vals = []
    for p in paths:
        rgb = load(p)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        white = (hsv[..., 2] > 175) & (hsv[..., 1] < 45)
        wood = wood_pixels(rgb)
        if white.mean() < 0.003 or wood.mean() < 0.08:
            print(f"  {Path(p).name}: skipped (white {white.mean():.3f}, floor {wood.mean():.2f})")
            continue
        lin = to_linear(rgb)
        f, w = np.median(lin[wood], 0), np.median(lin[white], 0)
        v = (f[0] / f[1] / (w[0] / w[1]), f[2] / f[1] / (w[2] / w[1]))
        vals.append(v)
        print(f"  {Path(p).name}: R/G {v[0]:.3f}  B/G {v[1]:.3f}")
    if vals:
        m = np.median(np.array(vals), 0)
        print(f"FLOOR_TARGET = ({m[0]:.2f}, {m[1]:.2f})   # median of {len(vals)} shots")


def auto_levels(rgb, lo=0.5, hi=99.5):
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    L = lab[..., 0].astype(np.float32)
    a, b = np.percentile(L, lo), np.percentile(L, hi)
    if b - a < 30:  # flat image, don't stretch noise
        return rgb
    # Partial stretch with a floor/ceiling so dark fabrics keep texture instead of going pure black
    a, b = min(a, 18), max(b, 235)
    L = (L - a) * 240.0 / (b - a) + 8
    # Gentle S-curve for contrast
    x = np.clip(L / 255.0, 0, 1)
    x = 0.8 * x + 0.2 * x * x * (3 - 2 * x)
    lab[..., 0] = np.clip(x * 255, 0, 255).astype(np.uint8)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


def hsl_adjust(rgb, mask, vibrance, bg_desat):
    hls = cv2.cvtColor(rgb, cv2.COLOR_RGB2HLS).astype(np.float32)
    s = hls[..., 2] / 255.0
    # Vibrance: boost low-saturation pixels more than already-saturated ones, on the subject only
    boost = 1 + vibrance * (1 - s) * mask
    # Mute the background a bit so the garment pops
    boost *= 1 - bg_desat * (1 - mask)
    hls[..., 2] = np.clip(s * boost, 0, 1) * 255
    return cv2.cvtColor(hls.astype(np.uint8), cv2.COLOR_HLS2RGB)


def shadows_lift(rgb, amount):
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab[..., 0] / 255.0
    L = L + amount * (1 - L) ** 3 * L * 4
    lab[..., 0] = np.clip(L * 255, 0, 255)
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)


# Target look, measured from a reference listing photo (kept locally at tools/reference-look.png, not in git): garment highlights roll off
# around L*84 instead of clipping, bright garments sit near L*73, and the wood floor stays rich and warm
# (HSV sat ~105, b* ~+16) rather than grayed out. L* is 0-100.
LOOK = {"subj_mid": 74.0, "subj_hi": 85.0, "knee": 68.0, "bg_sat": 105.0, "bg_warm": 16.0}


def reference_look(rgb, mask, full=True, look=LOOK):
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab[..., 0] / 2.55
    subj = mask > 0.5
    if subj.sum() < 1000:
        subj = np.ones_like(subj)
    mid, hi = np.percentile(L[subj], 50), np.percentile(L[subj], 98)

    # Exposure: pull bright garments down to the target midtone with a gamma (never brighten dark ones).
    # The floor only takes a third of the change so it doesn't sink into murk behind a light garment.
    if mid > look["subj_mid"]:
        g = np.log(look["subj_mid"] / 100) / np.log(mid / 100)
        Lg = 100 * np.power(np.clip(L / 100, 0, 1), g)
        ws = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 8)
        L = Lg * (0.33 + 0.67 * ws) + L * (0.67 - 0.67 * ws)
        hi = 100 * (hi / 100) ** g

    # Highlights: smooth shoulder above the knee so the garment's brightest areas land near subj_hi, not white
    d, t = hi - look["knee"], look["subj_hi"] - look["knee"]
    if d > t > 0:
        c = d * t / (d - t)
        over = L > look["knee"]
        x = L[over] - look["knee"]
        L[over] = look["knee"] + x / (1 + x / c)
    lab[..., 0] = np.clip(L * 2.55, 0, 255)

    # Floor: on wood (orange hue) give back the richness and warmth that flat phone light loses.
    # Measure saturation after the exposure change, since darkening alone raises HSV saturation.
    # Full-garment shots only: on close-ups the mask can't separate fabric from floor, and the boost
    # would tint the garment itself.
    bg = mask < 0.1
    if full and bg.sum() > 2000:
        hsv = cv2.cvtColor(cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB), cv2.COLOR_RGB2HSV)
        hue, sat = np.median(hsv[..., 0][bg]), np.median(hsv[..., 1][bg])
        if 5 <= hue <= 25 and sat > 30:
            # Only pixels that are themselves wood-toned (orange hue, some saturation), so walls, tags and
            # anything the mask missed keep their color
            px_hue, px_sat = hsv[..., 0].astype(np.float32), hsv[..., 1].astype(np.float32)
            wood = ((px_hue >= 3) & (px_hue <= 28) & (px_sat > 25)).astype(np.float32)
            w = cv2.GaussianBlur((1 - mask).astype(np.float32) * wood, (0, 0), 3)
            gain = np.clip(look["bg_sat"] / max(sat, 1), 1.0, 1.6)
            a, b = lab[..., 1] - 128, lab[..., 2] - 128
            a *= 1 + (gain - 1) * w
            b *= 1 + (gain - 1) * w
            warm = np.clip(look["bg_warm"] - np.median(b[bg]), 0, 6)
            b += warm * w
            lab[..., 1], lab[..., 2] = a + 128, b + 128

    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def sharpen(rgb, amount=0.6, radius=1.2):
    blur = cv2.GaussianBlur(rgb, (0, 0), radius)
    return cv2.addWeighted(rgb, 1 + amount, blur, -amount, 0)


def replace_bg(rgb, mask, color=(246, 245, 242)):
    m = cv2.GaussianBlur(mask, (0, 0), 1.5)[..., None]
    bg = np.empty_like(rgb, dtype=np.float32)
    bg[:] = color
    return (rgb.astype(np.float32) * m + bg * (1 - m)).astype(np.uint8)


def process(path, session, args, rotate=0, full=True, gains=None, tag=False, crop=None):
    """Inspect + crop first, then colour. Returns (rgb, mask, gains): mask is the garment mask at output
    size, gains are the white-balance gains this frame used (None if it had no floor to measure)."""
    rgb = load(path, rotate)
    if crop:
        # Per-pick pre-crop as fractions of the rotated frame (x0, y0, x1, y1), for cutting clutter out of a close-up
        h, w = rgb.shape[:2]
        rgb = np.ascontiguousarray(rgb[int(crop[1] * h):int(crop[3] * h), int(crop[0] * w):int(crop[2] * w)])
    mask = subject_mask(rgb, session)
    # Close-ups (tags, details) fill the frame already; subject-cropping them would clip text, so just trim to aspect
    bbox = subject_bbox(mask)
    if not full:
        # Largest window that fits, centered on the detail rather than the frame
        h, w = rgb.shape[:2]
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        bbox = (cx - w, cy - h, cx + w, cy + h)
    rgb, mask = crop_to_aspect(rgb, mask, bbox, args.aspect, args.margin if full else 0, extend=full)
    if not args.no_color:
        own_label = label_gains(rgb, strength=0.8 * args.wb) if tag and not full else None
        if full:
            gains = floor_gains(rgb, mask, strength=args.wb)
        elif own_label is not None:
            gains = own_label
        else:
            # Close-up: use its own floor when a lot of it shows (it may be lit differently from the full
            # shots), otherwise keep the gains borrowed from the nearest full shot. The bar is high because
            # the garment mask is unreliable on close-ups and tan linings or warm glare read as wood.
            own = floor_gains(rgb, None, min_frac=0.35, strength=args.wb)
            if own is not None:
                gains = own
        if gains is not None:
            rgb = apply_gains(rgb, gains)
        if args.look == "legacy":
            rgb = auto_levels(rgb)
            rgb = shadows_lift(rgb, args.shadows)
            rgb = hsl_adjust(rgb, mask, args.vibrance, args.bg_desat)
        else:
            rgb = reference_look(rgb, mask, full)
            rgb = hsl_adjust(rgb, mask, args.vibrance, 0)
    if args.white_bg:
        rgb = replace_bg(rgb, mask)
    h, w = rgb.shape[:2]
    if max(h, w) > args.size:
        s = args.size / max(h, w)
        # multiples of 16 so the frame can go to the image model as-is
        size = (int(round(w * s / 16)) * 16, int(round(h * s / 16)) * 16)
        rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, size, interpolation=cv2.INTER_LINEAR)
    return sharpen(rgb), mask, gains


def img_number(path):
    digits = "".join(c for c in Path(path).stem if c.isdigit())
    return int(digits) if digits else 0


def contact_sheet(paths, dest, thumb=360):
    ims = [Image.open(p) for p in paths]
    for im in ims:
        im.thumbnail((thumb, thumb))
    cols = min(4, len(ims))
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb, rows * thumb), (30, 30, 30))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * thumb, (i // cols) * thumb))
    sheet.save(dest, quality=85)


def ai_compare(pairs, dest, th=800):
    """Before | after per AI-processed shot, labelled with the verdict."""
    from PIL import ImageDraw
    tw = int(th * pairs[0][0].shape[1] / pairs[0][0].shape[0])
    sheet = Image.new("RGB", (len(pairs) * (2 * tw + 30), th + 40), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for k, (base, final, name, verdict) in enumerate(pairs):
        x = k * (2 * tw + 30)
        sheet.paste(Image.fromarray(base).resize((tw, th)), (x, 40))
        sheet.paste(Image.fromarray(final).resize((tw, th)), (x + tw + 4, 40))
        d.text((x + 4, 12), f"{name}  before | after   {verdict}"[:120], fill=(255, 230, 0) if verdict == "PASS" else (255, 90, 90))
    sheet.save(dest, quality=88)


def parse_aspect(s):
    a, b = s.split(":")
    return float(a) / float(b)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--aspect", type=parse_aspect, default="3:4")
    p.add_argument("--margin", type=float, default=0.06, help="padding around subject, fraction of subject size")
    p.add_argument("--size", type=int, default=1600, help="max long edge in px (1600 keeps a 9-photo set under the 10MB upload limit)")
    p.add_argument("--wb", type=float, default=1.0, help="white balance strength 0-1 (floor-anchored, see FLOOR_TARGET)")
    p.add_argument("--wb-calibrate", nargs="+", metavar="PHOTO", help="measure FLOOR_TARGET from shots with a white object and floor in frame, then exit")
    p.add_argument("--ai", action="store_true", help="AI background cleanup on full-garment shots, garment locked and verified (needs OPENAI_API_KEY in .env)")
    p.add_argument("--look", choices=["reference", "legacy"], default="reference",
                   help="reference = tone-matched to tools/reference-look.png; legacy = first-run auto levels")
    p.add_argument("--vibrance", type=float, default=0.06)
    p.add_argument("--bg-desat", type=float, default=0.25)
    p.add_argument("--shadows", type=float, default=0.10)
    p.add_argument("--white-bg", action="store_true", help="swap background for clean off-white")
    p.add_argument("--no-color", action="store_true", help="crop only")
    p.add_argument("--item", help="only process this item folder")
    p.add_argument("--model", default="isnet-general-use")
    args = p.parse_args()
    if args.wb_calibrate:
        return wb_calibrate(args.wb_calibrate)
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from dewrinkle import dewrinkle
    if args.ai:
        from ai_edit import enhance_locked

    session = new_session(args.model)
    items = sorted(d for d in RAW.iterdir() if d.is_dir() and (not args.item or d.name == args.item))
    loose = sorted(f for f in RAW.iterdir() if f.suffix.lower() in EXTS)
    if loose:
        print(f"! {len(loose)} photos sitting loose in photos/raw — put them in per-item folders")

    picks = json.loads(PICKS.read_text()) if PICKS.exists() else {}
    for item in items:
        if item.name in picks:
            shots = [(item / s["file"], s.get("rotate", 0), s["angle"].startswith(FULL_ANGLES), s["angle"], s) for s in picks[item.name]]
        else:
            shots = [(f, 0, True, "front", {}) for f in sorted(item.iterdir()) if f.suffix.lower() in EXTS]
        if not shots:
            continue
        dest = OUT / item.name
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.glob("*.jpg"):
            old.unlink()
        # Full-garment shots first: each measures its own floor, and close-ups borrow the gains of the
        # nearest full shot in capture order (same light, a minute apart)
        order = sorted(range(len(shots)), key=lambda i: not shots[i][2])
        done, full_gains, verify, pairs = {}, [], {}, []
        for i in order:
            f, rot, full, angle, pick = shots[i]
            is_tag = any(k in angle.lower() for k in ("tag", "label"))
            borrowed = None
            if not full and full_gains:
                borrowed = min(full_gains, key=lambda t: abs(t[0] - img_number(f)))[1]
            rgb, mask, gains = process(f, session, args, rot, full, borrowed, is_tag, pick.get("crop"))
            name = f"{i + 1:02d}.jpg"
            if full and gains is not None:
                full_gains.append((img_number(f), gains))
            wb = "none (no floor in frame)" if gains is None else ("own floor" if full else "borrowed from nearest full shot" if gains is borrowed else "white label" if is_tag else "own floor (close-up)") + " " + np.round(gains, 3).tolist().__str__()
            verify[name] = {"source": f.name, "white_balance": wb}
            if pick.get("dewrinkle") and not args.no_color:
                # Opt-in per pick. Runs before the AI pass, so the locked garment is the softened one.
                keep = 0.1 if pick["dewrinkle"] is True else float(pick["dewrinkle"])
                rgb, verify[name]["dewrinkle"] = dewrinkle(rgb, mask, keep=keep, protect=[tuple(b) for b in pick.get("protect", [])])
            if args.ai and full and not args.no_color:
                base = rgb
                rgb, rep = enhance_locked(base, mask, lambda im: subject_mask(im, session), cache=AI_CACHE / item.name / f.stem)
                verify[name]["ai"] = rep
                pairs.append((base, rgb, name, rep["verdict"]))
                print(f"  {item.name}/{name} AI: {rep['verdict']}")
            done[i] = rgb
        outs = []
        for i in range(len(shots)):
            o = dest / f"{i + 1:02d}.jpg"
            # Re-encode from array => no EXIF/GPS carried over
            Image.fromarray(done[i]).save(o, quality=92, optimize=True, progressive=True)
            outs.append(o)
            print(f"  {item.name}/{shots[i][0].name} -> {o.relative_to(ROOT)}")
        contact_sheet(outs, dest / "_sheet.jpg")
        (dest / "_verify.json").write_text(json.dumps(verify, indent=2))
        if pairs:
            ai_compare(pairs, dest / "_ai_compare.jpg")
    print("done")


if __name__ == "__main__":
    main()
