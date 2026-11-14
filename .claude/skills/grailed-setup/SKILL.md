---
name: grailed-setup
description: First-time setup for this Grailed listing repo on a new machine or for a new seller. Creates the Python venv, installs dependencies, writes .env, creates the photos/ folders and the per-seller working files from examples/, checks Claude in Chrome and the Grailed login, and publishes the seller's own condition-notes page. Use when someone says "set this up", "init", "first run", or when grailed-listing finds .venv/, .env, listings.json or config.local.json missing.
---

# Grailed repo setup

Run each step, skip any that is already done, and report what was done and what still needs the seller at the end. Nothing here publishes a listing.

## 1. Python environment

1. Check for `uv` (`uv --version`). If it's missing, ask before installing it (`brew install uv` or the official install script).
2. `uv venv --python 3.12 .venv` if `.venv/` doesn't exist.
3. `uv pip install --python .venv/bin/python -r requirements.txt`.
4. Smoke test: `.venv/bin/python -c "import cv2, PIL, rembg, pillow_heif, openai, dotenv"`. The first rembg run downloads its model (~170 MB) to `~/.u2net/`; warn the seller it will take a minute.

## 2. Secrets

1. If `.env` doesn't exist, copy `.env.example` to `.env` and `chmod 600 .env`.
2. Ask the seller for an OpenAI API key, or tell them to paste it into `.env` themselves. It is only needed for the AI background cleanup (`process.py --ai`). Without it, everything else works and photos ship without that pass.
3. Never print the key or commit `.env`.

## 3. Working files

Copy each of these from `examples/` only if the target doesn't exist. Never overwrite an existing one, it holds the seller's run data.

| Target | Source | Starting content |
|---|---|---|
| `config.local.json` | `examples/config.local.example.json` | as is |
| `listings.json` | `examples/listings.example.json` | keep `_note` and `defaults`, set `items` to `[]` |
| `picks.json` | `examples/picks.example.json` | keep `_note` only |
| `pricing.md` | none | `# Pricing research` |

Then `mkdir -p photos/raw photos/out photos/_not-selling photos/review tools/notes-page/thumbs` and run `.venv/bin/python tools/build_md.py` to create `listings.md`.

All of these are gitignored. Check with `git check-ignore -v listings.json config.local.json .env` and stop if any of them isn't ignored.

## 4. Claude in Chrome

1. Load the Chrome tools in one ToolSearch call (`tabs_context_mcp`, `tabs_create_mcp`, `navigate`, `list_connected_browsers`, `switch_browser`). If they don't exist, tell the seller to install the Claude in Chrome extension and connect it, then continue with step 6 and come back.
2. If several browsers are connected, have the seller pick theirs with `switch_browser` and write its name to `chromeProfile` in `config.local.json`.
3. Open `grailed.com/sell/new` in a new tab. A redirect to `/users/sign_up` means that profile isn't logged in to Grailed. Ask the seller to log in there. Sold comps, listing and status checks all need it.
4. Check the account's shipping defaults at `grailed.com/settings/shipping` with the seller (return address, international regions). The listing skill relies on them.

## 5. Grailed form coordinates

`.claude/skills/grailed-listing/reference/form-map.md` was measured on a 1458x900 window. Resize to that, open `/sell/new`, take one screenshot and compare against the form-map positions for the category button and the photo slots. If the layout has moved, note it to the seller; the listing skill re-derives positions from screenshots, but form-map should be updated after the first run.

## 6. Condition notes page

If `notesArtifactUrl` in `config.local.json` is empty:

1. Load the `artifact-capabilities` skill.
2. Publish `tools/notes-page/index.html` as a new artifact with capabilities `{db:{}, user:{}}` and icon `notes`.
3. Write the returned URL to `notesArtifactUrl`.

This gives every seller their own notes database. Don't reuse someone else's URL.

## 7. Check

1. `.venv/bin/python tools/validate_listings.py` runs without a traceback (an empty `items` list is fine).
2. `git status --short` shows no run data, photos or `.env`.
3. Tell the seller the next step: drop iPhone photos into `photos/`, put a measurements CSV next to them (format in `examples/measurements.example.csv`), and say "let's do a Grailed run".
