# Grailed sell form map

Observed on `https://www.grailed.com/sell/new`, Oct 2026, Chrome viewport 1458x772 (screenshot coordinate frame). Coordinates are click targets in that frame. Re-verify with one screenshot if the viewport differs or Grailed ships a redesign.

Checked again 2026-11-11 at 1458x757 after `resize_window` to 1458x900: every coordinate below still held, with Publish at (890,721). The logged-in Chrome profile opened at 932x830, where the layout is different, so resize first.

Field values and the request the form sends on publish are in `api-notes.md`.

## Order of fields

1. Department / Category (cascading menu) → Sub-category → Designer (search box) → Size
2. Item Name
3. Color, Condition, Description
4. Style, Measurements (grid changes by category)
5. Country of origin (search box, optional)
6. Price, Accept Offers (default ON), Smart Pricing (default **ON**, turn off), Floor price
7. Shipping From (account address), Shipping Regions (US = prepaid label; international = account defaults)
8. Photos (9 slots), Save as Draft / **Publish** (sticky bar, Publish at 890,736)

## Option vocabularies

- **Department**: Menswear, Womenswear
- **Menswear categories** (menu y): Tops 396, Bottoms 436, Outerwear 478, Footwear, Tailoring, Accessories
- **Outerwear sub** (y): Bombers 350, Cloaks & Capes 391, Denim Jackets 432, Heavy Coats 473, Leather Jackets 514, Light Jackets 555, Parkas 596, Raincoats 637, Vests 678. There is no "Down" subcategory: use Light Jackets or Parkas.
- **Tops sub** (y): Long Sleeve T-Shirts 350, Polos 391, Shirts (Button Ups) 432, Short Sleeve T-Shirts 473, Sweaters & Knitwear 514, Sweatshirts & Hoodies 555, Tank Tops & Sleeveless 596, Jerseys 637
- **Bottoms sub** (y): Casual Pants 350, Cropped Pants 391, Denim 432, Leggings 473, Overalls & Jumpsuits 514, Shorts 555, Sweatpants & Joggers 596, Swimwear 637
- **Tops/Outerwear sizes** (y): XXS 408, XS 449, S 490, M 531, L 572, XL 613, XXL 654 (labels like `US M / EU 48-50 / 2`)
- **Bottoms sizes** (y): US 26 408, 27 449, 28 490, 29 531, 30 572, 31 613, 32 654 … (one per 41px)
- **Color** (y, when dropdown at 218): Black 258, White 299, Gray 340, Brown 381, Beige 422, Yellow 463, Red 504, Orange 545, Pink 586, Purple 627, Blue 668, Green 708, Multi 749
- **Condition** (y, dropdown at 385): New/Never Worn 425, Gently Used 466, Used 507, Very Worn 548
- **Style** (y, dropdown at 324): None 366, Luxury 406, Vintage 446, Avant-Garde 488, Streetwear 528, Workwear 568, Gorpcore 610, Sportswear 650, Basics 692, Western 732
- **Measurements grid**: tops/outerwear = Chest, Length, Shoulders / Sleeve Length, Hem. Bottoms = Waist, Inseam, Leg Opening / Front Rise, Thigh, Knee. Chest = pit-to-pit. Unclear whether Waist is flat or full; leave blank and put it in the description.
- **Country**: type the name, then click the single suggestion just below the box. "Northern Mariana Islands" isn't in the list; its tags say (U.S.A.), so use United States.

## Coordinate recipe (the fast path)

Top of page (no scroll):
- Category button 516,310 → Menswear 380,396 → category row (see y above, x≈420–436)
- Sub-category button 938,310 → option (x≈810–834)
- Designer box 516,367 → type → first match at y≈408 (later matches every ~41px)
- Size button 938,367 → option (x≈830)
- Item name: **571 if the "Add a collaboration" button appeared under Designer, 535 if not** (it disappears once a collab is chosen; some designers, e.g. Christian Dior Monsieur, never show it)

After `scroll down 5` at x=1300 (always scroll from the right margin; scrolling over the description box only scrolls the textarea):
- Color 516,218 · Condition 516,385 · Description 728,610 (subtract 37 from every y here if the collab button was absent)

After another `scroll down 5`:
- Style 516,324 · Measurement row 1 y=610 (x 526 / 792 / 1058), row 2 y=682 (same -37 rule)

After another `scroll down 5`:
- Country 516,368 → suggestion 360,404 · Price 526,630 (same -37 rule)

After another `scroll down 5`:
- Smart Pricing toggle 678,259 (223 with the -37 shift). Confirm it reads OFF.

Then `scroll down 15` → Photos. Get file-input refs with `find "photo upload file inputs"` (9 refs, in slot order; the first is the cover).

**Bulk upload works** (verified Oct 2026): pass every path, in order, to one `file_upload` on the first slot ref. They land in order, with the first as the cover. Keep the set under 10MB (1600px exports run ~2–5MB for 3–8 photos).

## Gotchas

- **First click after `navigate` to /sell/new is swallowed** while the page hydrates. Don't put the category click in the same batch as the navigate; instead `find "Department / Category"` first (it waits), then click.
- **Designer search can show stale results** (the previous query's list). If the top hit isn't the brand, press BackSpace and retype the last letter, wait 2s, look again. If the field clears, retype the full name.
- **Collabs**: pick the base designer, click "Add a collaboration" (516,408), then `find` the exact "X x Y" menu item and click by ref (the list is long and needs scrolling).
- **Clicking a toggle twice closes it**: the category dropdown toggles. If a screenshot shows it closed, click once, not twice.
- **Editing price on a live listing**: `/listings/<id>/edit`; the price input ignores triple-click + type. Click into it, press End, then BackSpace ×4, type the new price, Publish. A price drop of 10% or more also shows as a markdown on the listing.
- **Grailed shows sold-price data inside the form** (the "Sold Price Range" box next to Price) once category + designer are set. Read it; it's the quickest sold-price check you can get on Grailed.
- **Published page check**: the listing page shows "Smart Pricing: OFF/ON" and the price. Take one screenshot there to verify.

## Replacing photos on a live listing

Verified Oct 2026 on all 10 listings, about 4 browser calls each:

1. `navigate` to `/listings/<id>/edit`, wait 4, `find "Photos section header"`.
2. `scroll_to` that ref, then screenshot to get the red ✕ positions. The viewport can change between sessions (1458, 1483 or 1512 wide), so read positions off the screenshot once and reuse them for the rest of the session. At 1512x772 after `scroll_to`: cover ✕ (600,432), top row ✕ x = 742 / 876 / 1010 / 1144 at y = 432, bottom row same x at y = 608.
3. Click the ✕ buttons **from the last photo to the first** so the remaining ones don't shift. There's no confirm dialog. Clicking a "Remove Photo" ref directly didn't register; click coordinates instead. Then `find "photo upload file inputs"`: 9 refs means every slot is empty.
4. One `file_upload` with all new paths on the first ref, wait 5–6, screenshot to check order.
5. Click Publish (center of the sticky bar, (756,736) at 1512 wide). It saves and lands on the listing page. Check the cover, price, and "Smart Pricing: OFF".

Edits keep price, offers, favorites, and the bump timer. The listing page shows how many people favorited the piece and that they'll be notified on a 10% price drop.
