"""
01_extract.py
=============
Extracts fellowship records from the UCLA DGE GRAPES Excel spreadsheet
and produces a base JSON file ready for enrichment.

Usage:
    python 01_extract.py --input "GRAPES AnnLog.xlsx" --output ../data/fellowships_base.json

Requirements:
    pip install pandas openpyxl
"""

import pandas as pd
import json
import argparse
import datetime
import re
from pathlib import Path


def normalize_season(val):
    if not val or pd.isna(val):
        return "Open/Rolling"
    v = str(val).strip()
    for s in ["Fall", "Winter", "Spring", "Summer"]:
        if s.lower() in v.lower():
            return s
    return "Open/Rolling"


def parse_deadline(dl):
    if pd.isna(dl):
        return None, None, None
    if isinstance(dl, datetime.datetime):
        return dl.date(), dl.strftime("%b %d, %Y"), dl.strftime("%Y-%m-%d")
    try:
        dt = pd.to_datetime(str(dl), errors="coerce")
        if pd.notna(dt):
            return dt.date(), dt.strftime("%b %d, %Y"), dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None, str(dl).strip(), "9999-12-31"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to DGE GRAPES .xlsx file")
    parser.add_argument("--output", default="../data/fellowships_base.json")
    parser.add_argument("--cutoff-years", type=int, default=3,
                        help="Skip fellowships with deadlines older than this many years")
    args = parser.parse_args()

    today = datetime.date.today()
    cutoff = today.replace(year=today.year - args.cutoff_years)

    # Load spreadsheet — try multiple sheet names
    xl = pd.ExcelFile(args.input)
    print(f"Sheets found: {xl.sheet_names}")
    sheet = next((s for s in xl.sheet_names if "annual" in s.lower() or "fellow" in s.lower()), xl.sheet_names[0])
    df = pd.read_excel(args.input, sheet_name=sheet)
    print(f"Loaded {len(df)} rows from sheet '{sheet}'")

    # Normalize column names
    df.columns = [str(c).strip().upper().replace(" ", "_") for c in df.columns]
    print(f"Columns: {list(df.columns)}")

    # Parse deadlines
    if "DEADLINE" in df.columns:
        df["DEADLINE"] = pd.to_datetime(df["DEADLINE"], errors="coerce")

    records = []
    skipped = 0

    for _, row in df.iterrows():
        # Get ID
        rid = row.get("RECORD_NUMBER") or row.get("ID") or row.get("REC_NUM") or None
        if pd.isna(rid) if rid is not None else True:
            continue
        rid = int(rid)

        title = str(row.get("TITLE") or row.get("AWARD_TITLE") or "").strip()
        if not title:
            continue

        agency1 = str(row.get("AGENCY") or row.get("SPONSOR") or row.get("AGENCY_1") or "").strip()
        agency2 = str(row.get("AGENCY_2") or row.get("CO_SPONSOR") or "").strip()
        season = normalize_season(row.get("SEASON") or row.get("REVIEW_PERIOD"))
        status = str(row.get("STATUS") or "Published").strip()

        # Deadline
        dl_raw = row.get("DEADLINE")
        dl_date, dl_str, dl_sort = parse_deadline(dl_raw)

        # Skip too-old deadlines
        if dl_date and dl_date < cutoff:
            skipped += 1
            continue

        # Determine sort tier
        dl_passed = bool(dl_date and dl_date < today)
        if dl_date and not dl_passed:
            sort_tier = 0  # upcoming
        elif not dl_date:
            sort_tier = 1  # no deadline
        else:
            sort_tier = 2  # recently passed

        records.append({
            "id": rid,
            "title": title,
            "agency1": agency1,
            "agency2": agency2 if agency2 and agency2 != "nan" else "",
            "season": season,
            "deadline": dl_str,
            "deadlineSort": dl_sort or "9999-12-31",
            "deadlinePassed": dl_passed,
            "sortTier": sort_tier,
            "status": status if status != "nan" else "Published",
            "officialUrl": "",
            "description": "",
            "eligibility": "",
            "amount": "",
            "awardType": "",
            "enriched": False,
        })

    print(f"Extracted: {len(records)} records | Skipped (too old): {skipped}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(records, f, indent=2, default=str)
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
