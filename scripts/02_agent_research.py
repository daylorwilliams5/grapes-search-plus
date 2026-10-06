"""
02_agent_research.py
====================
Checks listings against their sponsors' websites with a Claude research agent
and proposes updates, each backed by a quote from the sponsor's page.

For each selected listing, the agent searches the web, reads the sponsor's
pages, and reports the current deadline, award amount, eligibility, and
official link. Every value must come with the page it was found on and a
verbatim quote. This script then checks each quote against the page text
(both the copy the agent read and a fresh copy fetched here) and drops any
value whose quote can't be found or doesn't contain the value.

Nothing is published automatically. Verified changes are written to the data
only with --apply, and the GitHub workflow puts them in a pull request for
DGE staff to review. The agent never changes a listing's verified status.

What --apply changes:
  - deadline:    only when the new date is later than the one on file
  - amount:      only when the listing has none
  - officialUrl: only when the current link is broken (404, 410, or no such host)
Eligibility differences and programs that look discontinued are listed in
the report for staff to handle by hand.

Usage:
    python scripts/02_agent_research.py --data data/fellowships_master.json \
        --limit 20 [--ids 97,412] [--select stale|missing|all] [--apply]

Writes data/agent_proposals.json and data/agent_report.md.

Requirements:
    pip install anthropic requests beautifulsoup4 python-dateutil
    Set ANTHROPIC_API_KEY.
"""

import argparse
import base64
import datetime
import io
import json
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dparser

MODEL = "claude-opus-5-5"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UCLA-DGE-FellowshipBot/1.0; research@ucla.edu)"
}

FIELD = {
    "type": "object",
    "properties": {
        "value": {"type": "string"},
        "source_url": {"type": "string"},
        "quote": {"type": "string"},
    },
    "required": ["value", "source_url", "quote"],
    "additionalProperties": False,
}

SUBMIT_TOOL = {
    "name": "submit_findings",
    "description": (
        "Submit what you found for this listing. Call this exactly once, when your "
        "research is done. For any field you could not confirm on the sponsor's own "
        "pages, leave value, source_url and quote as empty strings."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "official_url": FIELD,
            "deadline": FIELD,
            "amount": FIELD,
            "eligibility": FIELD,
            "program_status": {
                "type": "string",
                "enum": ["active", "discontinued", "paused", "unclear"],
            },
            "program_status_evidence": FIELD,
            "notes": {"type": "string"},
        },
        "required": [
            "official_url", "deadline", "amount", "eligibility",
            "program_status", "program_status_evidence", "notes",
        ],
        "additionalProperties": False,
    },
}

SYSTEM = """You check graduate fellowship listings for UCLA's Division of Graduate Education. \
Students rely on these listings to plan applications, so a wrong deadline does real harm and \
an empty field does none. Report only what a sponsor's page states.

For the listing you're given:
1. Find the sponsor's official page for the program. Prefer the sponsor's own site over \
aggregators (ProFellow, university fellowship lists, Pivot, news posts); use an aggregator only \
to find the sponsor's page.
2. Read the page with web_fetch, and follow links to the "how to apply", "deadlines" or \
"eligibility" pages when the details are there.
3. Call submit_findings with:
   - official_url: the sponsor's page for this program.
   - deadline: the application deadline for the next cycle that closes after today, as \
YYYY-MM-DD. If the sponsor hasn't posted the next cycle yet, give the most recent deadline \
they state. If applications are rolling or there is no fixed deadline, leave the value empty \
and say so in notes. If there are several deadlines (letters, internal nomination), give the \
one for the applicant's own application and mention the others in notes.
   - amount: the award amount as the sponsor states it, e.g. "$30,000 stipend".
   - eligibility: one sentence, in plain words, on who can apply (degree stage, citizenship, field).
   - program_status: "discontinued" or "paused" only when a page says so explicitly.

Every value needs source_url (the page you fetched it from) and quote: a short passage copied \
character for character from that page that contains the value. The quote is checked \
automatically against the page text, so do not paraphrase, reformat dates, or join text from \
different parts of the page. Search result snippets are not acceptable sources; fetch the page.

Leave a field empty rather than guess."""


# ----------------------------------------------------------------------------
# Selecting listings
# ----------------------------------------------------------------------------

