"""
01_extract.py
=============
Extracts fellowship records from the UCLA DGE GRAPES Excel spreadsheet
and produces a base JSON file for 03_merge_and_rebuild.py --base.

Reads the "GRAPES Updates" sheet (or the first sheet if it's missing).
Columns are matched by the start of their header, so small wording
changes like "STATUS (published, pending, delete, deleted)" still work.

Usage:
    python 01_extract.py --input "GRAPES AnnLog.xlsx" --output ../data/fellowships_base.json

Requirements:
    pip install pandas openpyxl
"""

import pandas as pd
import json
import argparse
import datetime
from pathlib import Path


# Header prefixes for each field, checked in order
COLUMNS = {
    "id": ["RECORD NUMBER", "RECORD_NUMBER", "ID", "REC NUM"],
    "title": ["AWARD TITLE", "TITLE"],
    "agency1": ["AGENCY 1", "AGENCY", "SPONSOR"],
    "agency2": ["AGENCY 2", "CO-SPONSOR", "CO SPONSOR"],
    "period": ["APPLICATION PERIOD", "SEASON", "REVIEW PERIOD"],
    "deadline": ["DEADLINE"],
    "status": ["STATUS (", "STATUS"],
    "active": ["STATUS:", "ACTIVE"],
    "updated": ["LAST UPDATED", "UPDATED"],
}


def find_columns(columns):
    headers = {c: str(c).strip().upper().replace("_", " ") for c in columns}
    found = {}
    for field, prefixes in COLUMNS.items():
        for p in prefixes:
            match = next((c for c, h in headers.items() if h.startswith(p) and c not in found.values()), None)
            if match is not None:
                found[field] = match
                break
    return found


def cell(row, cols, field):
    """Cell text, or '' for missing/empty cells."""
    col = cols.get(field)
    if col is None:
        return ""
    v = row[col]
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    return str(v).strip()


def normalize_season(val):
    v = (val or "").lower()
    for s in ["Fall", "Winter", "Spring", "Summer"]:
        if s.lower() in v:
            return s
    return "Open/Rolling"


def normalize_status(val):
    v = (val or "").strip().upper()
    if v.startswith("DELETE"):
        return "Deleted"
    if v.startswith("PENDING"):
        return "Pending"
    return "Published"


def parse_deadline(dl):
    if dl is None or (not isinstance(dl, str) and pd.isna(dl)):
        return None
    dt = pd.to_datetime(dl, errors="coerce")
    return None if pd.isna(dt) else dt.date()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to DGE GRAPES .xlsx file")
    parser.add_argument("--output", default="../data/fellowships_base.json")
    args = parser.parse_args()

    today = datetime.date.today()

    xl = pd.ExcelFile(args.input)
    print(f"Sheets found: {xl.sheet_names}")
    sheet = next((s for s in xl.sheet_names if s.strip().lower() == "grapes updates"), xl.sheet_names[0])
    df = pd.read_excel(args.input, sheet_name=sheet)
    print(f"Loaded {len(df)} rows from sheet '{sheet}'")

    cols = find_columns(df.columns)
    print(f"Columns used: {cols}")
    missing = [f for f in ("id", "title", "deadline") if f not in cols]
    if missing:
        raise SystemExit(f"Spreadsheet is missing required columns: {missing}")

    records = []
    for _, row in df.iterrows():
        rid = pd.to_numeric(row[cols["id"]], errors="coerce")
        title = cell(row, cols, "title")
        if pd.isna(rid) or not title:
            continue

        dl = parse_deadline(row[cols["deadline"]])
        updated = parse_deadline(row[cols["updated"]]) if "updated" in cols else None
        status = normalize_status(cell(row, cols, "status"))
        if cell(row, cols, "active").upper().startswith("D"):
            status = "Deleted"

        records.append({
            "id": int(rid),
            "title": title,
            "agency1": cell(row, cols, "agency1"),
            "agency2": cell(row, cols, "agency2"),
            "season": normalize_season(cell(row, cols, "period")),
            "deadline": dl.strftime("%b %d, %Y") if dl else "",
            "deadlineSort": dl.isoformat() if dl else "9999-12-31",
            "deadlinePassed": bool(dl and dl < today),
            "sortTier": (2 if dl < today else 0) if dl else 1,
            "status": status,
            "officialUrl": "",
            "description": "",
            "eligibility": "",
            "amount": "",
            "awardType": "",
            "enriched": False,
            "updated": updated.isoformat() if updated else "",
        })

    print(f"Extracted {len(records)} records "
          f"({sum(r['status'] == 'Deleted' for r in records)} marked deleted)")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(records, f, indent=2)
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
