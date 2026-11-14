# Grailed listing API (observed, unofficial)

Captured 2026-11-11 by hooking `window.fetch` on `grailed.com/sell/new` while publishing through the form. This is Grailed's private web API. It is undocumented, can change without notice, and automated use may be against Grailed's terms. Nothing here has been used to create a listing yet: all six listings in the 2026-11-11 batch went through the form.

## Requests the sell form makes

| Step | Request | Notes |
|---|---|---|
| Photo slot | `GET /api/photos/presign/listing` | One per photo. Returns presigned S3 upload fields. |
| Photo upload | `POST https://grailed-media.s3.amazonaws.com/` (multipart) | Returns 201. The file then appears at `https://media-assets.grailed.com/prd/listing/temp/<32-hex id>`. |
| Price hints | `GET /api/pricing?designer_ids[]=<id>&category_path=<path>&condition=<cond>&size=<size>` | Feeds the "Sold Price Range" box. |
| Shipping | `GET /api/shipping_configs?category_path=<path>&from_address_id=<id>&price=<price>` | |
| Publish | `POST /api/listings` (JSON) | Returns 200 with `{"data": {"id": <listing id>, "title": ...}}`. |

Headers on the publish call: `accept`, `accept-version`, `content-type`, `device-id`, `x-csrf-token`. The session cookie goes along automatically. Header values were not recorded, on purpose: read them from the live page when needed and never write them to a file.

## `POST /api/listings` body

```json
{
  "buynow": true,
  "makeoffer": true,
  "category_path": "tops.sweaters_knitwear",
  "condition": "is_gently_used",
  "title": "Stone Island Light RWS Pure Wool Sweater",
  "description": "...",
  "designers": [{"id": 909, "slug": "wooyoungmi", "name": "Wooyoungmi", "logo_url": null,
                 "departments": ["menswear", "womenswear"], "collaborations": []}],
  "size": "l",
  "exact_size": null,
  "price": "240",
  "minimum_price": null,
  "styles": ["streetwear"],
  "traits": [{"name": "color", "value": "Gray"}, {"name": "country_of_origin", "value": "BG"}],
  "measurements": [{"measurement_type_id": 1, "inches": 22}],
  "photos": [{"id": null, "url": "https://media-assets.grailed.com/prd/listing/temp/<id>",
              "width": 1200, "height": 1600, "rotate": 0}],
  "return_address_id": <your return address id>,
  "shipping": {"us": {"amount": 0, "enabled": true}, "ca": {"amount": 20, "enabled": true},
               "uk": {"amount": 25, "enabled": true}, "eu": {"amount": 25, "enabled": false},
               "asia": {"amount": 25, "enabled": true}, "au": {"amount": 25, "enabled": true},
               "other": {"amount": 25, "enabled": true}},
  "shipping_label": {"free_shipping": false},
  "duplicate_listing": false,
  "hidden_from_algolia": false
}
```

Values seen:

- `category_path`: `tops.sweatshirts_hoodies`, `tops.sweaters_knitwear`, `bottoms.casual_pants`. Outerwear paths were not captured.
- `condition`: `is_new`, `is_gently_used`. `Used` and `Very Worn` were not captured.
- `size`: lowercase letter for tops (`s`, `l`), waist number as a string for bottoms (`"30"`).
- `price`: string. `minimum_price: null` is what the form sends with Smart Pricing off.
- `styles`: lowercase (`luxury`, `streetwear`).
- `traits.country_of_origin`: ISO 3166 alpha-2 (`BG`). Omitted when no country is chosen.
- `designers`: the full designer object from the search box, including its whole `collaborations` list (Supreme's is several KB). Designer ids seen: Supreme 6, Juun.J 561, Wooyoungmi 909.
- `measurement_type_id`: 1 Chest, 2 Length, 3 Shoulders, 4 Sleeve Length (tops); 7 Inseam, 9 Front Rise (bottoms). Waist, Leg Opening, Hem, Thigh and Knee ids were not captured.
- `shipping`: the account's saved defaults as of this date.

## What a script would still need

1. Photos. The presign response fields and the S3 form fields were not captured. A page script cannot read local files, so photos still have to go in through the form's file input (`file_upload`), or be uploaded from Python with the presign fields.
2. The designer object for each brand (from the form's designer search request, not captured).
3. The untested enum values listed above.
4. A dry run that creates one listing and checks it against a form-made one before trusting it for a batch.

## How to capture more

Install the hook right after `/sell/new` loads and before clicking anything, write each record to `sessionStorage` (the page navigates to the listing after publish, which wipes `window`), and read it back from the listing page. The browser tool blocks output containing query strings or long tokens, so strip those before returning: return parsed keys and short values, not raw bodies.