def select_records(records, mode, ids=None, limit=20):
    """Pick which listings to check. Passed deadlines come first, soonest
    passed first, since those are the ones students see as estimates."""
    if ids:
        wanted = set(ids)
        return [r for r in records if r["id"] in wanted]
    if mode == "stale":
        pool = [r for r in records if r.get("deadlinePassed")]
        pool.sort(key=lambda r: r.get("deadlineSort") or "", reverse=True)
    elif mode == "missing":
        pool = [r for r in records if not r.get("amount") or not r.get("deadline")]
    else:
        pool = list(records)
    return pool[:limit]


# ----------------------------------------------------------------------------
# Running the agent
# ----------------------------------------------------------------------------

def listing_prompt(record, today):
    shown = {k: record.get(k, "") for k in (
        "title", "agency1", "agency2", "awardType", "season",
        "deadline", "amount", "eligibility", "officialUrl")}
    return (
        f"Today is {today}. Check this listing:\n\n"
        f"{json.dumps(shown, indent=2)}\n\n"
        "The link and details on file may be out of date. When you're done, call submit_findings."
    )


def fetched_documents(content):
    """Text of every page the agent fetched in this turn, keyed by URL."""
    docs = {}
    for block in content:
        if block.type != "web_fetch_tool_result" or block.content.type != "web_fetch_result":
            continue
        source = block.content.content.source
        if source.type == "text":
            docs[block.content.url] = source.data
        elif source.type == "base64":
            text = pdf_text(base64.b64decode(source.data))
            if text:
                docs[block.content.url] = text
    return docs


def research(client, record, today, max_searches=6, max_fetches=10):
    """Run the agent on one listing. Returns (findings or None, fetched docs, usage)."""
    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_fetches},
        SUBMIT_TOOL,
    ]
    messages = [{"role": "user", "content": listing_prompt(record, today)}]
    docs, usage = {}, {"input_tokens": 0, "output_tokens": 0, "web_search_requests": 0}
    nudged = False

    for _ in range(8):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=SYSTEM,
            tools=tools,
            messages=messages,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()

        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        stu = getattr(response.usage, "server_tool_use", None)
        usage["web_search_requests"] += getattr(stu, "web_search_requests", 0) or 0
        docs.update(fetched_documents(response.content))

        if response.stop_reason == "refusal":
            return None, docs, usage

        submit = next((b for b in response.content
                       if b.type == "tool_use" and b.name == "submit_findings"), None)
        if submit:
            return submit.input, docs, usage

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason in ("end_turn", "tool_use") and not nudged:
            nudged = True
            messages.append({"role": "user",
                             "content": "Please call submit_findings with what you found."})
            continue
        break
    return None, docs, usage


# ----------------------------------------------------------------------------
# Checking the evidence
# ----------------------------------------------------------------------------

def normalize(text):
    """Lowercase, fold quotes/dashes/odd spaces, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(str.maketrans({
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "−": "-", " ": " ",
    }))
    text = text.replace("*", "").replace("_", "")  # markdown emphasis in fetched text
    return re.sub(r"\s+", " ", text).strip().lower()


def pdf_text(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        return " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return ""


def fetch_text(url, timeout=20):
    """Fetch a page ourselves. Returns (status, text). status is the HTTP code,
    or 0 if the host couldn't be reached."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return 0, ""
    if resp.status_code != 200:
        return resp.status_code, ""
    if "pdf" in resp.headers.get("content-type", "") or url.lower().endswith(".pdf"):
        return 200, pdf_text(resp.content)
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return 200, soup.get_text(separator=" ", strip=True)


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_PATTERNS = [
    # March 1, 2027 / Mar. 1 2027 / March 1st
    re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?"),
    # 1 March 2027
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:,?\s+(\d{4}))?"),
    # 3/1/2027
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b"),
    # 2027-03-01
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
]


def dates_in(text):
    """(year or None, month, day) for every date written in the text."""
    found = []
    for i, pat in enumerate(DATE_PATTERNS):
        for m in pat.finditer(text):
            g = m.groups()
            if i == 0:
                y, mo, d = g[2], MONTHS[g[0]], g[1]
            elif i == 1:
                y, mo, d = g[2], MONTHS[g[1]], g[0]
            elif i == 2:
                y, mo, d = g[2], g[0], g[1]
                if len(y) == 2:
                    y = "20" + y
            else:
                y, mo, d = g
            found.append((int(y) if y else None, int(mo), int(d)))
    return found


