#!/usr/bin/env python3
"""OpenAI image edits with pixel-level guarantees. Needs OPENAI_API_KEY in .env.

  remove   Inpaint one object (bright, e.g. white stool legs). Only pixels inside the object
           mask are taken from the model; the rest is copied from the original and verified
           byte-identical.
  enhance  Background cleanup with the garment locked (see enhance_locked). This is what
           `process.py --ai` runs on every full-garment shot; the command here is for one-offs.

Usage:
  .venv/bin/python tools/ai_edit.py remove  <photo> <out.png> --box x0,y0,x1,y1 [--crop x0,y0,x1,y1]
  .venv/bin/python tools/ai_edit.py enhance <photo> <out.png>
"""
import argparse
import base64
import io
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
MODEL = "gpt-image-2.5-sunburst"


def load(path):
    return np.array(ImageOps.exif_transpose(Image.open(path)).convert("RGB"))


def png_bytes(arr, name):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    buf.seek(0)
    buf.name = name
    return buf


def call_edit(rgb, prompt, mask=None, quality="high"):
    """rgb: HxWx3 uint8, dims divisible by 16. mask: HxW bool, True = region to edit."""
    h, w = rgb.shape[:2]
    kw = dict(model=MODEL, image=png_bytes(rgb, "image.png"), prompt=prompt,
              size=f"{w}x{h}", quality=quality, extra_body={"complexity": "low"})
    if mask is not None:
        rgba = np.dstack([rgb, np.where(mask, 0, 255).astype(np.uint8)])  # transparent = edit
        kw["mask"] = png_bytes(rgba, "mask.png")
    from openai import BadRequestError
    for cx in ("medium", None):  # lowest complexity the model accepts ("low" is rejected)
        kw["extra_body"] = {"complexity": cx} if cx else {}
        for f in (kw["image"], kw.get("mask")):
            if f is not None:
                f.seek(0)
        try:
            r = OpenAI().images.edit(**kw)
            print(f"complexity={cx or 'default'}", file=sys.stderr)
            break
        except BadRequestError as e:
            if "omplexity" not in str(e) or cx is None:
                raise
    out = np.array(Image.open(io.BytesIO(base64.b64decode(r.data[0].b64_json))).convert("RGB"))
    if out.shape[:2] != (h, w):
        out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LANCZOS4)
    usage = getattr(r, "usage", None)
    return out, (usage.model_dump() if usage else None)


def parse_box(s):
    return [int(v) for v in s.split(",")]


# ---------- remove ----------

def object_mask(rgb, box, grow=48):
    """Bright, low-saturation pixels inside box (white tubing, grey feet on a wood floor)."""
    x0, y0, x1, y1 = box
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    s, v = hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    cand = (v > 105) & (s < 70)
    m = np.zeros(rgb.shape[:2], np.uint8)
    m[y0:y1, x0:x1] = cand[y0:y1, x0:x1]
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] > 1500:
            keep[lab == i] = 1
    keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow * 2 + 1,) * 2))
    keep[:y0], keep[y1:], keep[:, :x0], keep[:, x1:] = 0, 0, 0, 0
    return keep.astype(bool)


