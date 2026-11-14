---
name: grailed-photos
description: Process Grailed listing photos in this repo. Inspect every photo, crop first, apply a natural floor-anchored white balance, run the AI background cleanup, then verify the garment was not edited. Use whenever photos are being picked, cropped, color-corrected, cleaned up, enhanced, re-edited or reviewed for a listing, including phase 2 of a grailed-listing run, a reshoot, or a one-off "fix this photo" request. Also use before making any OpenAI image edit on a garment photo.
---

# Grailed photo processing

All commands run from the repo root with `.venv/bin/python`. The order is fixed: inspect, crop, white balance and tone, AI cleanup, verify. Cropping comes first so the image model only sees the final frame at final resolution, and most clutter is already gone before it runs.

The rule that everything else follows from: **the garment in a listing photo is never generated.** The image model redraws the whole frame, garment included, even when told not to. In testing it turned a charcoal jacket navy, added sheen, and drew marks on a logo patch. So model pixels are only ever used for the floor, and each shot is checked before it ships.

## 1. Inspect every photo

1. `.venv/bin/python tools/contact_sheet.py intake <photo dir> <scratchpad>/sheets`, then read every sheet. Do not process photos you have not looked at.
2. Group into items by consecutive runs, move each run to `photos/raw/<Item name>/`.
3. Per photo, note: angle, whether it needs `rotate`, near-duplicates, blur, clipped sleeves, what clutter is in frame (bag, stool, chair wheels), and whether the light changed partway through the item (cool daylight vs warm lamp).
4. Write `picks.json`: per item an ordered list of `{file, angle, rotate?, dewrinkle?, protect?}`, cover first. The `angle` text drives the pipeline:
   - starts with `front`, `back`, `side` or `inside` → full-garment shot: subject-cropped, white balance measured on its own floor, eligible for the AI pass.
   - contains `tag` or `label` → close-up balanced on the white label itself.
   - anything else → close-up. It uses its own floor when at least 35% of the frame is floor, otherwise it borrows white balance from the nearest full shot in capture order.
   - Name detail shots so they do not start with one of the full-shot words. "back pocket detail" is treated as a full back shot; write "rear pocket detail".

   - Add `"crop": [x0, y0, x1, y1]` (fractions of the rotated frame) to cut clutter out of a close-up, e.g. a chair leg in the corner. Keep the box near 3:4 so nothing else is trimmed.

## 2. Crop, white balance, tone

`.venv/bin/python process.py --item "<Item name>"` writes `photos/out/<item>/01.jpg…` at 1200x1600 (3:4), metadata stripped.

White balance is one global gain per photo, so it shifts color without touching texture or detail:

- The phone compensates for the warm floor, so whites come out green-cyan and the cast drifts between shots. The oak floor is in every full shot, so it is the reference. Each photo's floor is moved to `FLOOR_TARGET` in `process.py`, the floor's color when a known white reads neutral.
- `_verify.json` records which anchor each photo used and the gains. Gains normally sit within about ±15% of 1.0. A shot far outside that has something else wood-toned in frame or very mixed light; look at it.
- A photo with no floor and no full shot to borrow from gets no white balance and is reported as such.
- New floor or new room: shoot a few frames with something white on the floor, then `process.py --wb-calibrate <photos>` and put the printed value in `FLOOR_TARGET`.

Look at the result before spending money on the AI pass: `.venv/bin/python tools/contact_sheet.py review photos/out <scratchpad>/sheets`. Fix picks, rotation or crops and rerun.

## Wrinkle softening (opt-in per photo)

Add `"dewrinkle": true` to a pick in `picks.json` to turn down wrinkle shading on that photo. It runs after white balance and tone and before the AI pass, so the locked garment is the softened one.