def deadline_in_quote(value, quote):
    """The proposed date must be written in the quote. A quote without a year
    (e.g. "Applications due November 1") is accepted on month and day."""
    try:
        date = datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return any(mo == date.month and d == date.day and (y is None or y == date.year)
               for y, mo, d in dates_in(normalize(quote)))


def amount_in_quote(value, quote):
    """Every number in the amount (e.g. 30,000) must appear in the quote."""
    nums = [n.replace(",", "") for n in re.findall(r"\d[\d,]*", value)]
    digits = {n.replace(",", "") for n in re.findall(r"\d[\d,]*", quote)}
    return bool(nums) and all(n in digits for n in nums)


class PageCache:
    """Page text by URL: what the agent fetched, plus our own fetch."""

    def __init__(self, agent_docs):
        self.agent = {u: normalize(t) for u, t in agent_docs.items()}
        self.ours = {}
        self.status = {}

    def texts(self, url):
        out = []
        if url in self.agent:
            out.append(self.agent[url])
        if url not in self.ours:
            status, text = fetch_text(url)
            self.status[url] = status
            self.ours[url] = normalize(text)
        if self.ours[url]:
            out.append(self.ours[url])
        return out


def check_field(name, field, pages):
    """Returns (verdict, reason). verdict is 'verified', 'empty' or 'rejected'."""
    value, url, quote = (field.get(k, "").strip() for k in ("value", "source_url", "quote"))
    if not value:
        return "empty", ""
    if not url or not quote:
        return "rejected", "no source or quote given"
    texts = pages.texts(url)
    if not texts:
        status = pages.status.get(url)
        return "rejected", f"source page could not be read (HTTP {status or 'no response'})"
    q = normalize(quote)
    if len(q) < 12:
        return "rejected", "quote too short to check"
    if not any(q in t for t in texts):
        return "rejected", "quote not found on the source page"
    if name == "deadline" and not deadline_in_quote(value, quote):
        return "rejected", "quote does not contain this date"
    if name == "amount" and not amount_in_quote(value, quote):
        return "rejected", "quote does not contain this amount"
    return "verified", ""


def check_findings(record, findings, agent_docs, today):
    """Check every field and decide which changes are safe to apply."""
    pages = PageCache(agent_docs)
    checks = {}
    for name in ("official_url", "deadline", "amount", "eligibility", "program_status_evidence"):
        f = findings.get(name) or {}
        if name == "official_url":
            # The link itself is the value: it's verified if the page loads and
            # the quote (e.g. the program name) is on it.
            f = {**f, "source_url": f.get("value", "")}
        verdict, reason = check_field(name, f, pages)
        checks[name] = {**f, "verdict": verdict, "reason": reason}

    changes = {}
    dl = checks["deadline"]
    if dl["verdict"] == "verified":
        current = record.get("deadlineSort") or ""
        if current.startswith("9999") or dl["value"] > current:
            changes["deadline"] = datetime.date.fromisoformat(dl["value"]).strftime("%b %d, %Y")
    am = checks["amount"]
    if am["verdict"] == "verified" and not record.get("amount"):
        changes["amount"] = am["value"]
    url = checks["official_url"]
    old = record.get("officialUrl", "")
    if url["verdict"] == "verified" and url["value"] != old and old:
        status, _ = fetch_text(old)
        if status in (0, 404, 410):
            changes["officialUrl"] = url["value"]

    flags = []
    if findings.get("program_status") in ("discontinued", "paused") and \
       checks["program_status_evidence"]["verdict"] == "verified":
        flags.append(f"Sponsor page says the program is {findings['program_status']}")
    el = checks["eligibility"]
    if el["verdict"] == "verified" and normalize(el["value"]) != normalize(record.get("eligibility")):
        flags.append("Eligibility on the sponsor's page may differ from the listing")
    if dl["verdict"] == "verified" and dl["value"] < today:
        flags.append("Sponsor hasn't posted a deadline after today yet")
    return checks, changes, flags


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------

def md(text, limit=300):
    text = re.sub(r"\s+", " ", str(text or "")).replace("|", "\\|")
    return text if len(text) <= limit else text[:limit] + "…"