def cmd_remove(a):
    src = load(a.photo)
    H, W = src.shape[:2]
    box = parse_box(a.box)
    mask = object_mask(src, box)
    if not mask.any():
        sys.exit("no object found in box")
    cx0, cy0, cx1, cy1 = parse_box(a.crop) if a.crop else (0, 0, W, H)
    assert (cx1 - cx0) % 16 == 0 and (cy1 - cy0) % 16 == 0, "crop dims must be divisible by 16"
    assert not mask[:cy0].any() and not mask[cy1:].any() and not mask[:, :cx0].any() and not mask[:, cx1:].any()
    crop, cmask = src[cy0:cy1, cx0:cx1], mask[cy0:cy1, cx0:cx1]
    gen, usage = call_edit(crop, a.prompt, cmask)

    # tone-match the generated floor to the original using a ring just outside the mask
    ring = cv2.dilate(cmask.astype(np.uint8), np.ones((61, 61), np.uint8)).astype(bool) & ~cmask
    gen = np.clip(gen.astype(np.float32) + (crop[ring].mean(0) - gen[ring].mean(0)), 0, 255)

    # feather inward only, so alpha is exactly 0 everywhere outside the mask
    dist = cv2.distanceTransform(cmask.astype(np.uint8), cv2.DIST_L2, 5)
    alpha = np.clip(dist / 14.0, 0, 1)[..., None]
    blended = (gen * alpha + crop.astype(np.float32) * (1 - alpha)).round().astype(np.uint8)
    out = src.copy()
    out[cy0:cy1, cx0:cx1] = blended

    changed = (out != src).any(-1)
    report = {
        "model": MODEL, "usage": usage,
        "mask_pixels": int(mask.sum()), "mask_pct_of_image": round(100 * mask.mean(), 3),
        "changed_pixels": int(changed.sum()),
        "changed_outside_mask": int((changed & ~mask).sum()),
        "mask_bbox": [int(v) for v in cv2.boundingRect(mask.astype(np.uint8))],
    }
    Image.fromarray(out).save(a.out)
    Image.fromarray((mask * 255).astype(np.uint8)).save(Path(a.out).with_suffix(".mask.png"))
    Path(a.out).with_suffix(".json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if report["changed_outside_mask"]:
        sys.exit("FAIL: pixels changed outside the mask")
    print("PASS: 0 pixels changed outside the mask")


# ---------- enhance ----------

def garment_mask(rgb):
    from rembg import new_session, remove
    m = remove(Image.fromarray(rgb), session=new_session("isnet-general-use"), only_mask=True)
    m = (np.array(m) > 127).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n > 1:
        m = (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    return m.astype(bool)


def garment_check(orig, new, mask):
    """Compare garment region. Tone is normalised first so a global brightness/contrast
    change does not count as an edit; structure, colour and detail changes do."""
    from skimage.metrics import structural_similarity as ssim
    inner = cv2.erode(mask.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    lo, ln = cv2.cvtColor(orig, cv2.COLOR_RGB2LAB).astype(np.float32), cv2.cvtColor(new, cv2.COLOR_RGB2LAB).astype(np.float32)
    lo[..., 0] *= 100 / 255; ln[..., 0] *= 100 / 255
    lo[..., 1:] -= 128; ln[..., 1:] -= 128
    # geometry: sub-pixel shift between the two (phase correlation on luminance)
    (dx, dy), _ = cv2.phaseCorrelate(lo[..., 0] * mask, ln[..., 0] * mask)
    # tone-normalise new L to original L inside the garment (linear fit)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        A = np.polyfit(ln[..., 0][inner], lo[..., 0][inner], 1)
    Ln = (ln[..., 0] * A[0] + A[1]).astype(np.float32)
    _, smap = ssim(lo[..., 0], Ln, data_range=100, full=True, gaussian_weights=True, sigma=2.0)
    # edges: do seams, snaps, logo outlines sit in the same places?
    eo = cv2.Canny(cv2.GaussianBlur(orig, (0, 0), 1.5), 40, 100) > 0
    en = cv2.Canny(cv2.GaussianBlur(new, (0, 0), 1.5), 40, 100) > 0
    k = np.ones((7, 7), np.uint8)
    eo_d, en_d = cv2.dilate(eo.astype(np.uint8), k).astype(bool), cv2.dilate(en.astype(np.uint8), k).astype(bool)
    recall = (eo & en_d & inner).sum() / max(1, (eo & inner).sum())
    added = (en & ~eo_d & inner).sum() / max(1, (en & inner).sum())
    # worst local region (64px tiles) by SSIM
    tiles = []
    for y in range(0, mask.shape[0] - 64, 64):
        for x in range(0, mask.shape[1] - 64, 64):
            if inner[y:y + 64, x:x + 64].mean() > 0.9:
                tiles.append((float(smap[y:y + 64, x:x + 64].mean()), x, y))
    tiles.sort()
    return {
        "shift_px": [round(dx, 2), round(dy, 2)],
        "ssim_tone_normalised": round(float(smap[inner].mean()), 4),
        "worst_tiles_ssim_x_y": [(round(s, 3), x, y) for s, x, y in tiles[:5]],
        "orig_edges_still_present": round(float(recall), 4),
        "new_edges_not_in_orig": round(float(added), 4),
        "L_gain_offset": [round(float(A[0]), 3), round(float(A[1]), 2)],
        "mean_dL": round(float((ln[..., 0] - lo[..., 0])[inner].mean()), 2),
        "mean_da_db": [round(float((ln[..., i] - lo[..., i])[inner].mean()), 2) for i in (1, 2)],
        "detail_ratio_laplacian_var": round(float(cv2.Laplacian(Ln, cv2.CV_32F)[inner].var() / cv2.Laplacian(lo[..., 0], cv2.CV_32F)[inner].var()), 3),
    }


BG_PROMPT = ("This is a resale listing photo of a garment lying on a wood floor. Clean up the background only: "
             "remove any clutter on the floor around the garment (bags, chair or stool legs, wheels, cables, feet, shadows "
             "of people) and fill those areas with the same wood floor, continuing the planks and grain. Even out the "
             "lighting on the floor. Keep the garment exactly as it is: same position, outline, wrinkles, colour, texture, "
             "labels and flaws. Keep the framing, the floor's colour and the white balance. Do not add anything.")


HALO_MAX = 0.03


def garment_verdict(c):
    fails = [n for n, bad in {
        "structure (ssim < 0.97)": c["ssim_tone_normalised"] < 0.97,
        "new detail (edges > 3%)": c["new_edges_not_in_orig"] > 0.03,
        "lost detail (edges < 95%)": c["orig_edges_still_present"] < 0.95,
        "texture (detail ratio outside 0.9-1.1)": not 0.9 <= c["detail_ratio_laplacian_var"] <= 1.1,
        "colour (|da| or |db| > 1.5)": max(abs(v) for v in c["mean_da_db"]) > 1.5,
        "geometry (shift > 0.5px)": max(abs(v) for v in c["shift_px"]) > 0.5,
    }.items() if bad]
    return "unchanged" if not fails else "edited: " + "; ".join(fails)


def enhance_locked(base, mask, segment, cache=None, prompt=BG_PROMPT):
    """AI background cleanup with the garment locked.

    base     HxWx3 uint8, already cropped / white-balanced / toned. Dims divisible by 16.
    mask     HxW float 0-1 garment mask for base.
    segment  fn(rgb) -> HxW float mask, used to re-segment the AI output.
    Returns (image, report). The image is base when any check fails.

    The model redraws the whole frame, garment included, so its garment pixels are never used:
    the garment (union of the base and AI outlines, grown 7px) is copied from base. Checks:
      garment_pixels_changed == 0     every pixel inside the base garment mask is byte-identical
      halo_pct <= 3                   the model's redrawn garment does not stick out from under the
                                      original (measured in the 25px of floor around the locked area)
      floor_shift_px <= 2             the planks did not move
      floor_dE <= 3                   floor colour matches base after chroma matching
    """
    import hashlib
    h, w = base.shape[:2]
    if w % 16 or h % 16:
        return base, {"verdict": f"SKIP: {w}x{h} not divisible by 16"}
    gen, usage, cached = None, None, False
    if cache:
        cache = Path(f"{cache}.{hashlib.sha1(base.tobytes() + prompt.encode()).hexdigest()[:12]}.png")
        if cache.exists():
            gen, cached = np.array(Image.open(cache).convert("RGB")), True
    if gen is None:
        gen, usage = call_edit(base, prompt)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(gen).save(cache)

    # Segment base and the AI output the same way, so the outline comparison measures what the model
    # did and not a difference between two segmentation passes. The crop-time mask is added to the lock.
    sb, m1 = segment(base) > 0.5, segment(gen) > 0.5
    iou = float((sb & m1).sum() / max(1, (sb | m1).sum()))
    m0 = (mask > 0.5) | sb
    union = (m0 | m1).astype(np.uint8)
    lock = cv2.dilate(union, np.ones((15, 15), np.uint8))
    floor = cv2.dilate(union, np.ones((61, 61), np.uint8)) == 0

    def lab(x):
        return cv2.cvtColor(x, cv2.COLOR_RGB2LAB).astype(np.float32)
    lb, lg = lab(base), lab(gen)
    raw_dE = None
    if floor.sum() > 2000:
        # the model tends to warm and brighten the floor; pull its median back to base so the
        # white balance set earlier is what ships
        d = np.median(lb[floor], 0) - np.median(lg[floor], 0)
        raw_dE = float(np.linalg.norm(d * [100 / 255, 1, 1]))
        lg += d
        gen_m = cv2.cvtColor(np.clip(lg, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    else:
        gen_m = gen
    alpha = cv2.GaussianBlur(lock.astype(np.float32), (0, 0), 1.5)[..., None]
    final = np.clip(base * alpha + gen_m.astype(np.float32) * (1 - alpha), 0, 255).round().astype(np.uint8)

    lf = lab(final)
    floor_dE = float(np.linalg.norm((np.median(lf[floor], 0) - np.median(lb[floor], 0)) * [100 / 255, 1, 1])) if floor.sum() > 2000 else 0.0
    (dx, dy), _ = cv2.phaseCorrelate(lb[..., 0] * floor, lf[..., 0] * floor)
    # Halo: in the 25px of floor just outside the locked garment the output is the model's. If the model
    # redrew the garment bigger or shifted, its version pokes out here: pixels that were wood floor in
    # base and are no longer wood-toned. Lighting changes on the floor keep the wood hue and don't count.
    ring = (cv2.dilate(lock, np.ones((51, 51), np.uint8)) > 0) & (lock == 0)

    def is_floor(x):  # wood-toned: orange hue with some saturation, any brightness above near-black
        hsv = cv2.cvtColor(x, cv2.COLOR_RGB2HSV)
        return (hsv[..., 0] >= 3) & (hsv[..., 0] <= 30) & (hsv[..., 1] > 30) & (hsv[..., 2] > 15)
    was_floor = ring & is_floor(base)
    halo = float((~is_floor(final))[was_floor].mean()) if was_floor.sum() > 500 else 0.0
    changed = (final != base).any(-1)
    rep = {
        "model": MODEL, "cached": cached, "usage": usage,
        "garment_pct": round(100 * float(m0.mean()), 1),
        "garment_pixels_changed": int(changed[m0].sum()),
        "halo_pct": round(100 * halo, 2),
        "floor_shift_px": [round(dx, 2), round(dy, 2)],
        "floor_dE": round(floor_dE, 2),
        "ai_floor_dE_before_match": None if raw_dE is None else round(raw_dE, 2),
        "segmentation_iou": round(iou, 4),
        "background_pixels_changed_pct": round(100 * float(changed[~m0].mean()), 1),
        "ai_garment_before_lock": garment_verdict(garment_check(base, gen, m0)),
    }
    fails = [n for n, bad in {
        "garment pixels changed": rep["garment_pixels_changed"] > 0,
        f"halo around garment ({rep['halo_pct']}% of the edge band)": halo > HALO_MAX,
        f"floor moved ({dx:.1f},{dy:.1f}px)": max(abs(dx), abs(dy)) > 2,
        f"floor colour (dE {floor_dE:.1f})": floor_dE > 3,
    }.items() if bad]
    rep["verdict"] = "PASS" if not fails else "FAIL: " + "; ".join(fails)
    return (final if not fails else base), rep


def cmd_enhance(a):
    src = load(a.photo)
    H, W = src.shape[:2]
    w = a.width - a.width % 16
    h = int(round(w * H / W / 16)) * 16
    base = cv2.resize(src, (w, h), interpolation=cv2.INTER_AREA)
    out = Path(a.out)
    final, rep = enhance_locked(base, garment_mask(base).astype(np.float32),
                                lambda im: garment_mask(im).astype(np.float32), cache=out.with_suffix(""))
    Image.fromarray(final).save(out)
    out.with_suffix(".json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=2))
    if rep["verdict"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("remove")
    r.add_argument("photo"); r.add_argument("out")
    r.add_argument("--box", required=True, help="x0,y0,x1,y1 search area for the object, full-res px")
    r.add_argument("--crop", help="x0,y0,x1,y1 region sent to the model (dims divisible by 16)")
    r.add_argument("--prompt", default="Remove the white metal stool legs and grey rubber feet, including any shadow they cast. Fill the area with the same dark wood plank floor, continuing the existing planks, grain and seams. Change nothing else.")
    r.set_defaults(fn=cmd_remove)
    e = sub.add_parser("enhance")
    e.add_argument("photo"); e.add_argument("out")
    e.add_argument("--width", type=int, default=1200)
    e.set_defaults(fn=cmd_enhance)
    a = p.parse_args()
    a.fn(a)
