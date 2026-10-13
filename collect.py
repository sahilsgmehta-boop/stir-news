"""
Central bank commentary collector -> docs/cb.js

Runs on GitHub Actions every 30 minutes. Reads a set of public RSS/Atom feeds,
keeps what is about the Fed, ECB, BoE, BoC or SNB, de-duplicates the same remark
reported by several sites, stores a rolling history, and writes a small
JavaScript file the dashboard loads.

Two kinds of item, kept apart on purpose:

  comment   A headline that IS the remark - "Fed's Waller: more hikes needed".
            From market news sites that rewrite wire flashes within minutes.
  official  A speech, release or minutes entry from a central bank's own feed.
            Usually a title rather than a quote, but complete and linked to the
            full text, and it catches speakers the news sites skip.

Standard library only, so nothing has to be installed on the runner.

    python collect.py                 # normal run
    python collect.py --fixtures DIR  # read DIR/<source-id>.xml instead of
                                      # the network, for testing
"""

import argparse
import email.utils
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "store.json")
OUT_JS = os.path.join(HERE, "docs", "cb.js")
OUT_HEALTH = os.path.join(HERE, "docs", "health.json")
ROSTER = os.path.join(HERE, "speakers.json")

KEEP_DAYS = 45          # held in the store
SHOW_DAYS = 30          # written to cb.js
MAX_SHOW = 1500
UA = "Mozilla/5.0 (compatible; stir-news/1.0; +https://github.com)"

