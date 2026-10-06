"""Tests for the evidence checks in scripts/02_agent_research.py.

Run with: python -m pytest tests/
These don't call the Claude API. Tests marked "network" fetch real pages.
"""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "agent_research", Path(__file__).parent.parent / "scripts" / "02_agent_research.py")
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)

TODAY = "2026-10-06"
PAGE = ("<h1>Example Dissertation Fellowship</h1><p>The fellowship provides a "
        "<b>$30,000</b> stipend for one year.</p><p>Applications are due "
        "November&nbsp;1, 2026 at 5 p.m. Eastern.</p><p>Open to U.S. citizens "
        "enrolled in a Ph.D. program.</p>")
URL = "https://example.org/fellowship"


def field(value, quote, url=URL):
    return {"value": value, "source_url": url, "quote": quote}


def findings(**kw):
    empty = field("", "", "")
    base = {k: empty for k in ("official_url", "deadline", "amount", "eligibility",
                               "program_status_evidence")}
    base.update(program_status="active", notes="")
    base.update(kw)
    return base


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(ar, "fetch_text", lambda url, timeout=20: (0, ""))


def record(**kw):
    r = {"id": 1, "title": "Example", "deadline": "Nov 03, 2025",
         "deadlineSort": "2025-11-03", "amount": "", "eligibility": "PhD students",
         "officialUrl": URL}
    r.update(kw)
    return r


def agent_docs():
    from bs4 import BeautifulSoup
    return {URL: BeautifulSoup(PAGE, "html.parser").get_text(" ")}


def test_dates_in_handles_common_formats():
    assert (2026, 11, 1) in ar.dates_in("due november 1, 2026")
    assert (None, 3, 15) in ar.dates_in("deadline: mar. 15th")
    assert (2027, 1, 9) in ar.dates_in("by 9 january 2027")
    assert (2026, 12, 1) in ar.dates_in("12/1/2026")
    assert (2027, 2, 3) in ar.dates_in("2027-02-03")


def test_deadline_must_be_in_quote():
    assert ar.deadline_in_quote("2026-11-01", "Applications are due November 1, 2026")
    assert ar.deadline_in_quote("2026-11-01", "Applications are due November 1")  # no year
    assert not ar.deadline_in_quote("2026-11-02", "Applications are due November 1, 2026")
    assert not ar.deadline_in_quote("2027-11-01", "Applications are due November 1, 2026")
    assert not ar.deadline_in_quote("not a date", "November 1, 2026")


def test_amount_must_be_in_quote():
    assert ar.amount_in_quote("$30,000 stipend", "provides a $30,000 stipend")
    assert ar.amount_in_quote("$30000", "provides a $30,000 stipend")
    assert not ar.amount_in_quote("$35,000", "provides a $30,000 stipend")
    assert not ar.amount_in_quote("Varies", "provides a $30,000 stipend")


def test_correct_findings_are_applied(no_network):
    f = findings(
        deadline=field("2026-11-01", "Applications are due November 1, 2026"),
        amount=field("$30,000 stipend", "provides a $30,000 stipend"),
    )
    checks, changes, flags = ar.check_findings(record(), f, agent_docs(), TODAY)
    assert checks["deadline"]["verdict"] == "verified"
    assert changes == {"deadline": "Nov 01, 2026", "amount": "$30,000 stipend"}


def test_curly_quotes_and_spacing_still_match(no_network):
    f = findings(deadline=field("2026-11-01", "Applications are due  November 1,\n2026"))
    checks, changes, _ = ar.check_findings(record(), f, agent_docs(), TODAY)
    assert changes.get("deadline") == "Nov 01, 2026"


def test_made_up_quote_is_rejected(no_network):
    f = findings(deadline=field("2026-12-15", "Applications are due December 15, 2026"))
    checks, changes, _ = ar.check_findings(record(), f, agent_docs(), TODAY)
    assert checks["deadline"]["verdict"] == "rejected"
    assert checks["deadline"]["reason"] == "quote not found on the source page"
    assert changes == {}


def test_real_quote_wrong_date_is_rejected(no_network):
    f = findings(deadline=field("2026-11-15", "Applications are due November 1, 2026"))
    checks, changes, _ = ar.check_findings(record(), f, agent_docs(), TODAY)
    assert checks["deadline"]["reason"] == "quote does not contain this date"
    assert changes == {}


def test_unreadable_source_is_rejected(no_network):
    f = findings(deadline=field("2026-11-01", "Applications are due November 1, 2026",
                                url="https://example.org/other"))
    checks, changes, _ = ar.check_findings(record(), f, agent_docs(), TODAY)
    assert checks["deadline"]["verdict"] == "rejected"
    assert changes == {}


def test_older_deadline_is_not_applied(no_network):
    f = findings(deadline=field("2026-11-01", "Applications are due November 1, 2026"))
    _, changes, _ = ar.check_findings(record(deadlineSort="2026-12-01"), f, agent_docs(), TODAY)
    assert "deadline" not in changes


def test_existing_amount_is_kept(no_network):
    f = findings(amount=field("$30,000", "provides a $30,000 stipend"))
    _, changes, _ = ar.check_findings(record(amount="$25,000"), f, agent_docs(), TODAY)
    assert changes == {}


