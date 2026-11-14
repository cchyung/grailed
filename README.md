# Grailed listing kit

Claude Code skills and Python tools that take a dump of iPhone photos of clothes and turn them into live Grailed listings: sort and crop photos, white-balance them, clean up the background with an AI pass that never touches the garment, research sold prices, collect condition notes, and fill in the Grailed sell form through Claude in Chrome.

## Requirements

- macOS with Claude Code
- [uv](https://docs.astral.sh/uv/) (Python 3.12 is installed by it)
- The Claude in Chrome extension, connected, in a Chrome profile logged in to Grailed
- Optional: an OpenAI API key for the background cleanup

## Setup

Open the repo in Claude Code and say "set this up". That runs the `grailed-setup` skill, which creates `.venv`, installs `requirements.txt`, writes `.env`, creates the working files from `examples/`, checks the Grailed login and publishes your condition-notes page.

## Doing a run

1. Lay each piece on the floor and shoot front, back, inside, brand tag, care tag, details and any flaws.
2. AirDrop the photos into `photos/` and put a measurements CSV beside them (see `examples/measurements.example.csv`).
3. Tell Claude "let's do a Grailed run". The `grailed-listing` skill walks through it and asks for condition notes and price sign-off before anything is published.

## Layout

| Path | What it is |
|---|---|
| `.claude/skills/grailed-setup` | First-time setup |
| `.claude/skills/grailed-listing` | The full run, plus Grailed form and API notes in `reference/` |
| `.claude/skills/grailed-photos` | Photo processing rules |
| `process.py` | Crop, white balance, AI cleanup for each item in `picks.json` |
| `tools/` | Contact sheets, listing validator, markdown builder, dewrinkle, AI edit helper, notes page |
| `examples/` | Templates for the gitignored per-seller files |
