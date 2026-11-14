---
name: grailed-listing
description: Run a batch Grailed listing session end to end. Sort a dump of iPhone photos into items, pick the best shot per angle, crop and color-correct them, read the tags, research and price each piece, collect condition notes, then publish every listing on grailed.com through Claude in Chrome. Use when the seller says they're doing a Grailed run, drops new photos in photos/, asks to list, relist, or reprice pieces on Grailed, or wants listing copy written for clothes.
---

# Grailed listing run

Everything lives in this repo. Python is `.venv/bin/python`. If `.venv/`, `.env`, `listings.json` or `config.local.json` is missing, run the `grailed-setup` skill first. Per-seller settings (notes page URL) are in `config.local.json`. The Grailed form reference is `reference/form-map.md` in this skill. Read it before touching the browser.

The run has five phases. The order matters: everything that needs a human answer gets collected **before** the browser opens, so the listing loop never stalls mid-form.

## 1. Intake and organize

1. Photos land loose in `photos/` (IMG_xxxx.JPG/HEIC). Get a measurements CSV from the seller (format: `examples/measurements.example.csv`) (or `~/Downloads/measurements.csv`).
2. `.venv/bin/python tools/contact_sheet.py intake photos/ <scratchpad>/sheets`, then read the sheets. Shots of one garment are consecutive in capture order, so group by runs.
3. Move each run into `photos/raw/<Item name>/`. Anything the seller isn't selling goes to `photos/_not-selling/<name>/`. Move files, never delete them.
4. Read every tag while you're here: brand, size, style code, fiber, country of origin. Zoom by cropping the tag region to ~600px rather than guessing from a thumbnail. Tags have corrected the brand before ("Outer error" was really ADERERROR).

## 2. Pick shots and process

**Load the `grailed-photos` skill before touching any photo** (Skill tool, `grailed-photos`). It owns this phase: inspect every photo, crop, floor-anchored white balance, AI background cleanup, and the checks that the garment was not edited. A subagent given photo work must load it too; say so in its brief.

1. Write `picks.json`: per item, an ordered list `{file, angle, rotate?}`. Cover first. Order: front, back, inside/lining, brand+size tag, care tag, details, flaws. `rotate` is degrees counter-clockwise for garments shot sideways.
   - Between near-duplicates, keep the sharper one (Laplacian variance on a 4x-downscaled grayscale) unless framing is clearly better.
   - Angles starting with front/back/side/inside get subject-cropped. Angles containing "tag" or "label" are white-balanced on the label. Everything else is a close-up (trimmed to aspect and centered on the subject, never cropped tighter).