# ---------------------------------------------------------------------------
# SOURCES
#
#   kind "curated"   every item about one of our five banks is kept
#   kind "headline"  kept only when the headline attributes a remark to an
#                    official ("Fed's Waller: ...", "ECB President Lagarde
#                    says ...") or reports a decision/minutes - so market wraps
#                    and analyst notes ("US Dollar: ... - ING") stay out
#   kind "official"  a central bank's own feed; bank is fixed, or for BIS it is
#                    worked out from the description
#
# "checked" records what had been confirmed to return a valid feed when this
# list was written. The rest are believed correct but were not reachable from
# where this was built - the health report after each run says which work.
# ---------------------------------------------------------------------------
SOURCES = [
    dict(id="il_cb", name="investingLive central banks", kind="curated",
         url="https://investinglive.com/feed/centralbank/", checked=True),
    dict(id="fxs", name="FXStreet", kind="headline",
         url="https://www.fxstreet.com/rss/news", checked=True),
    dict(id="il_all", name="investingLive", kind="headline",
         url="https://investinglive.com/feed/", checked=True),
    dict(id="cnbc", name="CNBC Economy", kind="headline",
         url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    dict(id="mw", name="MarketWatch", kind="headline",
         url="https://feeds.content.dowjones.io/public/rss/mw_topstories"),

    dict(id="fed_sp", name="Federal Reserve speeches", kind="official", bank="Fed",
         url="https://www.federalreserve.gov/feeds/speeches.xml"),
    dict(id="fed_mp", name="Federal Reserve monetary policy", kind="official", bank="Fed",
         url="https://www.federalreserve.gov/feeds/press_monetary.xml"),
    dict(id="ecb", name="ECB press, speeches, interviews", kind="official", bank="ECB",
         url="https://www.ecb.europa.eu/rss/press.html"),
    dict(id="boe", name="Bank of England news", kind="official", bank="BoE",
         url="https://www.bankofengland.co.uk/rss/news"),
    dict(id="boc", name="Bank of Canada speeches", kind="official", bank="BoC",
         url="https://www.bankofcanada.ca/content_type/speeches/feed/"),
    dict(id="snb", name="Swiss National Bank news", kind="official", bank="SNB",
         url="https://www.snb.ch/public/en/rss/news"),
    dict(id="bis", name="BIS central bankers' speeches", kind="official", bank=None,
         url="https://www.bis.org/doclist/cbspeeches.rss"),
]

BANKS = ["Fed", "ECB", "BoE", "BoC", "SNB"]

# ---------------------------------------------------------------------------
# Recognising the bank. Deliberately no names for the Fed: the chair changed
# in 2026 and rosters drift, so "Fed's <anyone>" is the reliable signal.
# Bare surnames are only trusted where they are unambiguous.
# ---------------------------------------------------------------------------
_REGIONS = (r"New York|Chicago|St\.? Louis|Atlanta|Dallas|San Francisco|Cleveland|"
            r"Richmond|Minneapolis|Boston|Philadelphia|Kansas City")
BANK_PAT = {
    "Fed": re.compile(r"\bFed\b|\bFOMC\b|Federal Reserve|\b(?:%s) Fed\b" % _REGIONS),
    "ECB": re.compile(r"\bECB\b|European Central Bank|\bLagarde\b"),
    "BoE": re.compile(r"\bBo[Ee]\b|\bBOE\b|Bank of England|\bMPC\b"),
    "BoC": re.compile(r"\bBo[Cc]\b|\bBOC\b|Bank of Canada|\bMacklem\b"),
    "SNB": re.compile(r"\bSNB\b|Swiss National Bank"),
}
# Only trusted in the curated feed, where the context is already central banks.
CURATED_EXTRA = {
    "BoE": re.compile(r"\bBailey\b"),
    "SNB": re.compile(r"\bSchlegel\b"),
}
# For BIS, the description names the institution in full.
BIS_PAT = {
    "Fed": re.compile(r"Federal Reserve|Board of Governors"),
    "ECB": re.compile(r"European Central Bank"),
    "BoE": re.compile(r"Bank of England"),
    "BoC": re.compile(r"Bank of Canada"),
    "SNB": re.compile(r"Swiss National Bank"),
}

_B = r"(?:Fed|FOMC|ECB|BoE|BOE|BoC|BOC|SNB)"
_ROLE = (r"(?:Chair|Chairman|Chairwoman|Vice Chair|President|Vice President|Governor|"
         r"Deputy Governor|policymaker|policy maker|official|member|board member|"
         r"Executive Board member|chief economist|Chief Economist)")
ATTRIBUTION = [
    re.compile(_B + r"(?:'s|’s)\s+[A-Z]"),                     # Fed's Waller
    re.compile(_B + r"\s+" + _ROLE + r"\b"),                          # ECB President ...
    re.compile(r"\b(?:%s) Fed(?:'s|’s)?\s+(?:President\s+)?[A-Z]" % _REGIONS),
    re.compile(r"\b(?:Lagarde|Macklem)\b"),
    re.compile(_B + r"\s+[A-Z][A-Za-z\-]+\s*:"),                  # Fed Williams: ...
    re.compile(_B + r"\b.*\b(?:minutes|decision|statement|accounts|press conference|"
               r"testimony|holds|hikes|raises|cuts|keeps|leaves|rate decision)\b", re.I),
    re.compile(r"\bBeige Book\b|\bdot plot\b", re.I),
]

# Mixed-content official feeds (ECB press, BoE news) carry banknote, supervision
# and job notices too. Keep what bears on policy.
OFFICIAL_KEEP = re.compile(
    r"speech|interview|blog|monetary policy|policy decision|decision|account|"
    r"minutes|statement|testimony|hearing|press conference|introductory|remarks|"
    r"podcast|letter|rate|inflation|economic outlook|projection|Monetary Policy Report|"
    r"Financial Stability", re.I)

# Official items that are not about rates or the economy. Checked against the
# title and the start of the description, for every official feed.
OFFICIAL_DROP = re.compile(
    r"digital euro|tokeni[sz]|payment|banknote|counterfeit|supervis|regulat|"
    r"prudential|\bPRA\b|cyber|climate|data portal|statistic|fintech|crypto|"
    r"stablecoin|financial inclusion|appointment|vacanc|consultation|"
    r"Money Market Committee|resolution regime|anti-money|sanction|"
    r"enforcement|bank capital|capital requirement|stress test|operational resilience",
    re.I)

NAME_STOP = set("""The A An Minutes Rate Rates Policy Survey Beige Book Board Staff
Monetary Decision Statement Says Said Sees See Warns Expects Report Economic Outlook
Chair Chairman President Governor Vice Deputy Officials Official Member Members Bank
Central New York Chicago St Louis Atlanta Dallas San Francisco Cleveland Richmond
Minneapolis Boston Philadelphia Kansas City Fed ECB BoE BOE BoC BOC SNB FOMC MPC
Speech Remarks Interview Testimony Press Release Is Will May Could Should Accounts
Account Data Survey Staff Projections""".split())

SPEAKER_PATS = [
    re.compile(_B + r"\s+([A-Z][A-Za-z\-]+)\s*:"),                # Fed Williams: ...
    re.compile(_B + r"(?:'s|’s)\s+([A-Z][A-Za-z\-]+)"),
    re.compile(r"\b(?:%s) Fed(?:'s|’s)?\s+(?:President\s+)?([A-Z][A-Za-z\-]+)" % _REGIONS),
    re.compile(_ROLE + r"(?:\s+for\s+Supervision)?\s+([A-Z][A-Za-z\-]+)"),
    re.compile(r"\b(Lagarde|Macklem|Bailey|Schlegel)\b"),
]

STOPWORDS = set("""the a an and or of to in on for at by with from as is are was be
been says said say sees see its it that this than more less not no will would could
should may might after before over under into about amid amid fed ecb boe boc snb
fomc s""".split())


# ---------------------------------------------------------------------------
def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(el, *names):
    for c in el:
        if _local(c.tag) in names and (c.text or "").strip():
            return c.text.strip()
    return ""


def _atom_link(el):
    for c in el:
        if _local(c.tag) == "link":
            href = c.get("href")
            if href and c.get("rel", "alternate") == "alternate":
                return href
            if (c.text or "").strip():
                return c.text.strip()
    return ""


def parse_feed(raw):
    """RSS 2.0, RSS 1.0 (RDF) and Atom. Returns a list of dicts."""
    root = ET.fromstring(raw)
    out = []
    for el in root.iter():
        name = _local(el.tag)
        if name not in ("item", "entry"):
            continue
        title = _child_text(el, "title")
        link = _child_text(el, "link") or _atom_link(el)
        if not link:
            g = _child_text(el, "guid")
            if g.startswith("http"):
                link = g
        date = _child_text(el, "pubDate", "published", "updated", "date")
        desc = _child_text(el, "description", "summary", "encoded")
        out.append(dict(title=title, link=link, date=date, desc=desc))
    return out


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(s):
    # some feeds encode entities twice ("&amp;#8217;")
    s = html.unescape(html.unescape(s or ""))
    s = _TAG.sub(" ", s)
    return _WS.sub(" ", s).strip()


def parse_date(s, fallback):
    s = (s or "").strip()
    if not s:
        return fallback
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone.utc)
    if d > fallback + timedelta(hours=1):       # a feed dated in the future
        return fallback
    return d


