"""Tests for the local assistant prototype (assistant/server.py). No API calls."""

import datetime
import importlib.util
import json
import threading
import urllib.error
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

        class Beta:
            messages = self.messages
        self.beta = Beta()


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
    assert call["model"] == "claude-sonnet-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
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


def test_recently_checked_listings_count_as_verified():
    checked = dict(RECORDS[1], checked="2026-09-01")
    stale = dict(RECORDS[1], id=98, checked="2025-01-01")
    a = srv.Assistant(FakeClient({}), [checked, stale], today=TODAY)
    assert a.verified == {99}
    assert "unverified listing" not in a.catalog.splitlines()[1]



class FakeAgent:
    """Stands in for scripts/02_agent_research.py."""

    def __init__(self, deadline=None, flags=(), findings=True):
        self.deadline, self.flags, self.findings, self.calls = deadline, list(flags), findings, 0

    def research(self, client, record, today, model):
        self.calls += 1
        return ({"notes": "Checked the sponsor's page."} if self.findings else None), {}, {}

    def estimate_cost(self, usage):
        return 0.012

    def check_findings(self, record, findings, docs, today):
        checks = {"deadline": {"verdict": "empty"}, "amount": {"verdict": "empty"}}
        if self.deadline:
            checks["deadline"] = {"verdict": "verified", "value": self.deadline, "quote": "Due " + self.deadline,
                                  "source_url": "https://example.org", "year_inferred": False}
        return checks, {}, self.flags


def test_check_confirms_a_current_deadline_and_caches_it():
    agent = FakeAgent(deadline="2099-01-10")
    c = srv.Checker(None, RECORDS, agent=agent)
    r = c.check(12)
    assert r["status"] == "confirmed" and r["deadline"]["quote"] == "Due 2099-01-10"
    assert r["listing_deadline"] == "" and r["cost"] == 0.012
    c.check(12)
    assert agent.calls == 1


def test_check_reports_unposted_and_stopped_programs():
    assert srv.Checker(None, RECORDS, agent=FakeAgent(deadline="2020-01-10")).check(12)["status"] == "not_posted"
    stopped = srv.Checker(None, RECORDS, agent=FakeAgent(flags=["Sponsor page says the program is paused"]))
    assert stopped.check(12)["status"] == "stopped"
    assert srv.Checker(None, RECORDS, agent=FakeAgent()).check(12)["status"] == "unconfirmed"


def test_check_rejects_unknown_listings():
    with pytest.raises(ValueError):
        srv.Checker(None, RECORDS, agent=FakeAgent()).check(4242)


def test_server_check_endpoint():
    a = assistant({"reply": "", "matches": []})
    checker = srv.Checker(None, RECORDS, agent=FakeAgent(deadline="2099-01-10"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(a, checker))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/api/check", method="POST", data=json.dumps({"id": 12}).encode(),
                                     headers={"Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read())["status"] == "confirmed"
    finally:
        server.shutdown()


def test_real_research_agent_loads():
    agent = srv.load_research_agent()
    assert callable(agent.research) and callable(agent.check_findings)


def test_gate_open_without_a_passcode():
    g = srv.Gate("")
    assert not g.locked and g.unlocks(None) and all(g.allow("a", "ask") for _ in range(100))


def test_gate_passcode_and_limits():
    g = srv.Gate("grapes")
    assert g.locked and g.unlocks("grapes") and not g.unlocks("nope") and not g.unlocks(None)
    t = 1_000_000.0
    assert all(g.allow("a", "check", now=t) for _ in range(srv.Gate.LIMITS["check"]))
    assert not g.allow("a", "check", now=t)            # this visitor's hourly limit
    assert g.allow("b", "check", now=t)                # another visitor is fine
    assert g.allow("a", "check", now=t + 3601)         # an hour later it resets


def test_gate_daily_limit():
    g = srv.Gate("grapes")
    g.DAILY = 3
    t = 1_000_000.0
    assert [g.allow(str(i), "ask", now=t) for i in range(4)] == [True, True, True, False]


def post(base, path, body, headers=None):
    req = urllib.request.Request(base + path, method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode()


def test_server_with_passcode():
    import urllib.error  # noqa: F401  (used by post)
    a = assistant({"reply": "Hi.", "matches": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(a, None, srv.Gate("grapes")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert json.loads(urllib.request.urlopen(base + "/api/status").read()) == {"locked": True, "check": False}
        ask = {"messages": [{"role": "user", "text": "hi"}]}
        assert post(base, "/api/ask", ask)[0] == 403
        assert post(base, "/api/ask", ask, {"X-Demo-Passcode": "wrong"})[0] == 403
        assert post(base, "/api/unlock", {"passcode": "grapes"}) == (200, {"ok": True})
        assert post(base, "/api/ask", ask, {"X-Demo-Passcode": "grapes"}) == (200, {"reply": "Hi.", "matches": []})
        assert post(base, "/api/check", {"id": 12}, {"X-Demo-Passcode": "grapes"})[0] == 404  # checks off here
    finally:
        server.shutdown()
