# GRAPES Search+

**Graduate fellowship, grant, and award finder for UCLA graduate students.**
Created by Daylor Williams for the UCLA Division of Graduate Education (DGE).

**[Open GRAPES Search+ →](https://daylorwilliams5.github.io/grapes-search-plus/grapes-fellowship-finder.html?v=2)**

![GRAPES Search+ search page](docs/screenshot.png)

## What it is

GRAPES Search+ is a searchable database of 400+ graduate fellowships, grants, and awards, built from the UCLA DGE GRAPES dataset. Students can search in plain language ("psychology dissertation", "conference travel") and narrow results by deadline, award type, field of study, and application season.

Listings reviewed by DGE this cycle are marked verified. The rest are shown with an "Unverified listing" note so students know to double-check the details.

## Features

- **Plain-language search.** Related terms are included automatically (for example, "psychology" also finds behavioral, cognitive, and social science awards), and matches are highlighted.
- **Filters with live counts** for deadline status, award type, degree stage, field of study, citizenship, application season, and verified listings.
- **Understands who you are.** Phrases like "international student", "not a US citizen", "postdoc", "master's student" or "PhD candidate" in the search box turn on the matching filter, shown as a chip, instead of being searched as keywords.
- **Recurring deadlines.** Most awards open every year, so when a listed deadline has passed, the next one is estimated from it and labeled as an estimate instead of the listing being hidden.
- **Detail panel** for each award, with the sponsor, amount, eligibility, and a link to the official page.
- **Saved list.** Students can bookmark awards; the list is stored in their browser.
- **Shareable searches.** Keywords and filters are kept in the page address.
- **Single HTML file.** No server, login, or build step. Fonts load from Google Fonts, with system fonts as a fallback.

## Updating the data

A GitHub Actions workflow merges the latest GRAPES spreadsheet into the site at the start of each application cycle (September 1, January 1, March 15, and June 15). To use it, either commit the spreadsheet to `data/` (the newest `.xlsx` there is used) or run the workflow by hand from the **Actions** tab with a direct download link. With neither, the run does nothing.

Each run does the following:

1. **Extract** the rows from the spreadsheet's "GRAPES Updates" sheet.
2. **Merge** them into the site data:
   - Listing status (verified or unverified) follows the spreadsheet.
   - A deadline from the spreadsheet is used only if staff updated that row after the last audit, the listing's own date has passed, and the spreadsheet's date is newer. This keeps deadlines that were confirmed on sponsor sites.
   - Rows marked deleted in the spreadsheet come off the site.
   - Rows not yet on the site are saved to `data/new_from_spreadsheet.json` to be researched, rather than published without a description or link.
   - Record numbers in `data/excluded_ids.json` (programs removed as discontinued, paused, or duplicate) are never added back.
3. **Rebuild** the page and commit the changes.

Listings are never removed just because their deadline is old. The page estimates the next deadline from the last one for a year and a half, then asks students to check the sponsor's page.

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

`scripts/02_enrich.py` is a starting point for filling in descriptions, eligibility, and links for new rows from the sponsors' websites.

## Checking listings with the research agent

Instead of scraping sponsor sites, a Claude research agent can check listings and propose updates. For each listing it searches the web, reads the sponsor's pages, and reports the current deadline, award amount, eligibility, and official link. Every value must come with the page it came from and a quote copied from that page. The script then checks each quote against the page text and drops any value whose quote isn't on the page or doesn't contain the value.

Checked changes are never published directly. The **Agent Research** workflow opens a pull request with the changes and a report of the evidence, and DGE staff review and merge it. The agent only:

- moves a deadline later (never earlier),
- fills in an amount when a listing has none,
- replaces a link when the current one is broken.

It doesn't change a listing's status in the DGE spreadsheet. Eligibility conflicts and programs that look discontinued are listed in the report for staff to handle.

**Checking unverified listings.** Run Agent Research with **pending** selected to check listings DGE hasn't published this cycle, about 50 at a time. When the agent confirms a current deadline on the sponsor's page and the pull request is merged, the listing is marked as checked on that date. The site then treats it as verified for six months: the "Unverified listing" label goes away and the details say when the deadline was checked. Listings the agent couldn't confirm stay unverified and are skipped for 30 days, so the next batch moves on to new ones. Merge (or close) each batch's pull request before running the next; the workflow stops with a message if one is still open, since a new batch can't see the last one's results and would research the same listings again. Use the reports to mark the same listings published in the GRAPES admin system.

To set it up, add an `ANTHROPIC_API_KEY` repository secret and turn on **Allow GitHub Actions to create and approve pull requests** under Settings → Actions → General. Then run **Agent Research** from the **Actions** tab. By default it checks the 20 listings whose deadlines passed most recently, using Claude Haiku 5.5, the cheapest model. Its price goes up fivefold for prompts over 100,000 tokens, so each listing is limited to 3 searches and 5 pages of up to 10,000 tokens. Pick Sonnet or Opus in the run form for harder listings; they're more thorough and cost more. Each run prints its token use and an estimated cost.

To run it locally:

```bash
pip install anthropic requests beautifulsoup4 python-dateutil pypdf
export ANTHROPIC_API_KEY=...

python scripts/02_agent_research.py --limit 5            # report only
python scripts/02_agent_research.py --ids 97,412 --apply # write changes to the data
python scripts/02_agent_research.py --limit 5 --model sonnet  # a more thorough model
```

The report is written to `data/agent_report.md`. Tests for the evidence checks run with `python -m pytest tests/` and don't call the API.

## Student assistant (local prototype)

`assistant/server.py` runs the search page with two changes:

- **The search box asks the assistant.** Students describe their degree, field, citizenship, and what the funding is for, and the assistant's picks appear as **Best fits** above the full list, each with a line on why it fits. Follow-up questions build on the earlier ones until **Start over**. The full list stays below with every filter, and the filters selected on the page are sent with each question. The assistant can only pick listings by record number; the page shows them with its usual cards, so the deadlines, amounts, and links come from the data, not from the AI. It uses Claude Sonnet 5.5, with the list of listings (about 60,000 tokens) cached between questions.
- **"Check the sponsor's page now"** in every listing's details. It runs the research agent on that one listing (Claude Haiku 5.5, about 1 cent and 20-40 seconds) and shows what the sponsor's page says today, with quotes and links.

```bash
python -m pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python assistant/server.py      # then open http://localhost:8000
```

Questions aren't stored. It's a demo for staff: it sends questions to the Claude API, so don't open it to students until IT has approved where it runs. Tests: `python -m pytest tests/`.

### Online staff demo (Render)

`render.yaml` sets up the assistant as a free [Render](https://render.com) web service, so staff can try it from a link instead of running it on their own computer.

1. In Render, choose **New → Blueprint** and pick this repository.
2. Enter the two secrets it asks for: `ANTHROPIC_API_KEY`, and `DEMO_PASSCODE` (any passcode to share with staff).
3. When it's deployed, open `https://<service>.onrender.com/?demo` and enter the passcode. The browser tab remembers it until it's closed.

Without `?demo` and the passcode, the page is the ordinary keyword search with no assistant (as on GitHub Pages), and the API refuses questions. Each visitor can ask 40 questions and run 15 sponsor checks an hour, with 400 requests a day in all, to cap the cost. The free plan sleeps after 15 minutes without visits, so the first visit after that takes about 30 seconds. The server won't start online without `DEMO_PASSCODE`; setting `PUBLIC=1` instead opens it to everyone, which should wait until IT has approved it.

## Citizenship and degree-stage tags

Each rebuild tags every listing with who can apply, read from its eligibility text by `scripts/eligibility_tags.py`: whether it's limited to U.S. citizens and permanent residents, and which degree stages (master's and professional, doctoral before candidacy, dissertation stage, postdoctoral) it's open to. Listings that don't say are included in every filter. The tags come from pattern matching, so some will be wrong: correct a listing in `data/eligibility_overrides.json` and it stays corrected. To review all tags, run `python scripts/eligibility_tags.py`.

## Turning on "Submit a fellowship"

The page has a form for suggesting new fellowships, but its button stays hidden until it's connected to a Google Form. To turn it on, create a Google Form with fields for the link, name, notes, and extracted details, then replace `FORM_ID` and the four `entry.*` values in `GFORM_URL` and `GFORM_ENTRIES` near the end of `grapes-fellowship-finder.html`.

## Files

| File | Description |
|------|-------------|
| `grapes-fellowship-finder.html` | The app, with the data embedded. Open it in any browser. |
| `index.html` | Sends the site's root address to the app |
| `data/fellowships_master.json` | All fellowship records, including descriptions and eligibility |
| `data/excluded_ids.json` | Record numbers removed after the September 2026 audit, with reasons |
| `data/new_from_spreadsheet.json` | Spreadsheet rows waiting to be researched (written by each update) |
| `scripts/01_extract.py` | Extracts records from the DGE GRAPES spreadsheet |
| `scripts/02_enrich.py` | Template for adding descriptions and eligibility from sponsor websites |
| `scripts/02_agent_research.py` | Checks listings against sponsor sites with a research agent and proposes verified updates |
| `scripts/make_agent_updates.py` | Builds a spreadsheet of the research agent's findings to enter in the GRAPES admin system |
| `scripts/make_worklist.py` | Builds a spreadsheet for checking listings by hand, sorted by upcoming deadline |
| `scripts/make_update_list.py` | Builds a spreadsheet of the deadlines and links confirmed in the September audit that differ from the DGE spreadsheet |
| `worklists/` | Manual update worklists |
| `scripts/eligibility_tags.py` | Tags listings with citizenship limits and degree stages for the filters |
| `data/eligibility_overrides.json` | Staff corrections to those tags |
| `scripts/03_merge_and_rebuild.py` | Merges spreadsheet records into the data and rebuilds the HTML |
| `.github/workflows/update-fellowships.yml` | Scheduled update that runs the steps above |
| `.github/workflows/agent-research.yml` | Runs the research agent and opens a pull request with its changes |
| `assistant/` | Prototype of the student assistant (server, search box and Best fits) |
| `render.yaml`, `requirements.txt` | Render setup for the online staff demo |
| `tests/` | Tests for the research agent and the assistant prototype |
| `grapes-system-design.md`, `chat-system-design.md` | Design notes |

## Data source

The list of fellowships comes from the UCLA DGE GRAPES database. Descriptions, eligibility, deadlines, and official links were gathered from each sponsor's website. Students should always confirm details on the official page before applying.

---

*Built for UCLA DGE by Daylor Williams*