def find_bank(text, curated=False):
    hits = [b for b in BANKS if BANK_PAT[b].search(text)]
    if not hits and curated:
        hits = [b for b, p in CURATED_EXTRA.items() if p.search(text)]
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    # several named - take the one that comes first in the headline
    return min(hits, key=lambda b: BANK_PAT[b].search(text).start()
               if BANK_PAT[b].search(text) else 10**6)


_BYLINE = re.compile(r"\b(?:Interview with|Speech by|Remarks by|Statement by|"
                     r"Blog post by|Op-ed by|Testimony by)\s+(?:Mr\.?\s+|Ms\.?\s+|Dr\.?\s+)?"
                     r"((?:[A-Z][\w\.\-]*\s+){0,3}[A-Z][\w\-]+)")


_LEAD_COLON = re.compile(r"^((?:[A-Z][\w\.\-’']+\s+){0,3}[A-Z][\w\-’']+)\s*:\s")
_LEAD_COMMA = re.compile(r"^([A-Z][a-z][\w\-]+),\s+[A-Z]")


def official_speaker(title, desc):
    m = _LEAD_COLON.match(title)
    if m:
        last = m.group(1).split()[-1]
        if last not in NAME_STOP:
            return last
    m = _LEAD_COMMA.match(title)
    if m and m.group(1) not in NAME_STOP:
        return m.group(1)
    return find_speaker(title) or find_speaker(desc[:300])


