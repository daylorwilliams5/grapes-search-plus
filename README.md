# GRAPES Search+

**Graduate fellowship, grant & award finder for UCLA graduate students.**
Created by Daylor Williams for the UCLA Division of Graduate Education (DGE).

---

## What it is

GRAPES Search+ is a self-contained, searchable database of **266 verified graduate fellowships**, grants, and awards curated from the UCLA DGE GRAPES dataset. Students can find relevant funding by searching natural language queries ("psychology dissertation", "travel grant conference") or by filtering by field of study, award type, and season.

Live demo: *(deploy via GitHub Pages — see below)*

---

## Features

- Natural language search with synonym expansion (e.g. "psychology" → behavioral, cognitive, social science)
- Field of Study filter: Social Sciences, STEM, Humanities, Health, Arts, Law & Policy, Education, International
- Award Type filter: Postdoctoral, Dissertation, Research Grant, Travel Grant, Scholarship, Internship
- Season filter: Fall, Winter, Spring, Summer, Open/Rolling
- Defaults to active/upcoming deadlines — past deadlines hidden by toggle
- Fully self-contained single HTML file — no server, no login, no dependencies
- UCLA branding

---

## Files

| File | Description |
|------|-------------|
| `grapes-fellowship-finder.html` | The main app — open this in any browser |
| `data/fellowships_master.json` | All 266 enriched fellowship records |
| `scripts/01_extract.py` | Extracts fellowship records from the DGE Excel spreadsheet |
| `scripts/02_enrich.py` | Template for enriching fellowship records via web scraping |
| `scripts/03_merge_and_rebuild.py` | Merges enriched data and rebuilds the HTML |

---

## How to deploy (GitHub Pages)

1. Push this repo to GitHub
2. Go to **Settings → Pages**
3. Source: **Deploy from a branch → main → / (root)**
4. Your tool will be live at:
   `https://[your-username].github.io/grapes-search-plus/grapes-fellowship-finder.html`

---

## How to update

The fellowship data is embedded directly in the HTML file as a JSON array (`const DATA=[...]`).
To update deadlines or add new fellowships:

1. Edit `data/fellowships_master.json`
2. Run `scripts/03_merge_and_rebuild.py` to regenerate the HTML
3. Commit and push — GitHub Pages auto-deploys

For a full refresh from the DGE spreadsheet:
1. Export the latest spreadsheet as `.xlsx`
2. Run `scripts/01_extract.py` to regenerate the base records
3. Run `scripts/02_enrich.py` to fetch updated details from official fellowship websites
4. Run `scripts/03_merge_and_rebuild.py` to rebuild the HTML

---

## Data source

Base fellowship list from the UCLA DGE GRAPES database.
Fellowship details (descriptions, eligibility, deadlines, official URLs) scraped from official fellowship websites.

---

*Built for UCLA DGE | Created by Daylor Williams*
