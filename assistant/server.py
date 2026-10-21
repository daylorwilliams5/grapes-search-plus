"""
assistant/server.py
===================
A local prototype of a student-facing assistant for GRAPES Search+.

Runs the search page on your own computer with a chat panel added. Students
describe themselves ("3rd-year sociology PhD, international, need summer
funding") and the assistant recommends listings. The model may only pick
record numbers from the listings; the page then shows those listings with its
own cards, so every deadline, amount, and link a student sees comes from the
data, not from the model's wording.

This is a demo for staff. It sends questions to the Claude API, so don't let
real students use it until IT has approved where it runs.

Usage:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
    python assistant/server.py            # then open http://localhost:8000

Nothing is logged: questions are sent to the API and not stored here.
"""

import argparse
import collections
import datetime
import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent

MODEL = "claude-sonnet-5-5"
# Models that support server-side fallbacks: if the model declines a request,
# the API retries it on another model instead of returning the refusal
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}
CHECK_MODEL = "haiku"  # the research agent's model for "Check the sponsor's page now"
MAX_MATCHES = 6
MAX_TURNS = 8          # earlier turns of the conversation sent with each question
MAX_QUESTION_CHARS = 1500
STALE_DAYS = 550       # same cutoff the page uses for projecting old deadlines

INSTRUCTIONS = """You help UCLA graduate students and postdocs find funding in GRAPES, \
UCLA's list of fellowships, grants, and awards. The full list is below; each listing \
starts with its record number in brackets.

Recommend only listings from this list, by record number. Never mention an award that \
isn't on it. Pick the ones that best fit what the student told you, at most 6, best \
first. Leave out listings the student clearly can't apply for, such as a U.S.-citizens-only \
award for an international student, or a postdoctoral award for a master's student. When \
a listing's eligibility is unclear for this student, you can still include it and say \
what to check.

Don't state deadlines, amounts, or links in your reply: the page shows them under each \
recommendation. Prefer listings that are open or expected to reopen over ones whose dates \
are unknown. Prefer verified listings: recommend one marked "unverified listing" only when \
no verified listing fits as well, and never more unverified than verified ones.

If you need one fact to give a useful answer (degree stage, field, or citizenship), ask \
for it in one short question, and still suggest what you can. Never ask for a name, \
student ID, or contact details. Keep replies short and plain: two or three sentences, \
then the recommendations. For each recommendation, give one sentence on why it fits.

If the question isn't about finding funding, say briefly that you can only help find \
awards in GRAPES."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "why": {"type": "string"}},
                "required": ["id", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reply", "matches"],
    "additionalProperties": False,
}


# ----------------------------------------------------------------------------
# The listing catalog the model chooses from
# ----------------------------------------------------------------------------

def deadline_text(r, today):
    """The deadline as the page shows it: open, estimated from last year, rolling, or unknown."""
    try:
        last = datetime.date.fromisoformat(r.get("deadlineSort") or "")
        if last.year == 9999:
            last = None
    except ValueError:
        last = None
    if not last:
        return "rolling" if r.get("season") == "Open/Rolling" else "date not confirmed"
    if last >= today:
        return f"open, due {last:%b %d, %Y}"
    if (today - last).days > STALE_DAYS:
        return "date not confirmed"
    year = last.year
    while True:
        year += 1
        try:
            nxt = last.replace(year=year)
        except ValueError:  # Feb 29
            nxt = last.replace(year=year, day=28)
        if nxt >= today:
            return f"expected to reopen around {nxt:%b %d, %Y}"


def is_verified(r, today):
    """Published by DGE, or its current deadline was confirmed on the sponsor's
    page in the last six months (the same rule the page uses)."""
    if r.get("status") == "Published":
        return True
    try:
        checked = datetime.date.fromisoformat(r.get("checked") or "")
    except ValueError:
        return False
    return (today - checked).days <= 183


def clip(text, n):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def build_catalog(records, today):
    """One compact line per listing. Kept identical between questions so it can be cached."""
    lines = []
    for r in sorted(records, key=lambda r: r["id"]):
        sponsor = " / ".join(a for a in (r.get("agency1"), r.get("agency2")) if a)
        parts = [
            f"[{r['id']}] {r['title']} ({sponsor})",
            r.get("awardType") or "",
            deadline_text(r, today),
            "U.S. citizens and permanent residents only" if r.get("citizenship") == "us" else "",
            f"eligibility: {clip(r.get('eligibility'), 160)}" if r.get("eligibility") else "",
            f"about: {clip(r.get('description'), 130)}" if r.get("description") else "",
            "" if is_verified(r, today) else "unverified listing",
        ]
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Answering a question
# ----------------------------------------------------------------------------

class Assistant:
    def __init__(self, client, records, model=MODEL, today=None):
        self.client = client
        self.model = model
        self.today = today or datetime.date.today()
        self.ids = {r["id"] for r in records}
        self.verified = {r["id"] for r in records if is_verified(r, self.today)}
        self.catalog = build_catalog(records, self.today)

    def messages(self, history):
        """The conversation for the API: plain text turns, ending with the student's question."""
        out = []
        for turn in history[-MAX_TURNS:]:
            role = "assistant" if turn.get("role") == "assistant" else "user"
            text = str(turn.get("text", ""))[:MAX_QUESTION_CHARS].strip()
            if not text:
                continue
            if role == "assistant" and turn.get("ids"):
                text += "\n(Recommended: " + ", ".join(f"[{i}]" for i in turn["ids"]) + ")"
            if out and out[-1]["role"] == role:
                out[-1]["content"] += "\n\n" + text
            else:
                out.append({"role": role, "content": text})
        while out and out[0]["role"] != "user":
            out.pop(0)
        if not out or out[-1]["role"] != "user":
            raise ValueError("The conversation must end with a question")
        out[-1]["content"] = f"(Today is {self.today:%B %d, %Y}.)\n\n" + out[-1]["content"]
        return out

    def ask(self, history):
        """Returns {"reply": str, "matches": [{"id", "why"}]}, matches limited to real listings."""
        api, extra = self.client.messages, {}
        if self.model in FALLBACK_MODELS:
            api = self.client.beta.messages
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        response = api.create(
            **extra,
            model=self.model,
            max_tokens=8000,
            system=[
                {"type": "text", "text": INSTRUCTIONS},
                {"type": "text", "text": "GRAPES listings:\n" + self.catalog,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=self.messages(history),
            output_config={"effort": "medium",
                           "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        )
        if response.stop_reason == "refusal":
            return {"reply": "Sorry, I can't help with that. I can help you find awards in GRAPES.",
                    "matches": []}
        if response.stop_reason == "max_tokens":
            return {"reply": "Sorry, that took too long. Could you ask again more briefly?",
                    "matches": []}
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
        return {"reply": data.get("reply", "").strip(), "matches": self.real_matches(data.get("matches", []))}

    def real_matches(self, matches):
        """Drops record numbers that aren't listings and repeats, puts verified
        listings first (keeping the model's order otherwise), and caps the count."""
        seen, out = set(), []
        for m in matches:
            i = m.get("id")
            if isinstance(i, int) and i in self.ids and i not in seen:
                seen.add(i)
                out.append({"id": i, "why": str(m.get("why", "")).strip()})
        out.sort(key=lambda m: m["id"] not in self.verified)
        return out[:MAX_MATCHES]


# ----------------------------------------------------------------------------
# Checking one listing against its sponsor's page, live
# ----------------------------------------------------------------------------

def load_research_agent():
    """scripts/02_agent_research.py, the research agent the update workflow uses."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_research", ROOT / "scripts" / "02_agent_research.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Checker:
    """Runs the research agent on one listing and reports what the sponsor's
    page says today. Results are kept for the session, so a second click on
    the same listing doesn't pay for another check."""

    def __init__(self, client, records, agent=None, model=CHECK_MODEL):
        self.client, self.model = client, model
        self.records = {r["id"]: r for r in records}
        self.agent = agent
        self.cache = {}

    def check(self, rid):
        if rid not in self.records:
            raise ValueError("No such listing")
        if rid in self.cache:
            return self.cache[rid]
        if self.agent is None:
            self.agent = load_research_agent()
        record = self.records[rid]
        today = datetime.date.today().isoformat()
        findings, docs, usage = self.agent.research(self.client, record, today, self.model)
        result = {"status": "unconfirmed", "deadline": None, "amount": None, "notes": "",
                  "listing_deadline": record.get("deadline", ""),
                  "cost": round(self.agent.estimate_cost(usage), 3)}
        if findings is None:
            result["notes"] = "The check didn't finish. Try again in a moment."
            return result
        checks, _, flags = self.agent.check_findings(record, findings, docs, today)
        for name in ("deadline", "amount"):
            c = checks.get(name, {})
            if c.get("verdict") == "verified":
                result[name] = {"value": c["value"], "quote": c.get("quote", ""),
                                "source": c.get("source_url", ""),
                                "year_added": bool(c.get("year_inferred"))}
        dl = result["deadline"]
        if dl and dl["value"] >= today:
            result["status"] = "confirmed"
        elif dl:
            result["status"] = "not_posted"  # only a past deadline is on the page
        stopped = [f for f in flags if "discontinued" in f or "paused" in f]
        if stopped:
            result["status"] = "stopped"
        result["notes"] = clip(findings.get("notes", ""), 500)
        self.cache[rid] = result
        return result


# ----------------------------------------------------------------------------
# Local web server
# ----------------------------------------------------------------------------

STATIC = {
    "/assistant/widget.js": ("widget.js", "text/javascript; charset=utf-8"),
    "/assistant/widget.css": ("widget.css", "text/css; charset=utf-8"),
}


def page_with_widget():
    html = (ROOT / "grapes-fellowship-finder.html").read_text(encoding="utf-8")
    tags = ('<link rel="stylesheet" href="/assistant/widget.css"/>\n'
            '<script src="/assistant/widget.js"></script>\n')
    i = html.rfind("</body>")
    return html[:i] + tags + html[i:]


class Gate:
    """Passcode and usage limits for a copy that's online, so only staff can
    use it and nobody can run up the API bill. With no passcode set (running
    on your own computer), everything is open."""

    LIMITS = {"ask": 40, "check": 15}  # per visitor per hour
    DAILY = 400                         # all visitors, per day

    def __init__(self, passcode=""):
        self.passcode = passcode
        self.recent = collections.defaultdict(collections.deque)
        self.day, self.today_count = None, 0
        self.lock = threading.Lock()

    @property
    def locked(self):
        return bool(self.passcode)

    def unlocks(self, given):
        return not self.passcode or hmac.compare_digest(str(given or ""), self.passcode)

    def allow(self, visitor, kind, now=None):
        """True if this visitor may make another request of this kind."""
        if not self.passcode:
            return True
        now = now or time.time()
        with self.lock:
            today = time.strftime("%Y-%m-%d", time.gmtime(now))
            if today != self.day:
                self.day, self.today_count = today, 0
            q = self.recent[(visitor, kind)]
            while q and q[0] < now - 3600:
                q.popleft()
            if len(q) >= self.LIMITS[kind] or self.today_count >= self.DAILY:
                return False
            q.append(now)
            self.today_count += 1
            return True


def make_handler(assistant, checker=None, gate=None):
    gate = gate or Gate()

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, ctype):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def visitor(self):
            # Behind a host like Render, the visitor's address is in X-Forwarded-For
            fwd = self.headers.get("X-Forwarded-For", "")
            return fwd.split(",")[0].strip() or self.client_address[0]

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/status":
                return self.send(200, json.dumps({"locked": gate.locked, "check": bool(checker)}),
                                 "application/json")
            if path in ("/", "/index.html", "/grapes-fellowship-finder.html"):
                return self.send(200, page_with_widget(), "text/html; charset=utf-8")
            if path in STATIC:
                name, ctype = STATIC[path]
                return self.send(200, (HERE / name).read_bytes(), ctype)
            self.send(404, "Not found", "text/plain")

        def do_POST(self):
            if self.path not in ("/api/ask", "/api/check", "/api/unlock") or \
                    (self.path == "/api/check" and not checker):
                return self.send(404, "Not found", "text/plain")
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 64_000)
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/unlock":
                    ok = gate.unlocks(body.get("passcode"))
                    if not ok:
                        time.sleep(1)  # slow down guessing
                    return self.send(200 if ok else 403, json.dumps({"ok": ok}), "application/json")
                if not gate.unlocks(self.headers.get("X-Demo-Passcode")):
                    return self.send(403, json.dumps({"error": "Enter the demo passcode first."}),
                                     "application/json")
                kind = "check" if self.path == "/api/check" else "ask"
                if not gate.allow(self.visitor(), kind):
                    return self.send(429, json.dumps({"error": "That's the limit for now. Try again in an hour."}),
                                     "application/json")
                if self.path == "/api/check":
                    answer = checker.check(int(body.get("id", 0)))
                else:
                    answer = assistant.ask(body.get("messages", []))
                self.send(200, json.dumps(answer), "application/json")
            except ValueError as e:
                self.send(400, json.dumps({"error": str(e)}), "application/json")
            except Exception as e:  # API errors: report without crashing the server
                print(f"Assistant error: {type(e).__name__}: {e}")
                self.send(502, json.dumps({"error": "The assistant is unavailable right now."}),
                          "application/json")

        def log_message(self, *args):
            pass  # don't log requests (they'd include nothing private, but keep it quiet)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--data", default=str(ROOT / "data" / "fellowships_master.json"))
    args = parser.parse_args()

    # On a host like Render, PORT is set and the server must listen publicly
    port, host = args.port, args.host
    if os.environ.get("PORT"):
        port, host = int(os.environ["PORT"]), "0.0.0.0"
    passcode = os.environ.get("DEMO_PASSCODE", "").strip()
    if host != "127.0.0.1" and not passcode and os.environ.get("PUBLIC") != "1":
        raise SystemExit("Refusing to go online without a passcode: set DEMO_PASSCODE "
                         "(or PUBLIC=1 once IT has approved opening it to students).")

    import anthropic
    records = json.loads(Path(args.data).read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    assistant = Assistant(client, records, model=args.model)
    try:
        checker = Checker(client, records, agent=load_research_agent())
    except ImportError as e:
        checker = None
        print(f"\"Check the sponsor's page\" is off: {e}. To turn it on:")
        print("    python -m pip install requests beautifulsoup4 python-dateutil")
    server = ThreadingHTTPServer((host, port), make_handler(assistant, checker, Gate(passcode)))
    print(f"GRAPES Search+ with the assistant: http://localhost:{port}  ({len(records)} listings, {args.model})"
          + ("  [passcode required]" if passcode else ""))
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
