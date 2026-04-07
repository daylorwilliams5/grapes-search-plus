"""
03_merge_and_rebuild.py
=======================
Merges enriched fellowship data and rebuilds the self-contained HTML app.

Usage:
    python 03_merge_and_rebuild.py \
        --data ../data/fellowships_master.json \
        --template ../grapes-fellowship-finder.html \
        --output ../grapes-fellowship-finder.html

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


CUTOFF_YEARS = 3  # Remove records with deadlines older than this

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


def process_records(records):
    today = datetime.date.today()
    cutoff = today.replace(year=today.year - CUTOFF_YEARS)

    out = []
    removed = 0

    for r in records:
        # Remove incomplete + stale records
        if not r.get("description") and not r.get("eligibility") and r.get("sortTier") == 2:
            removed += 1
            continue

        # Normalize award type
        if r.get("awardType"):
            r["awardType"] = normalize_award_type(r["awardType"])

        # Recompute sort tier from deadline
        dl_date = parse_deadline(r.get("deadline"))
        if dl_date:
            if dl_date < cutoff:
                removed += 1
                continue
            passed = dl_date < today
            r["deadlinePassed"] = passed
            r["deadlineSort"] = dl_date.strftime("%Y-%m-%d")
            r["sortTier"] = 2 if passed else 0
        elif not r.get("deadline"):
            r["sortTier"] = 1
            r["deadlineSort"] = "9999-12-31"
            r["deadlinePassed"] = False

        out.append(r)

    print(f"Processed: {len(out)} records kept, {removed} removed")
    return out


def rebuild_html(data, html_path, output_path):
    with open(html_path) as f:
        html = f.read()

    # Replace the DATA block
    new_data_js = json.dumps(data, separators=(",", ":"))
    start = html.index("const DATA=[")
    end = html.index("];", start) + 2
    html = html[:start] + "const DATA=" + new_data_js + ";" + html[end:]

    with open(output_path, "w") as f:
        f.write(html)
    print(f"Rebuilt HTML: {output_path} ({len(html):,} bytes)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Path to fellowships JSON data file")
    parser.add_argument("--template", required=True, help="Path to current HTML file (used as template)")
    parser.add_argument("--output", required=True, help="Output HTML path")
    args = parser.parse_args()

    print(f"Loading data from {args.data}...")
    with open(args.data) as f:
        records = json.load(f)
    print(f"Loaded {len(records)} records")

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
