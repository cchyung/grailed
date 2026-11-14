#!/usr/bin/env python3
"""Soften wrinkles on a flat-laid garment without generating anything.

Wrinkles on a plain fabric are mid-scale shading: wider than the weave, narrower than the garment's
overall light falloff. This splits the garment's lightness and colour into three bands and turns down
only the middle one. Weave texture, seams, stitching and overall shape come through from the original;
no pixels are invented and nothing outside the garment mask changes.

  .venv/bin/python tools/dewrinkle.py <in.jpg> <out.jpg> [--keep 0.1] [--fine 3] [--coarse 90]
                                      [--protect x0,y0,x1,y1 ...]

  --keep     fraction of wrinkle shading left in (0 = flattest, 1 = untouched)
  --fine     px; detail smaller than this is kept as texture
  --coarse   px; shading broader than this is kept as shape
  --protect  boxes left untouched (badges, labels, prints)

Defaults are the "strong" setting picked on a wool knit test (2026-11-11). In a listing run this
is switched on per photo in picks.json: {"file": ..., "angle": "front", "dewrinkle": true,
"protect": [[x0, y0, x1, y1]]}, with boxes in output pixels (1200x1600). process.py applies it.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def masked_blur(x, m, sigma):
    return cv2.GaussianBlur(x * m, (0, 0), sigma) / np.maximum(cv2.GaussianBlur(m, (0, 0), sigma), 1e-4)


def dewrinkle(rgb, mask, keep=0.1, fine=3, coarse=90, protect=()):
    m = (mask > 0.5).astype(np.float32)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    out = lab.copy()
    for c in range(3):
        x = lab[..., c]
        mid = masked_blur(x, m, fine) - masked_blur(x, m, coarse)
        out[..., c] = x - (1 - keep) * mid
    # only inside the garment, eased off over the last few px so the outline is untouched
    w = cv2.GaussianBlur(cv2.erode(m, np.ones((9, 9), np.uint8)), (0, 0), 3)
    for x0, y0, x1, y1 in protect:
        p = np.zeros_like(w); p[y0:y1, x0:x1] = 1
        w *= 1 - cv2.GaussianBlur(p, (0, 0), 6)
    w = w[..., None]
    res = cv2.cvtColor(np.clip(lab * (1 - w) + out * w, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    res[m == 0] = rgb[m == 0]

    # report: what moved and what did not
    hi = lambda im: cv2.cvtColor(im, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32) - cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32), (0, 0), 2)
    inner = cv2.erode(m, np.ones((15, 15), np.uint8)) > 0
    l0, l1 = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32), cv2.cvtColor(res, cv2.COLOR_RGB2LAB).astype(np.float32)
    rep = {
        "pixels_changed_outside_garment": int((res != rgb).any(-1)[m == 0].sum()),
        "mean_colour_shift_L_a_b": [round(float((l1[..., i] - l0[..., i])[inner].mean()) * (100 / 255 if i == 0 else 1), 2) for i in range(3)],
        "fine_texture_kept": round(float(hi(res)[inner].std() / hi(rgb)[inner].std()), 3),
        "wrinkle_shading_left": round(float(np.std((masked_blur(l1[..., 0], m, fine) - masked_blur(l1[..., 0], m, coarse))[inner])
                                            / np.std((masked_blur(l0[..., 0], m, fine) - masked_blur(l0[..., 0], m, coarse))[inner])), 3),
    }
    return res, rep


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--keep", type=float, default=0.1)
    p.add_argument("--fine", type=float, default=3)
    p.add_argument("--coarse", type=float, default=90)
    p.add_argument("--protect", nargs="*", default=[])
    a = p.parse_args()
    import process as P
    from rembg import new_session
    rgb = np.array(Image.open(a.src).convert("RGB"))
    mask = P.subject_mask(rgb, new_session("isnet-general-use"))
    res, rep = dewrinkle(rgb, mask, a.keep, a.fine, a.coarse, [tuple(int(v) for v in b.split(",")) for b in a.protect])
    Image.fromarray(res).save(a.out, quality=92)
    print(json.dumps(rep, indent=2))
