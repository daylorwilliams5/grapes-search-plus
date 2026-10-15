"""Tests for scripts/eligibility_tags.py, using eligibility text from real listings."""

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "eligibility_tags", Path(__file__).parent.parent / "scripts" / "eligibility_tags.py")
et = importlib.util.module_from_spec(spec)
spec.loader.exec_module(et)


def rec(eligibility, title="Fellowship", awardType="Fellowship", id=1):
    return {"id": id, "eligibility": eligibility, "title": title, "awardType": awardType}


def test_citizenship():
    assert et.citizenship("U.S. citizens, nationals, or permanent residents; full-time STEM graduate students") == "us"
    assert et.citizenship("PhD, MD, or JD recipients within 5 years of degree; open to U.S. and non-U.S. citizens.") == "open"
    assert et.citizenship("U.S. citizens, permanent residents, or DACA recipients. International students now eligible") == "open"
    assert et.citizenship("Bachelor's degree holders; All nationalities; English speakers") == "open"
    assert et.citizenship("ROC citizens completing PhD dissertations") == "other"
    assert et.citizenship("Doctoral candidates in history") == ""


def test_international_relations_is_not_open_to_international_students():
    text = ("U.S. citizens under age 30 with a background in fields such as political science, "
            "international relations, or history")
    assert et.citizenship(text) == "us"
    assert et.citizenship("current graduate students in international development") == ""


def test_levels():
    assert et.levels(rec("Full-time graduate students; U.S. institutions")) == ["masters", "phd"]
    assert et.levels(rec("PhD students advanced to candidacy; social sciences")) == ["dissertation"]
    assert et.levels(rec("Predoctoral candidates must be advanced to candidacy; postdoctoral applicants must hold a PhD")) \
        == ["dissertation", "postdoc"]
    assert et.levels(rec("Doctoral candidates enrolled at North American universities")) == ["dissertation"]
    assert et.levels(rec("Recent PhD recipients in theoretical computer science")) == ["postdoc"]
    assert et.levels(rec("Terminal degree holders (PhD, MFA, etc.) at least 5 years prior; faculty")) == ["postdoc"]
    assert et.levels(rec("Researchers at NIH-funded institutions with doctoral degree and a qualified mentor.")) == ["postdoc"]
    assert et.levels(rec("Graduate students and postdoctoral scholars")) == ["masters", "phd", "postdoc"]
    assert et.levels(rec("Second-year law students at U.S. law schools")) == ["masters"]
    assert et.levels(rec("Artists and scholars; multiple discipline categories")) == []


def test_award_type_and_title_count():
    assert et.levels(rec("", awardType="Dissertation Fellowship")) == ["dissertation"]
    assert et.levels(rec("", title="Postdoctoral Fellowship", awardType="Fellowship")) == ["postdoc"]


def test_overrides_win(tmp_path):
    data = tmp_path / "fellowships_master.json"
    data.write_text("[]")
    (tmp_path / "eligibility_overrides.json").write_text(json.dumps({
        "_note": "ignored", "7": {"citizenship": "open", "levels": ["postdoc", "phd"]}}))
    records = [rec("U.S. citizens; graduate students", id=7), rec("U.S. citizens", id=8)]
    et.tag(records, et.load_overrides(data))
    assert records[0]["citizenship"] == "open" and records[0]["levels"] == ["phd", "postdoc"]
    assert records[1]["citizenship"] == "us"


def test_every_listing_gets_tags():
    data = Path(__file__).parent.parent / "data" / "fellowships_master.json"
    records = json.loads(data.read_text())
    et.tag(records)
    assert all(r["citizenship"] in ("us", "open", "other", "") for r in records)
    assert all(set(r["levels"]) <= set(et.LEVELS) for r in records)