def find_speaker(text):
    m = _BYLINE.search(text)
    if m:
        last = m.group(1).split()[-1]
        if last not in NAME_STOP and len(last) > 2:
            return last
    for p in SPEAKER_PATS:
        for m in p.finditer(text):
            name = m.group(1)
            if name not in NAME_STOP and len(name) > 2:
                return name
    return ""


def attributed(title):
    return any(p.search(title) for p in ATTRIBUTION)


def tokens(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower())
            if len(w) > 2 and w not in STOPWORDS}


def similar(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def canon_url(u):
    u = (u or "").strip()
    u = re.sub(r"[?#].*$", "", u)
    return u.rstrip("/").lower()


# ---------------------------------------------------------------------------
def classify(src, it, now, near=None):
    title = clean(it["title"])
    desc = clean(it["desc"])
    if not title:
        return None
    url = (it["link"] or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        url = ""
    t = parse_date(it["date"], now)
    kind = src["kind"]

    if kind == "official":
        if OFFICIAL_DROP.search(title + " " + desc[:300]):
            return None
        if src.get("bank"):
            bank = src["bank"]
            if src["id"] in ("ecb", "boe", "snb") and not OFFICIAL_KEEP.search(title + " " + desc[:300]):
                return None
        else:                                           # BIS: every bank in the world
            blob = title + " " + desc[:400]
            bank = next((b for b, p in BIS_PAT.items() if p.search(blob)), None)
            if not bank:
                return None
        speaker = official_speaker(title, desc)
        tier = "official"
    else:
        bank = find_bank(title, curated=(kind == "curated"))
        if not bank:
            return None
        if kind == "headline" and not attributed(title):
            if near is not None and len(near) < 10:
                near.append(title[:160])
            return None
        speaker = find_speaker(title)
        tier = "comment"

    return dict(t=t.strftime("%Y-%m-%dT%H:%M:%SZ"), bank=bank, speaker=speaker,
                hl=title, url=url, src=src["name"], tier=tier, tone="", also=[])


def merge(store, new):
    """Add new items, folding in repeats of the same remark from other sites."""
    by_url = {canon_url(x["url"]): x for x in store if x["url"]}
    added = 0
    for n in new:
        cu = canon_url(n["url"])
        if cu and cu in by_url:
            continue
        nt = tokens(n["hl"])
        n_time = datetime.strptime(n["t"], "%Y-%m-%dT%H:%M:%SZ")
        dup = None
        for x in store:
            if x["bank"] != n["bank"] or x["tier"] != n["tier"]:
                continue
            x_time = datetime.strptime(x["t"], "%Y-%m-%dT%H:%M:%SZ")
            if abs((x_time - n_time).total_seconds()) > 36 * 3600:
                continue
            s = similar(tokens(x["hl"]), nt)
            same_person = n["speaker"] and n["speaker"] == x["speaker"]
            if s >= 0.5 or (same_person and s >= 0.35):
                dup = x
                break
        if dup:
            if n["src"] != dup["src"] and n["src"] not in dup["also"]:
                dup["also"].append(n["src"])
            if not dup["speaker"] and n["speaker"]:
                dup["speaker"] = n["speaker"]
            continue
        store.append(n)
        if cu:
            by_url[cu] = n
        added += 1
    return added


def load_store():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except (OSError, ValueError):
        return []


def fold(s):
    """'Šimkus' and 'Simkus' are the same person to a headline writer."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def load_roster():
    """speakers.json - the hand-assessed lean of each policymaker."""
    try:
        with open(ROSTER, encoding="utf-8") as f:
            people = json.load(f).get("speakers", [])
    except (OSError, ValueError) as e:
        print("speakers.json unreadable, continuing without leans:", e)
        return [], {}
    index = {}
    for p in people:
        for n in [p["name"]] + list(p.get("aliases", [])):
            index[p["bank"] + "|" + fold(n)] = p["name"]
    return people, index


def write_outputs(store, health, now):
    people, index = load_roster()
    store[:] = [x for x in store
                if not (x["tier"] == "official" and OFFICIAL_DROP.search(x["hl"]))]
    for x in store:
        if x["tier"] == "official":
            sp = official_speaker(x["hl"], "")
            if sp:
                x["speaker"] = sp
        elif not x["speaker"]:
            x["speaker"] = find_speaker(x["hl"])
    for x in store:                              # one spelling per person
        if x["speaker"]:
            x["speaker"] = index.get(x["bank"] + "|" + fold(x["speaker"]), x["speaker"])

    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    os.makedirs(os.path.dirname(OUT_JS), exist_ok=True)

    cut_keep = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store = [x for x in store if x["t"] >= cut_keep]
    store.sort(key=lambda x: x["t"], reverse=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump({"items": store}, f, ensure_ascii=False, indent=0)

    cut_show = (now - timedelta(days=SHOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    show = [x for x in store if x["t"] >= cut_show][:MAX_SHOW]
    payload = {
        "built": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cols": ["t", "bank", "speaker", "headline", "tone", "url", "source", "tier", "also"],
        "sources": [{k: v for k, v in h.items() if k != "near_misses"} for h in health],
        "speakers": [[p["bank"], p["name"], p["full"], p["role"], p["lean"],
                      p["confidence"], p["basis"], p["asof"]] for p in people],
        "items": [[x["t"], x["bank"], x["speaker"], x["hl"], x["tone"], x["url"],
                   x["src"], x["tier"], x["also"]] for x in show],
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # json.dumps cannot produce "</script>", but escape "</" anyway so the file
    # is safe even if it is ever inlined into a page
    body = body.replace("</", "<\\/")
    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("window.STELLAR_CB = " + body + ";\n")
    with open(OUT_HEALTH, "w", encoding="utf-8") as f:
        json.dump({"built": payload["built"], "sources": health}, f, indent=1)
    return len(show)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", help="read <dir>/<id>.xml instead of the network")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    store = load_store()
    health = []
    total_new = 0

    for src in SOURCES:
        rec = dict(id=src["id"], name=src["name"], kind=src["kind"], ok=False,
                   fetched=0, kept=0, added=0, error="")
        try:
            if args.fixtures:
                p = os.path.join(args.fixtures, src["id"] + ".xml")
                if not os.path.exists(p):
                    rec["error"] = "no fixture"
                    health.append(rec)
                    continue
                with open(p, "rb") as f:
                    raw = f.read()
            else:
                raw = fetch(src["url"])
            items = parse_feed(raw)
            rec["fetched"] = len(items)
            near = []
            kept = [k for k in (classify(src, it, now, near) for it in items) if k]
            if src["kind"] == "headline":
                rec["near_misses"] = near
            rec["kept"] = len(kept)
            rec["added"] = merge(store, kept)
            total_new += rec["added"]
            rec["ok"] = rec["fetched"] > 0
            if not rec["ok"]:
                rec["error"] = "feed returned no items"
        except Exception as e:                    # one bad source never stops the run
            rec["error"] = (type(e).__name__ + ": " + str(e))[:200]
        health.append(rec)
        if not args.fixtures:
            time.sleep(1)

    shown = write_outputs(store, health, now)

    ok = sum(1 for h in health if h["ok"])
    print("sources ok: %d of %d   new items: %d   in cb.js: %d"
          % (ok, len(health), total_new, shown))
    for h in health:
        print("  %-4s %-36s fetched %3d  kept %3d  new %3d  %s"
              % ("ok" if h["ok"] else "FAIL", h["name"], h["fetched"], h["kept"],
                 h["added"], h["error"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
