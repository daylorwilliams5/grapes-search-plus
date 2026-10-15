"""
eligibility_tags.py
===================
Tags each listing with who can apply, from its eligibility text, for the
search page's citizenship and degree-stage filters.

    citizenship: "us"    U.S. citizens / nationals / permanent residents only
                 "open"  says non-U.S. citizens can apply
                 "other" limited to citizens of another country
                 ""      doesn't say
    levels:      any of "masters", "phd", "dissertation", "postdoc";
                 empty when the listing doesn't say

The tags come from pattern matching, so some will be wrong. Staff can correct
any listing in data/eligibility_overrides.json, which always wins:

    {"429": {"citizenship": "us", "levels": ["masters", "phd"]}}

Run directly to print the tags for review:
    python scripts/eligibility_tags.py [--data data/fellowships_master.json]
"""

import json
import re
from pathlib import Path

OPEN = re.compile(
    r"international (students?|applicants?|scholars?|candidates?|researchers?)"
    r"|\b(and|or) international\b(?! (relations|development|studies|affairs|law|security))"
    r"|non-?u\.?s\.?( citizens?)?|\bnon-?citizens?"
    r"|all nationalities|any nationality|citizens? (or permanent residents )?of any country"
    r"|regardless of (citizenship|nationality)|no citizenship requirement"
    r"|foreign nationals?|\bworldwide\b|open to (all|anyone)\b")
US = re.compile(
    r"\bu\.?\s?s\.? citizens?|united states citizens?|american citizens?"
    r"|\bcitizens? (or|and) (u\.?s\.? )?(permanent|legal) residents?"
    r"|u\.?s\.? nationals?|green card|\bpermanent residents?")
OTHER = re.compile(
    r"\b(canadian|roc|taiwanese|japanese|chinese|german|french|mexican|indian|korean|turkish"
    r"|israeli|british|uk|eu|european union) (citizens?|nationals?|residents?)")

POSTDOC = re.compile(
    r"post-?doc|recent (ph\.?d|doctoral|doctorate)|ph\.?d\.? (holders?|recipients?|graduates?)"
    r"|(holds?|hold|have|has|received|completed|earned) (a |the |their )?(ph\.?d|doctorate|doctoral degree)"
    r"|doctorate (received|awarded|conferred)|within \w+ years? of (the |their )?(ph\.?d|doctorate|degree)"
    r"|post-?ph\.?d|early[- ]career (scholars?|researchers?|faculty)|terminal degree"
    r"|with (a |an )?(ph\.?d|doctorate|doctoral degree)|doctoral degree holders?")
# Requirements that rule out doctoral students before candidacy
CANDIDATES_ONLY = re.compile(
    r"advanced to candidacy|\babd\b|all but dissertation|must be (a )?(doctoral|ph\.?d\.?) candidates?")
STUDENTS = re.compile(r"\bstudents?\b|\bcandidates?\b|graduate study")
DISSERTATION = re.compile(
    r"dissertation|advanced to candidacy|\babd\b|all but dissertation"
    r"|(doctoral|ph\.?d\.?) candidates?|candidacy")
PHD = re.compile(
    r"ph\.?d\.?|doctoral|predoctoral|pre-doctoral|doctorate students?|graduate students?|grad students?")
MASTERS = re.compile(
    r"master'?s|\bm\.?a\.?\b(?= students?| degree| program)|\bm\.?s\.? (students?|degree|program)"
    r"|\b(mfa|mph|msw|mpp|mba|mpa|mlis|mup)\b|professional (degree|school) students?"
    r"|graduate students?|grad students?|graduate degree|graduate (study|school|programs?)"
    r"|\b(law|medical|business|j\.?d\.?) students?")

LEVELS = ("masters", "phd", "dissertation", "postdoc")


def citizenship(text):
    t = (text or "").lower()
    if OPEN.search(t):
        return "open"
    if US.search(t):
        return "us"
    if OTHER.search(t):
        return "other"
    return ""


def levels(record):
    """Degree stages a listing is open to, from its eligibility, title and award type."""
    elig = (record.get("eligibility") or "").lower()
    title = (record.get("title") or "").lower()
    kind = (record.get("awardType") or "").lower()
    found = set()
    if POSTDOC.search(elig) or "postdoctoral" in kind or POSTDOC.search(title):
        found.add("postdoc")
    if DISSERTATION.search(elig) or "dissertation" in kind or DISSERTATION.search(title):
        found.add("dissertation")
    # A postdoc listing that never mentions students is for PhD holders only:
    # its "PhD" or "MFA" is the degree applicants must already have
    if "postdoc" in found and elig and not STUDENTS.search(elig):
        return [lvl for lvl in LEVELS if lvl in found]
    phd_text = POSTDOC.sub(" ", elig)
    if PHD.search(phd_text) or "predoctoral" in title:
        # Awards for doctoral candidates only aren't open to students before candidacy
        only_candidates = CANDIDATES_ONLY.search(elig) or (
            DISSERTATION.search(elig) and not re.search(
                r"doctoral students?|ph\.?d\.? students?|graduate students?", phd_text))
        if not only_candidates:
            found.add("phd")
    if MASTERS.search(elig) or MASTERS.search(title):
        found.add("masters")
    return [lvl for lvl in LEVELS if lvl in found]


def load_overrides(data_path):
    path = Path(data_path).with_name("eligibility_overrides.json")
    if not path.exists():
        return {}
    with open(path) as f:
        return {int(k): v for k, v in json.load(f).items() if not k.startswith("_")}


def tag(records, overrides=None):
    """Adds "citizenship" and "levels" to each record, in place."""
    overrides = overrides or {}
    for r in records:
        r["citizenship"] = citizenship(r.get("eligibility"))
        r["levels"] = levels(r)
        o = overrides.get(r["id"], {})
        if "citizenship" in o:
            r["citizenship"] = o["citizenship"]
        if "levels" in o:
            r["levels"] = [lvl for lvl in LEVELS if lvl in o["levels"]]
    return records


if __name__ == "__main__":
    import argparse
    import collections
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/fellowships_master.json")
    args = ap.parse_args()
    recs = json.load(open(args.data))
    tag(recs, load_overrides(args.data))
    print(collections.Counter(r["citizenship"] or "(not stated)" for r in recs))
    print(collections.Counter(l for r in recs for l in r["levels"] or ["(not stated)"]))
    for r in recs:
        print(f"{r['id']:>5} {r['citizenship'] or '-':5} {','.join(r['levels']) or '-':28} {r['eligibility'][:90]}")