2. `.venv/bin/python process.py --item "<name>"` → `photos/out/<item>/01.jpg…`, 3:4 portrait, 1200x1600, EXIF/GPS stripped, white-balanced. Review with `tools/contact_sheet.py review photos/out <scratchpad>/sheets`, fix picks/rotation, rerun.
3. `.venv/bin/python process.py --ai --item "<name>"` for the AI cleanup, then read `_verify.json` and `_ai_compare.jpg` for each item as the photo skill describes. Shots that fail a check ship without the AI pass.
4. Flag reshoots now (missing back shot, blurry back, sleeve clipped) rather than after listing. Every item needs front, back, brand tag and care tag shots (Grailed's photo guide lists both tags as required when present), plus a close-up of every flaw the description will mention, with an angle name containing "flaw" or "wear" (e.g. "sleeve flaw"). `validate_listings.py` checks this from `picks.json`.

## 3. Facts, pricing, condition (all before the browser)

1. **Check the Grailed login first. This is a hard gate.** Open `grailed.com/sell/new` in a new tab. A redirect to `/users/sign_up` means the connected Chrome profile isn't logged in. Stop and have the seller log in there, or switch the extension to their profile. Do not start pricing research until this passes. Both previous batches were priced from asking prices because this was skipped.
2. **Sold comps, logged in**: `grailed.com/sold?query=<brand model>` for each item (run as one background agent, read-only, its own tab). Write the comps to `pricing.md` and set `price` and `floor` on each item in `listings.json`. Asks alone run 10–30% high. If sold data still can't be had, say so per item and mark the price low-confidence.
3. **Condition notes**: reuse the seller's "Grailed Run Notes" artifact, whose URL is `notesArtifactUrl` in `config.local.json` (source in `tools/notes-page/`, capabilities `{db:{}, user:{}}`). If it's empty, `grailed-setup` step 6 publishes one and saves the URL. Regenerate `tools/notes-page/thumbs/<slug>.jpg` (360x480 from each `01.jpg`) and republish it to that URL with the new thumbs. Then use `ArtifactData` to `update` last run's `items/*` docs with `archived: true` (never delete them: they hold the seller's condition notes) and seed one doc per item with a `batch` field set to today's date. Doc fields: `order, name, category, size, measurements, tagFacts, suggestedList, suggestedFloor, photoNote`, plus the empty fields the seller fills in: `condition, flaws, notes, color, model, askPrice, ready`. Read it back (`query` ordered by `order`) once they say they're done.
4. Build `listings.json` (shape: `examples/listings.example.json`). It is the only file edited by hand. Set `condition_score` (the seller's 1–10) and `floor` on each item. `listings.md` is generated from it by `tools/build_md.py`. Every value must use Grailed's exact vocabulary from `form-map.md`: subcategory, size label, color, condition, style, measurement field names. Map condition: 10 → New/Never Worn, 8–9 → Gently Used, 6–7 → Used, ≤5 → Very Worn. Japanese tag sizes run about one size small; list by measurements and say "Tagged L (Japanese sizing)" in the description.
5. Titles: put the style code or model name in the title when one is known (N24FC077, SUBS302, "Le Connaisseur"). Buyers search by them.
6. Descriptions: light and casual, in the seller's voice (read their past descriptions in `listings.json` if there are any). Where it came from, what it is, honest condition, then `Shoulder / Pit to pit / Length / Sleeve`. No hype, no em-dash asides.
7. `.venv/bin/python tools/validate_listings.py` must print `all clear`. Its warnings (missing shots, flaw with no photo, code not in title) go to the seller with the questions below. Ask the seller only for what's still missing (size with no tag, price, condition), in one message.
8. Flag any price that's far off Grailed's sold range before listing (Uniqlo x WM at 2x the sold high; Acne at half the median). The seller decides; don't publish a flagged price without their OK.

## 4. Listing loop (Claude in Chrome)

Load the Chrome tools in one ToolSearch call, including `browser_batch`, `find`, `file_upload` and `resize_window`. Several Chrome profiles can be connected; if `/sell/new` redirects to sign-up, ask the seller which profile is logged in (`list_connected_browsers`, then `switch_browser` so they pick it) rather than waiting. Resize the window to 1458x900 before using the coordinates in form-map. Create your own tab. The seller saying "put them up" authorizes publishing those listings, at those prices, this session. Anything else (accepting offers, messaging buyers) still needs their OK.

Per item, aim for about 5 round trips:

1. `navigate` to `/sell/new`, then `find "Department / Category"` (this waits out hydration; the first click after navigate is otherwise swallowed).
2. **Batch A**: category → menswear → category row → sub-category → designer box → type designer → wait 2 → screenshot. Check that the top search hit is right (stale results happen; see form-map).
3. **Batch B**: click designer hit → size button → size → item name (571 with the collab button, 535 without) → type name → scroll 5 at x=1300 → color, condition, description → scroll 5 → style → measurements → scroll 5 → country + suggestion → price → scroll 5 → Smart Pricing OFF → scroll 15 → `find "photo upload file inputs"`. End with a screenshot.
4. **Photos**: every path in one `file_upload` on the first slot ref (verified: all land, in order). Screenshot to confirm order.
5. **Publish** (890,736), wait 5, screenshot the listing page. Confirm the price, "Smart Pricing: OFF", and the cover photo. Write `grailed_id` and `listed_at` back into `listings.json`, then run `tools/build_md.py`.

If a screenshot in step 2 or 3 shows things shifted, re-derive positions from that screenshot before continuing. Don't click blind.

## 5. Wrap up

Report the live links, anything held back and why, the settings you chose for them (Smart Pricing off, JP sizing, countries left blank), and anything they should check (international shipping uses account defaults with self-bought labels). Close your tab.

## Re-editing photos on live listings

1. Snapshot the current edits: `cp -R photos/out photos/out_v<N>`.
2. Rerun `process.py` (follow the `grailed-photos` skill), then build before/after sheets (rows of `out_v<N>` against `out`) into `photos/review/` and `open` them for the seller. Don't touch live listings until they approve.
3. Before rerunning, check `find photos/raw -newermt <last run>`. A raw file replaced since the picks were made (as happened with the Burberry back shot) may need its `rotate` in `picks.json` changed.
4. Swap photos with the "Replacing photos on a live listing" recipe in `form-map.md`.

The photo look is tuned to a reference photo (values in `LOOK` in `process.py`; the image itself is not in git): garment highlights near L*85, bright garments near L*74, warm and rich wood floor. White balance, the AI pass and its checks are covered in the `grailed-photos` skill. Full-garment shots that can't fit at 3:4 get extra floor mirrored in rather than clipped sleeves. If the seller sends a new reference photo, measure it and update `LOOK` in `process.py`.

## Price edits on live listings

`/listings/<id>/edit` → click the price input, press End, BackSpace ×4, type the new price → Publish → verify on the listing page. In `listings.json`, set the new `price`, append `{date, from, to, note}` to `price_history` (note says why, e.g. "seller's call", "no favorites after 14 days"), lower `floor` if it is now above the price, then run `tools/build_md.py`.

## Status check on live listings

Read-only; run it at the start of every session and whenever the seller asks how things are selling. For each item with a `grailed_id`, open the listing page and record `status` (active / sold / removed), `favorites` (the page shows the count), and for sold pieces `sold_at` and `sold_price`. Fill `net` from the sale notification or payout when the seller has it, and `cost` when they say what they paid. Then run `tools/build_md.py`. A piece with no sale after 14 days is a candidate for a 10% cut (that notifies everyone who favorited it); suggest it, don't do it without their OK.
