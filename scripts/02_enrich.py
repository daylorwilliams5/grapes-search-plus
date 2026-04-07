"""
02_enrich.py
============
Enriches fellowship records by fetching descriptions, eligibility,
deadlines, and official URLs from fellowship websites.

Processes records in batches. Can be re-run safely — already-enriched
records are skipped unless --force is passed.

Usage:
    python 02_enrich.py --input ../data/fellowships_base.json \
                        --output ../data/fellowships_enriched.json \
                        --batch-size 50

Requirements:
    pip install requests beautifulsoup4 openai
    Set OPENAI_API_KEY or use a local model for the extraction step.

Note: This script uses web scraping. Some fellowship pages may block
automated requests. Rate limiting is applied automatically.
"""

import json
import time
import re
import argparse
import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Install dependencies: pip install requests beautifulsoup4")
    raise


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UCLA-DGE-FellowshipBot/1.0; research@ucla.edu)"
}

AWARD_TYPE_MAP = {
    "postdoctoral fellowship": "Postdoctoral Fellowship",
    "postdoctoral": "Postdoctoral Fellowship",
    "post-doctoral": "Postdoctoral Fellowship",
    "dissertation fellowship": "Dissertation Fellowship",
    "dissertation": "Dissertation Fellowship",
    "predoctoral": "Dissertation Fellowship",
    "research grant": "Research Grant",
    "travel grant": "Travel Grant",
    "travel award": "Travel Grant",
    "internship": "Internship",
    "scholarship": "Scholarship",
    "fellowship": "Fellowship",
}


def normalize_award_type(raw):
    if not raw:
        return ""
    rl = raw.lower().strip()
    for k, v in AWARD_TYPE_MAP.items():
        if k in rl:
            return v
    return raw.title()


def fetch_page(url, timeout=10):
    """Fetch a URL and return BeautifulSoup object, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  Fetch failed for {url}: {e}")
    return None


def extract_text_blocks(soup, max_chars=2000):
    """Extract meaningful text from a BeautifulSoup page."""
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def find_deadline(text):
    """Try to extract a deadline from page text."""
    patterns = [
        r"(?:deadline|due|applications?\s+(?:due|close[sd]?))[:\s]+([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})",
        r"(?:deadline|due)[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
        r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def google_search_url(title, agency):
    """Build a Google search fallback URL."""
    q = f"{title} {agency} fellowship".replace(" ", "+")
    return f"https://www.google.com/search?q={q}"


def enrich_record(record):
    """Enrich a single record. Returns updated record dict."""
    url = record.get("officialUrl", "")
    title = record.get("title", "")
    agency = record.get("agency1", "")

    print(f"  [{record['id']}] {title[:50]}...")

    # Try to fetch the official page
    soup = None
    if url and "google.com" not in url:
        soup = fetch_page(url)
        time.sleep(0.5)  # polite rate limiting

    if not soup:
        # Try a Google search for the URL
        search_url = google_search_url(title, agency)
        record["officialUrl"] = search_url
        print(f"    Could not fetch page, using search fallback")
        return record

    page_text = extract_text_blocks(soup)

    # Extract deadline if not already set or if passed
    if not record.get("deadline") or record.get("deadlinePassed"):
        dl = find_deadline(page_text)
        if dl:
            record["deadline"] = dl
            print(f"    Found deadline: {dl}")

    # Extract description (first 300 chars of meaningful content)
    if not record.get("description"):
        # Try meta description first
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            record["description"] = meta["content"][:400].strip()
        else:
            # Use first paragraph
            for p in soup.find_all(["p", "div"], limit=10):
                text = p.get_text(strip=True)
                if len(text) > 80:
                    record["description"] = text[:400]
                    break

    record["enriched"] = True
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--force", action="store_true", help="Re-enrich already-enriched records")
    parser.add_argument("--start", type=int, default=0, help="Start from record index N")
    args = parser.parse_args()

    with open(args.input) as f:
        records = json.load(f)

    to_enrich = [
        r for r in records
        if not r.get("enriched") or args.force
    ][args.start:args.start + args.batch_size]

    print(f"Enriching {len(to_enrich)} records (batch size {args.batch_size})...")

    enriched_ids = set()
    results = []
    for i, rec in enumerate(to_enrich):
        print(f"[{i+1}/{len(to_enrich)}]", end=" ")
        updated = enrich_record(dict(rec))
        results.append(updated)
        enriched_ids.add(updated["id"])

    # Merge back into full records list
    lookup = {r["id"]: r for r in results}
    final = [lookup.get(r["id"], r) for r in records]

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(final, f, indent=2, default=str)

    print(f"\nDone. {len(results)} records enriched.")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
