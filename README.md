# GRAPES Search+

**Graduate fellowship, grant & award finder for UCLA graduate students.**
Created by Daylor Williams for the UCLA Division of Graduate Education (DGE).

---

## What it is

GRAPES Search+ is a self-contained, searchable database of **350+ verified graduate fellowships**, grants, and awards curated from the UCLA DGE GRAPES dataset. Students can find relevant funding by searching natural language queries ("psychology dissertation", "travel grant conference") or by filtering by field of study, award type, and season.

Live demo: https://daylorwilliams5.github.io/grapes-search-plus/grapes-fellowship-finder.html

---

## Features

- Natural language search with synonym expansion (e.g. "psychology" → behavioral, cognitive, social science)
- Field of Study filter: Social Sciences, STEM, Humanities, Health, Arts, Law & Policy, Education, International
- Award Type filter: Postdoctoral, Dissertation, Research Grant, Travel Grant, Scholarship, Internship
- Season filter: Fall, Winter, Spring, Summer, Open/Rolling
- Defaults to active/upcoming deadlines — past deadlines hidden by toggle
- Fully self-contained single HTML file — no server, no login, no dependencies

---

## Files

| File | Description |
|------|-------------|
| `grapes-fellowship-finder.html` | The main app — open this in any browser |
| `data/fellowships_master.json` | All 363 enriched fellowship records |
| `scripts/01_extract.py` | Extracts fellowship records from the DGE Excel spreadsheet |
| `scripts/02_enrich.py` | Template for enriching fellowship records via web scraping |
| `scripts/03_merge_and_rebuild.py` | Merges enriched data and rebuilds the HTML |

---

## Data source

Base fellowship list from the UCLA DGE GRAPES database.
Fellowship details (descriptions, eligibility, deadlines, official URLs) scraped from official fellowship websites.

---

*Built for UCLA DGE | Created by Daylor Williams*
