# GRAPES Search+

**Graduate fellowship, grant, and award finder for UCLA graduate students.**
Created by Daylor Williams for the UCLA Division of Graduate Education (DGE).

**[Open GRAPES Search+ →](https://daylorwilliams5.github.io/grapes-search-plus/grapes-fellowship-finder.html)**

![GRAPES Search+ search page](docs/screenshot.png)

## What it is

GRAPES Search+ is a searchable database of graduate fellowships, grants, and awards, built from the UCLA DGE GRAPES dataset. Students can search in plain language ("psychology dissertation", "conference travel") and narrow results by deadline, award type, field of study, and application season.

Listings reviewed by DGE this cycle are marked verified. The rest are shown with an "Unverified listing" note so students know to double-check the details.

## Features

- **Plain-language search.** Related terms are included automatically (for example, "psychology" also finds behavioral, cognitive, and social science awards), and matches are highlighted.
- **Filters with live counts** for deadline status, award type, field of study, application season, and verified listings.
- **Recurring deadlines.** Most awards open every year, so when a listed deadline has passed, the next one is estimated from it and labeled as an estimate instead of the listing being hidden.
- **Detail panel** for each award, with the sponsor, amount, eligibility, and a link to the official page.
- **Saved list.** Students can bookmark awards; the list is stored in their browser.
- **Shareable searches.** Keywords and filters are kept in the page address.
- **Single HTML file.** No server, login, or build step. Fonts load from Google Fonts, with system fonts as a fallback.

## Updating the data

The data refreshes automatically at the start of each application cycle (September 1, January 1, March 15, and June 15) through a GitHub Actions workflow. It can also be run by hand from the **Actions** tab, optionally with a link to the latest GRAPES spreadsheet.

Each run does the following:

1. **Extract** records from the GRAPES `.xlsx` file in `data/`.
2. **Merge** them into the existing data. Deadlines, season, and status come from the spreadsheet. Descriptions, eligibility, amounts, and links are kept. New awards are added, and awards whose deadlines are more than three years old are removed.
3. **Rebuild** the HTML page and commit the changes.

To run the same steps locally:

```bash
pip install pandas openpyxl python-dateutil

python scripts/01_extract.py \
  --input "data/GRAPES AnnLog.xlsx" \
  --output data/fellowships_base.json

python scripts/03_merge_and_rebuild.py \
  --data data/fellowships_master.json \
  --base data/fellowships_base.json \
  --template grapes-fellowship-finder.html \
  --output grapes-fellowship-finder.html
```

New awards added this way have only the basic details from the spreadsheet. `scripts/02_enrich.py` is a starting point for filling in descriptions, eligibility, and links from the sponsors' websites.

## Files

| File | Description |
|------|-------------|
| `grapes-fellowship-finder.html` | The app, with the data embedded. Open it in any browser. |
| `data/fellowships_master.json` | All fellowship records, including descriptions and eligibility |
| `scripts/01_extract.py` | Extracts records from the DGE GRAPES spreadsheet |
| `scripts/02_enrich.py` | Template for adding descriptions and eligibility from sponsor websites |
| `scripts/03_merge_and_rebuild.py` | Merges new spreadsheet records into the data and rebuilds the HTML |
| `.github/workflows/update-fellowships.yml` | Scheduled update that runs the steps above |

## Data source

The list of fellowships comes from the UCLA DGE GRAPES database. Descriptions, eligibility, deadlines, and official links were gathered from each sponsor's website. Students should always confirm details on the official page before applying.

---

*Built for UCLA DGE by Daylor Williams*
