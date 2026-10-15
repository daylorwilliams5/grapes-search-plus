"""Tests for the local assistant prototype (assistant/server.py). No API calls."""

import datetime
import importlib.util
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "assistant_server", Path(__file__).parent.parent / "assistant" / "server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

TODAY = datetime.date(2026, 10, 15)
RECORDS = [
    {"id": 12, "title": "Newkirk Fellowship", "agency1": "HAO", "agency2": "", "awardType": "Fellowship",
     "season": "Winter", "deadlineSort": "2027-01-10", "status": "Published",
     "eligibility": "Graduate students in solar physics", "description": "Visits to HAO."},
    {"id": 99, "title": "Met Fellowship", "agency1": "The Met", "agency2": "", "awardType": "Fellowship",
     "season": "Fall", "deadlineSort": "2025-10-17", "status": "Pending",
     "eligibility": "PhD candidates", "description": ""},
    {"id": 5, "title": "Rolling Grant", "agency1": "Fund", "agency2": "", "awardType": "Research Grant",
     "season": "Open/Rolling", "deadlineSort": "9999-12-31", "status": "Published",
     "eligibility": "", "description": ""},
]


class Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class Response:
    def __init__(self, data, stop_reason="end_turn"):
        self.content = [Block(json.dumps(data))]
        self.stop_reason = stop_reason


class FakeClient:
    def __init__(self, data, stop_reason="end_turn"):
        self.data, self.stop_reason, self.calls = data, stop_reason, []
        outer = self

        class Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return Response(outer.data, outer.stop_reason)
        self.messages = Messages()


def assistant(data, **kw):
    return srv.Assistant(FakeClient(data, **kw), RECORDS, today=TODAY)


def test_deadline_text_matches_the_page():
    assert srv.deadline_text(RECORDS[0], TODAY) == "open, due Jan 10, 2027"
    assert srv.deadline_text(RECORDS[1], TODAY) == "expected to reopen around Oct 17, 2026"
    assert srv.deadline_text(RECORDS[2], TODAY) == "rolling"
    old = dict(RECORDS[1], deadlineSort="2024-01-01", season="Fall")
    assert srv.deadline_text(old, TODAY) == "date not confirmed"


def test_catalog_lists_every_listing_by_record_number():
    cat = srv.build_catalog(RECORDS, TODAY)
    assert cat.splitlines()[0].startswith("[5] Rolling Grant")
    assert "[99] Met Fellowship (The Met)" in cat and "unverified listing" in cat


def test_only_real_listings_are_returned():
    a = assistant({"reply": "Here you go.",
                   "matches": [{"id": 12, "why": "Solar physics."}, {"id": 4242, "why": "Made up."},
                               {"id": 12, "why": "Repeat."}, {"id": 99, "why": "Art."}]})
    out = a.ask([{"role": "user", "text": "solar physics PhD"}])
    assert out == {"reply": "Here you go.",
                   "matches": [{"id": 12, "why": "Solar physics."}, {"id": 99, "why": "Art."}]}


def test_matches_are_capped():
    a = assistant({"reply": "", "matches": [{"id": i, "why": ""} for i in (12, 99, 5)] * 3})
    srv.MAX_MATCHES, old = 2, srv.MAX_MATCHES
    try:
        assert len(a.ask([{"role": "user", "text": "anything"}])["matches"]) == 2
    finally:
        srv.MAX_MATCHES = old


def test_request_caches_the_catalog_and_asks_for_json():
    a = assistant({"reply": "", "matches": []})
    a.ask([{"role": "user", "text": "hi"}])
    call = a.client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert "[12] Newkirk Fellowship" in call["system"][1]["text"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    # Today's date goes in the question, not the cached catalog
    assert "October 15, 2026" in call["messages"][-1]["content"]


def test_conversation_keeps_earlier_recommendations():
    a = assistant({"reply": "", "matches": []})
    a.ask([{"role": "user", "text": "PhD in art history"},
           {"role": "assistant", "text": "Try these.", "ids": [99]},
           {"role": "user", "text": "I'm international"}])
    msgs = a.client.calls[0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "[99]" in msgs[1]["content"]


def test_conversation_must_end_with_a_question():
    with pytest.raises(ValueError):
        assistant({"reply": "", "matches": []}).ask([{"role": "assistant", "text": "hi"}])


def test_refusal_gets_a_plain_answer():
    out = assistant({}, stop_reason="refusal").ask([{"role": "user", "text": "x"}])
    assert out["matches"] == [] and "GRAPES" in out["reply"]


def test_server_serves_the_page_with_the_panel_and_answers():
    a = assistant({"reply": "Found one.", "matches": [{"id": 12, "why": "Fits."}]})
    server = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(a))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert '<script src="/assistant/widget.js"></script>' in page
        assert page.index("/assistant/widget.js") < page.rindex("</body>")
        assert urllib.request.urlopen(base + "/assistant/widget.js").status == 200
        req = urllib.request.Request(base + "/api/ask", method="POST",
                                     data=json.dumps({"messages": [{"role": "user", "text": "hi"}]}).encode(),
                                     headers={"Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read()) == \
            {"reply": "Found one.", "matches": [{"id": 12, "why": "Fits."}]}
    finally:
        server.shutdown()


def test_verified_listings_come_first():
    a = assistant({"reply": "", "matches": [{"id": 99, "why": "Unverified."}, {"id": 12, "why": "Verified."},
                                            {"id": 5, "why": "Verified too."}]})
    out = a.ask([{"role": "user", "text": "anything"}])
    assert [m["id"] for m in out["matches"]] == [12, 5, 99]


def test_instructions_prefer_verified_listings():
    assert "Prefer verified listings" in srv.INSTRUCTIONS