- It is not generative. `tools/dewrinkle.py` splits the garment's lightness and color into fine, middle and coarse bands and reduces only the middle one. Weave texture, seams, the outline and the floor come through unchanged.
- `true` is the strong setting approved on a wool knit test (2026-11-11). A number sets how much wrinkle shading stays, e.g. `"dewrinkle": 0.3` for a lighter pass.
- Add `"protect": [[x0, y0, x1, y1], ...]` for badges, labels and prints that should be left alone. Boxes are in output pixels (1200x1600); run once without it, read the coordinates off `01.jpg`, then rerun.
- It suits plain fabric laid flat. Soft rumpling and blotchy shading go; sharp crease lines stay, because a thin crease is the same scale as a seam. Do not use it on patterned or printed fabric, leather, or anything where creasing is part of the condition being disclosed.
- `_verify.json` reports `wrinkle_shading_left`, `fine_texture_kept` (expect above 0.95), `mean_colour_shift_L_a_b` (expect under 1) and `pixels_changed_outside_garment` (must be 0).
- Asking the image model to remove wrinkles does not work: it redraws the garment (new sleeve shape, moved seams, redrawn badge). Do not try it again.

## 3. AI background cleanup

`.venv/bin/python process.py --ai --item "<Item name>"`

- Needs `OPENAI_API_KEY` in `.env`. Uses `gpt-image-2.5-sunburst` through `tools/ai_edit.py`.
- Runs on full-garment shots only. Close-ups are mostly garment, so there is nothing for it to clean.
- The model is asked to remove clutter and even out the floor lighting. Its floor is then color-matched back to the white-balanced floor, and the garment is copied back from step 2: the union of the garment outline in the step 2 image and in the model's image, grown 7px.
- Model outputs are cached in `photos/ai-cache/` keyed on the input pixels, so a rerun with unchanged picks costs nothing. A changed crop, rotation or white balance is a new call.
- Cost is roughly 7 cents per shot at current token rates (one measured call: about 1,500 input and 1,800 output image tokens).

## 4. Verify

Every AI shot gets these checks. A shot that fails any of them ships as the step 2 image, with no model pixels, and says so.

| Check | Passes when | What it catches |
|---|---|---|
| `garment_pixels_changed` | 0 | Any pixel inside the garment mask differing from step 2 |
| `halo_pct` | ≤ 3% | The model's redrawn garment sticking out around the original (floor next to the garment that is no longer wood-toned) |
| `floor_shift_px` | ≤ 2px | The model moving or rescaling the scene |
| `floor_dE` | ≤ 3 | The model's floor color drifting from the white-balanced floor |

`ai_garment_before_lock` in the report describes what the model did to the garment before it was replaced. It reads "edited" on almost every shot. That is expected and is the reason for the lock; it is not a failure.

Then look, because the numbers do not cover everything:

1. Read `photos/out/<item>/_verify.json`. Report the count of PASS and FAIL and the reason for each FAIL.
2. Open `photos/out/<item>/_ai_compare.jpg` (before | after per shot). Check the garment edge for seams or leftover fragments, check that nothing was added to the floor, and check that a strap, belt, hanger or hang tag lying beside the garment was not removed as clutter. The garment mask can miss a dark sleeve on a dark floor; if a part of the garment looks different between before and after, treat the shot as failed.
3. If a shot fails or looks wrong, rerun without `--ai` for that item, or drop its cache file and rerun for a fresh attempt. Do not hand-edit around a failed check.

## One-off edits

- Remove a single bright object and change nothing else: `tools/ai_edit.py remove <photo> <out.png> --box x0,y0,x1,y1 --crop x0,y0,x1,y1`. Only pixels inside the object mask come from the model; it exits non-zero if any pixel outside the mask changed. The object finder looks for bright, low-saturation pixels (white stool legs), so a dark object needs a different mask.
- One photo outside the item folders: `tools/ai_edit.py enhance <photo> <out.png>`, same lock and checks.

## What not to do

- Do not send a garment photo to an image model and use the output directly, even with a "don't change the garment" prompt.
- Do not tone-match the garment to the model's output. On dark fabric an offset flattens contrast and shifts the color.
- Do not raise a threshold to get a shot through. Ship the step 2 image instead.
- Do not put generated pixels on tags, labels, flaws or detail shots.