def write_report(results, path, cost):
    applied = [r for r in results if r["changes"]]
    lines = [
        "# Agent research report",
        "",
        f"{len(results)} listings checked, {len(applied)} with changes to apply. "
        f"Estimated API cost: ${cost:.2f}.",
        "",
        "Each change below was found on the sponsor's page, and its quote was matched "
        "against that page automatically. Please open the source links for anything that looks off.",
        "",
    ]
    for r in results:
        lines.append(f"## [{r['id']}] {md(r['title'], 120)}")
        lines.append("")
        if r.get("error"):
            lines += [f"Agent did not finish: {r['error']}", ""]
            continue
        if r["changes"]:
            lines += ["| Field | On file | Proposed |", "|---|---|---|"]
            for k, v in r["changes"].items():
                lines.append(f"| {k} | {md(r['before'].get(k))} | {md(v)} |")
            lines.append("")
        for flag in r["flags"]:
            lines.append(f"- ⚠️ {flag}")
        lines += ["", "<details><summary>Evidence</summary>", ""]
        for name, c in r["checks"].items():
            if c["verdict"] == "empty":
                continue
            mark = "✅" if c["verdict"] == "verified" else f"❌ {c['reason']}"
            lines.append(f"- **{name}** {mark}: {md(c.get('value'), 200)}")
            if c.get("quote"):
                lines.append(f"  > {md(c['quote'])}")
            if c.get("source_url"):
                lines.append(f"  [source]({c['source_url']})")
        if r.get("notes"):
            lines.append(f"- Agent notes: {md(r['notes'], 500)}")
        lines += ["", "</details>", ""]
    Path(path).write_text("\n".join(lines))


# ----------------------------------------------------------------------------

def estimate_cost(usage):
    # Claude Opus 5.5: $4 / $20 per million tokens; web search $10 per 1,000
    return (usage["input_tokens"] * 4 + usage["output_tokens"] * 20) / 1e6 + \
        usage["web_search_requests"] * 0.01


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/fellowships_master.json")
    parser.add_argument("--select", choices=["stale", "missing", "all"], default="stale")
    parser.add_argument("--ids", help="Comma-separated record numbers to check")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true", help="Write verified changes to --data")
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()

    import anthropic
    client = anthropic.Anthropic()

    with open(args.data) as f:
        records = json.load(f)
    ids = [int(i) for i in args.ids.split(",")] if args.ids else None
    batch = select_records(records, args.select, ids, args.limit)
    today = datetime.date.today().isoformat()
    print(f"Checking {len(batch)} listings with {MODEL}")

    results, total = [], {"input_tokens": 0, "output_tokens": 0, "web_search_requests": 0}
    for i, rec in enumerate(batch, 1):
        print(f"[{i}/{len(batch)}] {rec['id']} {rec['title'][:60]}")
        result = {"id": rec["id"], "title": rec["title"], "changes": {}, "flags": [], "checks": {}}
        t0 = time.time()
        try:
            findings, docs, usage = research(client, rec, today)
        except anthropic.APIStatusError as e:
            result["error"] = f"API error {e.status_code}"
            results.append(result)
            continue
        for k in total:
            total[k] += usage[k]
        if findings is None:
            result["error"] = "no findings submitted"
        else:
            checks, changes, flags = check_findings(rec, findings, docs, today)
            result.update(checks=checks, changes=changes, flags=flags,
                          notes=findings.get("notes", ""),
                          before={k: rec.get(k, "") for k in changes})
            verdicts = ", ".join(f"{k}={c['verdict']}" for k, c in checks.items())
            print(f"    {verdicts}; changes: {list(changes) or 'none'} ({time.time() - t0:.0f}s)")
        results.append(result)

    out = Path(args.out_dir)
    cost = estimate_cost(total)
    with open(out / "agent_proposals.json", "w") as f:
        json.dump({"date": today, "model": MODEL, "usage": total, "results": results}, f, indent=2)
    write_report(results, out / "agent_report.md", cost)
    print(f"\nTokens: {total['input_tokens']:,} in, {total['output_tokens']:,} out; "
          f"{total['web_search_requests']} searches; about ${cost:.2f}")
    print(f"Report: {out / 'agent_report.md'}")

    if args.apply:
        by_id = {r["id"]: r for r in results if r["changes"]}
        n = 0
        for rec in records:
            if rec["id"] in by_id:
                rec.update(by_id[rec["id"]]["changes"])
                n += 1
        with open(args.data, "w") as f:
            json.dump(records, f, indent=2, default=str)
        print(f"Applied changes to {n} listings in {args.data}. "
              "Run 03_merge_and_rebuild.py to rebuild the page.")


if __name__ == "__main__":
    main()