def test_link_replaced_only_when_old_one_is_broken(monkeypatch):
    new = "https://example.org/new"
    docs = {new: "Example Dissertation Fellowship"}
    f = findings(official_url=field(new, "Example Dissertation Fellowship", url=""))
    monkeypatch.setattr(ar, "fetch_text", lambda url, timeout=20: (404, ""))
    _, changes, _ = ar.check_findings(record(), f, docs, TODAY)
    assert changes == {"officialUrl": new}
    monkeypatch.setattr(ar, "fetch_text", lambda url, timeout=20: (403, ""))
    _, changes, _ = ar.check_findings(record(), f, docs, TODAY)
    assert changes == {}


def test_discontinued_is_flagged_not_applied(no_network):
    docs = {URL: "This fellowship has been discontinued and will not be offered in 2027."}
    f = findings(program_status="discontinued",
                 program_status_evidence=field("discontinued",
                                               "This fellowship has been discontinued"))
    _, changes, flags = ar.check_findings(record(), f, docs, TODAY)
    assert changes == {}
    assert any("discontinued" in fl for fl in flags)


def test_select_stale_orders_most_recently_passed_first():
    recs = [record(id=1, deadlinePassed=True, deadlineSort="2025-01-01"),
            record(id=2, deadlinePassed=False, deadlineSort="2026-12-01"),
            record(id=3, deadlinePassed=True, deadlineSort="2026-09-01")]
    assert [r["id"] for r in ar.select_records(recs, "stale", limit=5)] == [3, 1]
    assert [r["id"] for r in ar.select_records(recs, "all", ids=[2])] == [2]


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """Replays canned API responses, built with the SDK's own types."""

    def __init__(self, responses):
        from anthropic.types.beta import BetaMessage
        self.responses = [BetaMessage.model_validate(r) for r in responses]
        self.calls = []
        outer = self

        class Messages:
            def stream(self, **kw):
                outer.calls.append(kw)
                return FakeStream(outer.responses.pop(0))

        class Beta:
            messages = Messages()

        self.beta = Beta()


def api_message(content, stop_reason):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": ar.MODEL,
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 200,
                      "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 1}}}


def fetch_block(url, text):
    return [
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_fetch", "input": {"url": url}},
        {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_1",
         "content": {"type": "web_fetch_result", "url": url, "retrieved_at": "2026-10-06T00:00:00Z",
                     "content": {"type": "document",
                                 "source": {"type": "text", "media_type": "text/plain", "data": text}}}},
    ]


def submit_block(f):
    return {"type": "tool_use", "id": "toolu_1", "name": "submit_findings", "input": f}


def test_research_handles_pause_turn_and_collects_fetched_pages(no_network):
    text = "Applications are due November 1, 2026. The fellowship provides a $30,000 stipend."
    client = FakeClient([
        api_message(fetch_block(URL, text), "pause_turn"),
        api_message([submit_block(findings(
            deadline=field("2026-11-01", "Applications are due November 1, 2026")))], "tool_use"),
    ])
    f, docs, usage = ar.research(client, record(), TODAY)
    assert f["deadline"]["value"] == "2026-11-01"
    assert docs == {URL: text}
    assert usage == {"input_tokens": 2000, "output_tokens": 400, "web_search_requests": 4}
    # The paused turn is sent back so the agent can continue it
    assert client.calls[1]["messages"][-1]["role"] == "assistant"
    _, changes, _ = ar.check_findings(record(), f, docs, TODAY)
    assert changes == {"deadline": "Nov 01, 2026"}


def test_research_nudges_once_then_gives_up():
    done = api_message([{"type": "text", "text": "I couldn't find it."}], "end_turn")
    client = FakeClient([done, done])
    f, _, _ = ar.research(client, record(), TODAY)
    assert f is None and len(client.calls) == 2


def test_main_writes_report_and_applies(tmp_path, monkeypatch, no_network):
    import json, sys, anthropic
    data = tmp_path / "data.json"
    data.write_text(json.dumps([record(id=1, deadlinePassed=True), record(id=2, deadlinePassed=True)]))
    text = "Applications are due November 1, 2026."
    good = findings(deadline=field("2026-11-01", "Applications are due November 1, 2026"))
    made_up = findings(deadline=field("2026-12-15", "Applications are due December 15, 2026"))
    client = FakeClient([
        api_message(fetch_block(URL, text) + [submit_block(good)], "tool_use"),
        api_message(fetch_block(URL, text) + [submit_block(made_up)], "tool_use"),
    ])
    monkeypatch.setattr(anthropic, "Anthropic", lambda: client)
    monkeypatch.setattr(sys, "argv", ["x", "--data", str(data), "--out-dir", str(tmp_path),
                                      "--ids", "1,2", "--apply"])
    ar.main()
    out = {r["id"]: r for r in json.loads(data.read_text())}
    assert out[1]["deadline"] == "Nov 01, 2026"
    assert out[2]["deadline"] == "Nov 03, 2025"
    report = (tmp_path / "agent_report.md").read_text()
    assert "Nov 01, 2026" in report and "quote not found on the source page" in report
