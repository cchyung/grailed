#!/usr/bin/env python3
"""Preflight for listings.json: every field Grailed's sell form needs, in its exact vocabulary,
plus photos present and small enough to upload, shot coverage (front, back, brand and care tags, a photo of
any flaw the description mentions), floor not above price, description measurements matching the form
fields, and style codes in the title. Run before opening the browser.

  .venv/bin/python tools/validate_listings.py            # all unpublished items
  .venv/bin/python tools/validate_listings.py --all      # include already-published ones
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "photos" / "out"

SUBCATS = {
    "Tops": ["Long Sleeve T-Shirts", "Polos", "Shirts (Button Ups)", "Short Sleeve T-Shirts",
             "Sweaters & Knitwear", "Sweatshirts & Hoodies", "Tank Tops & Sleeveless", "Jerseys"],
    "Bottoms": ["Casual Pants", "Cropped Pants", "Denim", "Leggings", "Overalls & Jumpsuits",
                "Shorts", "Sweatpants & Joggers", "Swimwear"],
    "Outerwear": ["Bombers", "Cloaks & Capes", "Denim Jackets", "Heavy Coats", "Leather Jackets",
                  "Light Jackets", "Parkas", "Raincoats", "Vests"],
}
TOP_SIZES = ["US XXS / EU 40", "US XS / EU 42 / 0", "US S / EU 44-46 / 1", "US M / EU 48-50 / 2",
             "US L / EU 52-54 / 3", "US XL / EU 56 / 4", "US XXL / EU 58 / 5"]
COLORS = ["Black", "White", "Gray", "Brown", "Beige", "Yellow", "Red", "Orange", "Pink", "Purple",
          "Blue", "Green", "Multi"]
CONDITIONS = ["New/Never Worn", "Gently Used", "Used", "Very Worn"]
STYLES = ["None", "Luxury", "Vintage", "Avant-Garde", "Streetwear", "Workwear", "Gorpcore",
          "Sportswear", "Basics", "Western"]
MEASURE = {
    "top": {"Chest", "Length", "Shoulders", "Sleeve Length", "Hem"},
    "Bottoms": {"Waist", "Inseam", "Leg Opening", "Front Rise", "Thigh", "Knee"},
}
UPLOAD_LIMIT = 10 * 1024 * 1024  # file_upload per-call cap
MAX_PHOTOS = 9
PICKS = json.loads((ROOT / "picks.json").read_text()) if (ROOT / "picks.json").exists() else {}

# Description measurement line ("Shoulder 19 / Pit to pit 22 / ...") -> form field
DESC_FIELDS = {"shoulder": "Shoulders", "pit to pit": "Chest", "length": "Length", "sleeve": "Sleeve Length",
               "inseam": "Inseam", "leg opening": "Leg Opening", "rise": "Front Rise"}
FLAW_WORDS = r"\b(marks?|fray(ing|ed)?|stains?|holes?|pilling|scuffs?|signs of wear|wear on|discolou?r\w*|snags?|tears?|rips?)\b"
# Words in a pick's angle that count as photographing a flaw
FLAW_ANGLE = re.compile(r"flaw|wear|mark|fray|stain|hole|scuff|damage", re.I)


def shot_checks(item):
    """Coverage against Grailed's photo guide: front, back, brand tag, care tag, plus a photo of any flaw
    the description mentions."""
    errs, warns = [], []
    picks = PICKS.get(item.get("folder"))
    if picks is None:
        return errs, ["no entry in picks.json, can't check shot coverage"]
    angles = [p["angle"].lower() for p in picks]
    if not any(a.startswith("front") for a in angles):
        errs.append("no front shot")
    if not any(a.startswith("back") for a in angles):
        warns.append("no back shot")
    if not any(("tag" in a or "label" in a) and "care" not in a for a in angles) and not any("brand" in a for a in angles):
        warns.append("no brand tag shot (Grailed lists it as required when the piece has one)")
    if not any("care" in a for a in angles):
        warns.append("no care tag shot (Grailed lists it as required when the piece has one)")
    desc = item.get("description", "")
    for m in re.finditer(FLAW_WORDS, desc, re.I):
        before = desc[max(0, m.start() - 30):m.start()].lower()
        if re.search(r"\b(no|without|never)\b[^.]*$", before):
            continue  # "no stains, marks, or other issues"
        if not any(FLAW_ANGLE.search(a) for a in angles):
            warns.append(f"description mentions {m.group(0)!r} but no pick angle shows a flaw (name it e.g. 'sleeve flaw')")
        break
    return errs, warns


def text_checks(item):
    """Description measurements agree with the form fields; style codes in the description also appear in the title."""
    errs, warns = [], []
    desc, meas = item.get("description", ""), item.get("measurements", {})
    for line in desc.splitlines():
        if " / " not in line:
            continue
        for part in line.split(" / "):
            m = re.match(r"\s*([A-Za-z ]+?)\s+([\d.]+)\s*$", part)
            if not m:
                continue
            field = DESC_FIELDS.get(m.group(1).strip().lower())
            if field and field in meas and float(meas[field]) != float(m.group(2)):
                errs.append(f"description says {m.group(1).strip()} {m.group(2)} but measurements[{field!r}] is {meas[field]}")
    title = item.get("name", "")
    for code in set(re.findall(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9][A-Z0-9-]{5,}\b", desc)):
        if code not in title and not code.startswith(("FN-", "RWS")):
            warns.append(f"style code {code} is in the description but not the title (buyers search by code)")
    return errs, warns


def check(item):
    errs, warns = [], []
    need = ["folder", "category", "subcategory", "designer", "size", "name", "color", "condition",
            "style", "price", "description"]
    for k in need:
        if item.get(k) in (None, ""):
            errs.append(f"missing {k}")
    cat = item.get("category")
    if cat not in SUBCATS:
        errs.append(f"category {cat!r} not in {list(SUBCATS)}")
    elif item.get("subcategory") not in SUBCATS[cat]:
        errs.append(f"subcategory {item.get('subcategory')!r} not in {SUBCATS[cat]}")
    if cat in ("Tops", "Outerwear") and item.get("size") not in TOP_SIZES:
        errs.append(f"size {item.get('size')!r} not a Grailed tops/outerwear size")
    if cat == "Bottoms" and not str(item.get("size", "")).startswith("US "):
        errs.append(f"size {item.get('size')!r} should look like 'US 30 / EU 46'")
    for k, allowed in (("color", COLORS), ("condition", CONDITIONS), ("style", STYLES)):
        if item.get(k) not in allowed:
            errs.append(f"{k} {item.get(k)!r} not in {allowed}")
    fields = MEASURE["Bottoms" if cat == "Bottoms" else "top"]
    bad = set(item.get("measurements", {})) - fields
    if bad:
        errs.append(f"measurement fields {sorted(bad)} not on the form (allowed {sorted(fields)})")
    if not item.get("measurements"):
        warns.append("no measurements (Grailed says +40% sell-through with them)")
    if not item.get("country"):
        warns.append("no country of origin (optional, but asked for customs)")
    if item.get("collab") and not str(item["collab"]).startswith(item.get("designer", "")):
        warns.append("collab usually reads '<designer> x <partner>'")
    photos = sorted((OUT / item.get("folder", "")).glob("0*.jpg"))
    if not photos:
        errs.append(f"no processed photos in photos/out/{item.get('folder')}")
    if len(photos) > MAX_PHOTOS:
        warns.append(f"{len(photos)} photos; Grailed takes {MAX_PHOTOS}, extras will be dropped")
    if len(photos) < 5:
        warns.append(f"only {len(photos)} photos of {MAX_PHOTOS} slots")
    total = sum(p.stat().st_size for p in photos[:MAX_PHOTOS])
    if total > UPLOAD_LIMIT:
        warns.append(f"photo set is {total / 1e6:.1f}MB; upload per slot or rerun process.py --size 1600")
    floor, price = item.get("floor"), item.get("price")
    if floor is not None and price is not None and floor > price:
        errs.append(f"floor ${floor} is above the price ${price}")
    for fn in (shot_checks, text_checks):
        e, w = fn(item)
        errs += e
        warns += w
    return errs, warns


def main():
    data = json.loads((ROOT / "listings.json").read_text())
    show_all = "--all" in sys.argv
    failed = 0
    for item in data["items"]:
        if item.get("grailed_id") and not show_all:
            continue
        errs, warns = check(item)
        status = "FAIL" if errs else "ok  "
        print(f"{status} {item.get('folder')}  ${item.get('price')}")
        for e in errs:
            print(f"     ✗ {e}")
        for w in warns:
            print(f"     · {w}")
        failed += bool(errs)
    print(f"\n{failed} item(s) need fixing" if failed else "\nall clear")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
