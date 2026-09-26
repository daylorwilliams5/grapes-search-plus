"""
03_merge_and_rebuild.py
=======================
Merges enriched fellowship data and rebuilds the self-contained HTML app.

Usage:
    python 03_merge_and_rebuild.py \
        --data ../data/fellowships_master.json \
        [--base ../data/fellowships_base.json] \
        --template ../grapes-fellowship-finder.html \
        --output ../grapes-fellowship-finder.html

With --base, fresh records from 01_extract.py are merged into the master
data first: status comes from the spreadsheet, a deadline is taken only when
it's newer than the one on file, rows marked deleted are removed, and rows
not yet on the site are written to data/new_from_spreadsheet.json for
research instead of being published. Record numbers in
data/excluded_ids.json are never re-added.

The script replaces the `const DATA=[...]` block in the HTML with
the updated JSON data, preserving all app logic and styling.

Requirements:
    pip install python-dateutil
"""

import json
import re
import argparse
import datetime
from pathlib import Path


AWARD_TYPE_MAP = {
    "postdoctoral fellowship": "Postdoctoral Fellowship",
    "postdoctoral": "Postdoctoral Fellowship",
    "post-doctoral": "Postdoctoral Fellowship",
    "postdoc": "Postdoctoral Fellowship",
    "dissertation fellowship": "Dissertation Fellowship",
    "dissertation": "Dissertation Fellowship",
    "predoctoral": "Dissertation Fellowship",
    "pre-doctoral": "Dissertation Fellowship",
    "research grant": "Research Grant",
    "grant": "Research Grant",
    "travel grant": "Travel Grant",
    "travel award": "Travel Grant",
    "travel": "Travel Grant",
    "internship": "Internship",
    "scholarship": "Scholarship",
    "fellowship": "Fellowship",
    "other": "Other",
}


def normalize_award_type(t):
    if not t:
        return ""
    tl = t.lower().strip()
    if tl in AWARD_TYPE_MAP:
        return AWARD_TYPE_MAP[tl]
    for k, v in AWARD_TYPE_MAP.items():
        if k in tl:
            return v
    return t


def parse_deadline(dl_str):
    if not dl_str:
        return None
    from dateutil import parser as dparser
    try:
        return dparser.parse(dl_str, fuzzy=True).date()
    except Exception:
        return None


def load_audit(data_path):
    """Record numbers removed after the last audit, and the audit date."""
    path = Path(data_path).with_name("excluded_ids.json")
    if not path.exists():
        return set(), ""
    with open(path) as f:
        audit = json.load(f)
    return {r["id"] for r in audit["records"]}, audit.get("audited", "")


def merge_base(records, base, excluded, audited=""):
    """Merge fresh spreadsheet rows (from 01_extract.py) into the site data.

    - Rows marked deleted in the spreadsheet are removed from the site.
    - A listing's deadline is replaced only when staff updated that row after
      the last audit (its "Last Updated" date), its own date has passed or is
      missing, and the spreadsheet's date is newer. Dates confirmed against
      sponsor sites aren't overwritten by older projections, and rolling
      programs keep no date.
    - Status (verified / unverified) follows the spreadsheet.
    - Rows not on the site are returned separately for research; they are
      not published, since the spreadsheet has no descriptions or links.
    """
    today = datetime.date.today().isoformat()
    by_id = {}
    for r in records:
        by_id.setdefault(r["id"], []).append(r)
    # The spreadsheet can list a record twice; prefer the published row
    rows = {}
    for b in base:
        if b["id"] not in rows or rows[b["id"]]["status"] != "Published":
            rows[b["id"]] = b
    deleted, updated, new = set(), 0, []
    for b in rows.values():
        rid = b["id"]
        if b["status"] == "Deleted":
            if rid in by_id:
                deleted.add(rid)
            continue
        if rid not in by_id:
            if rid not in excluded:
                new.append(b)
            continue
        for r in by_id[rid]:
            changed = r["status"] != b["status"]
            r["status"] = b["status"]
            current = r.get("deadlineSort") or "9999-12-31"
            rolling = current.startswith("9999") and r.get("season") == "Open/Rolling"
            stale = current < today or current.startswith("9999")
            fresh = b.get("updated", "") > audited
            if b["deadline"] and fresh and stale and not rolling and \
               (current.startswith("9999") or b["deadlineSort"] > current):
                for k in ("deadline", "deadlineSort", "season"):
                    r[k] = b[k]
                changed = True
            updated += changed
    records = [r for r in records if r["id"] not in deleted]
    print(f"Merged spreadsheet: {updated} listings updated, {len(deleted)} removed as deleted, "
          f"{len(new)} new rows need research")
    return records, new


def process_records(records):
    """Normalize award types and recompute deadline flags. Nothing is removed:
    the app estimates the next cycle from past deadlines, and listings come
    off the site only when the spreadsheet marks them deleted."""
    today = datetime.date.today()
    for r in records:
        if r.get("awardType"):
            r["awardType"] = normalize_award_type(r["awardType"])
        dl_date = parse_deadline(r.get("deadline"))
        if dl_date:
            r["deadlineSort"] = dl_date.strftime("%Y-%m-%d")
            r["deadlinePassed"] = dl_date < today
            r["sortTier"] = 2 if dl_date < today else 0
        else:
            r["deadline"] = ""
            r["deadlineSort"] = "9999-12-31"
            r["deadlinePassed"] = False
            r["sortTier"] = 1
    print(f"Processed: {len(records)} records")
    return records


def rebuild_html(data, html_path, output_path):
    with open(html_path) as f:
        html = f.read()

    # Replace the DATA line. Compact JSON has no raw newlines, so the data
    # always ends at the end of its line; "</" is escaped so text in the
    # data can't close the <script> tag.
    new_data_js = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    start = html.index("const DATA=")
    end = html.index("\n", start)
    html = html[:start] + "const DATA=" + new_data_js + ";" + html[end:]

    with open(output_path, "w") as f:
        f.write(html)
    print(f"Rebuilt HTML: {output_path} ({len(html):,} bytes)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Path to fellowships JSON data file")
    parser.add_argument("--base", help="Optional fresh records from 01_extract.py to merge in")
    parser.add_argument("--template", required=True, help="Path to current HTML file (used as template)")
    parser.add_argument("--output", required=True, help="Output HTML path")
    args = parser.parse_args()

    print(f"Loading data from {args.data}...")
    with open(args.data) as f:
        records = json.load(f)
    print(f"Loaded {len(records)} records")

    if args.base:
        with open(args.base) as f:
            excluded, audited = load_audit(args.data)
            records, new = merge_base(records, json.load(f), excluded, audited)
        new_path = Path(args.data).with_name("new_from_spreadsheet.json")
        with open(new_path, "w") as f:
            json.dump(new, f, indent=2)
        print(f"Rows to research before adding: {new_path}")

    records = process_records(records)

    # Save updated master data
    data_path = Path(args.data)
    with open(data_path, "w") as f:
        json.dump(records, f, indent=2, default=str)
    print(f"Updated master data saved to {data_path}")

    rebuild_html(records, args.template, args.output)
    print("Done.")


if __name__ == "__main__":
    main()
