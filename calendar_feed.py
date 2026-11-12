"""Economic calendar for the dashboard's Calendar page -> docs/calendar.js

US, euro area (with Germany, France, Italy and Spain), UK, Canada and
Switzerland: data releases, central bank decisions and speeches, with the
forecast, previous and - once printed - actual.

Source: TradingView's public economic-calendar feed (free, no key), which
covers any date range and fills in actuals within minutes of a release.
ForexFactory's weekly feed is the fallback if it does not answer; that one has
no actuals and only covers the current week.

Runs in the 15-minute job: one request.
"""
import hashlib, html, json, os, re, subprocess, sys, time
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "calendar.js")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
COUNTRIES = ["US", "EU", "DE", "FR", "IT", "ES", "GB", "CA", "CH"]
BACK_DAYS, AHEAD_DAYS = 1, 35        # the page shows only what is still to come
MODE = {"dump": None, "cache": None}
health = {"errors": [], "source": None}


def get(url, headers=()):
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    if MODE["cache"]:
        return open(os.path.join(MODE["cache"], key), encoding="utf-8").read()
    cmd = ["curl", "-sS", "-L", "-m", "40", "--compressed", "-A", UA, "-w", "\n@@%{http_code}"]
    for h in headers:
        cmd += ["-H", h]
    last = ""
    for attempt in range(3):
        p = subprocess.run(cmd + [url], capture_output=True)
        body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n@@")
        if code == "200":
            if MODE["dump"]:
                os.makedirs(MODE["dump"], exist_ok=True)
                open(os.path.join(MODE["dump"], key), "w", encoding="utf-8").write(body)
            return body
        last = f"HTTP {code or 'error'}"
        time.sleep(3 + 4 * attempt)
    raise IOError(last)


def tradingview(start, end):
    url = ("https://economic-calendar.tradingview.com/events?from=" + start.strftime("%Y-%m-%dT00:00:00.000Z")
           + "&to=" + end.strftime("%Y-%m-%dT00:00:00.000Z") + "&countries=" + ",".join(COUNTRIES))
    d = json.loads(get(url, ("Origin: https://www.tradingview.com", "Referer: https://www.tradingview.com/")))
    out = []
    for e in d.get("result") or []:
        if e.get("country") not in COUNTRIES or not e.get("date"):
            continue
        out.append({
            "id": "tv" + str(e.get("id")),
            "t": e["date"][:19] + "Z",
            "c": e.get("country"),
            "title": (e.get("title") or "").strip(),
            "ind": e.get("indicator") or "",
            "cat": e.get("category") or "",
            "imp": e.get("importance"),            # -1 low, 0 medium, 1 high
            "period": e.get("period") or "",
            "unit": e.get("unit") or "",
            "scale": e.get("scale") or "",
            "actual": e.get("actual"), "forecast": e.get("forecast"), "previous": e.get("previous"),
            "allday": (e.get("indicator") == "Holidays"),
        })
    return out


FF_CC = {"USD": "US", "EUR": "EU", "GBP": "GB", "CAD": "CA", "CHF": "CH"}
FF_CACHE = os.path.join(HERE, "data", "ff_speeches.json")
LEADER = re.compile(r"Fed Chair|ECB President Lagarde|BOE Gov |BOC Gov |SNB Chairman|Warsh|Lagarde|Bailey|Macklem|Schlegel", re.I)
FF_EVERY = 3600          # ForexFactory asks for no more than a request or two an hour
SPEECH = re.compile(r"\b(speaks|speech|testifies|testimony|press conference|remarks|hearing)\b", re.I)


def forexfactory():
    d = json.loads(get("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
    out = []
    for e in d:
        c = FF_CC.get(e.get("country"))
        if not c:
            continue
        t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        imp = {"High": 1, "Medium": 0, "Low": -1}.get(e.get("impact"), -1)
        out.append({"id": "ff" + hashlib.sha1((e["title"] + e["date"] + c).encode()).hexdigest()[:10],
                    "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": c, "title": e.get("title", ""),
                    "ind": "", "cat": "", "imp": imp, "period": "", "unit": "", "scale": "",
                    "actual": None, "forecast": e.get("forecast") or None, "previous": e.get("previous") or None,
                    "allday": e.get("impact") == "Holiday", "text": True})
    return out


def ff_speeches(now):
    """Central bank speakers for this week and next, from ForexFactory's public
    weekly files. TradingView's feed stopped carrying speeches in early November
    2026, so they come from here and are merged in. Fetched at most once an hour
    (cached in data/ff_speeches.json); a failure keeps the cached copy."""
    try:
        cache = json.load(open(FF_CACHE))
    except Exception:  # noqa: BLE001
        cache = {"at": 0, "events": []}
    if time.time() - cache.get("at", 0) < FF_EVERY and cache.get("events"):
        return cache["events"]
    out, ok = [], False
    for wk in ("thisweek", "nextweek"):
        try:
            d = json.loads(get(f"https://nfs.faireconomy.media/ff_calendar_{wk}.json"))
            ok = True
        except Exception as e:  # noqa: BLE001
            if wk == "thisweek" or "404" not in str(e):   # next week's file only appears late in the week
                health["errors"].append(f"ForexFactory {wk}: {e}"[:200])
            continue
        for e in d:
            c = FF_CC.get(e.get("country"))
            title = (e.get("title") or "").strip()
            if not c or not SPEECH.search(title):
                continue
            try:
                t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
            except Exception:  # noqa: BLE001
                continue
            # the page shows high and medium by default: every speaker is at least medium,
            # the heads of the five banks are high
            imp = max(0, {"High": 1, "Medium": 0, "Low": -1}.get(e.get("impact"), -1))
            if LEADER.search(title):
                imp = 1
            out.append({"id": "ff" + hashlib.sha1((title + e["date"] + c).encode()).hexdigest()[:10],
                        "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": c, "title": title,
                        "ind": "", "cat": "mny", "imp": imp, "period": "", "unit": "", "scale": "",
                        "actual": None, "forecast": None, "previous": None,
                        "allday": False, "text": True, "src": "ForexFactory"})
    if ok:
        cache = {"at": time.time(), "events": out}
        os.makedirs(os.path.dirname(FF_CACHE), exist_ok=True)
        json.dump(cache, open(FF_CACHE, "w"), separators=(",", ":"))
    return cache.get("events", [])


# ---------------------------------------------------------------- official schedules
# The banks' own published schedules are the most reliable times; they are used
# first and ForexFactory fills in the rest (regional Fed presidents, BoE, SNB).
ET, CET = ZoneInfo("America/New_York"), ZoneInfo("Europe/Berlin")
SPEAK_ECB = re.compile(r"speech|speaks|keynote|remarks|panel|fireside|conversation|hearing|testimony|"
                       r"introductory statement|interview|lecture|press conference|dialogue|address", re.I)


def _ev(src, t_local, tz, country, title, imp, allday=False, where=""):
    t = t_local.replace(tzinfo=tz).astimezone(timezone.utc)
    return {"id": src[:2] + hashlib.sha1((title + t.isoformat() + country).encode()).hexdigest()[:10],
            "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": country, "title": title, "ind": "", "cat": "mny",
            "imp": imp, "period": where[:80], "unit": "", "scale": "", "actual": None, "forecast": None,
            "previous": None, "allday": allday, "text": True, "src": src}


def _clock(txt):
    """'10:50 a.m.' / '7:00 p.m.' / '16:30' -> (h, m) or None"""
    m = re.search(r"(\d{1,2})[:.](\d\d)\s*([ap])?\.?m?\.?", txt or "", re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3):
        h = h % 12 + (12 if m.group(3).lower() == "p" else 0)
    return h, mi


def fed_board(start, end):
    """Board members' speeches and testimony, FOMC press conferences, minutes and the
    Beige Book, from the Fed's own calendar (Eastern time)."""
    d = json.loads(get("https://www.federalreserve.gov/json/calendar.json").lstrip("﻿"))
    out = []
    for e in d.get("events", []):
        typ, title = e.get("type", ""), html.unescape(e.get("title", "")).strip()
        if typ not in ("Speeches", "Testimony", "FOMC", "Beige"):
            continue
        if typ == "FOMC" and not re.search(r"Press Conference|Minutes", title):
            continue                      # the decision itself comes from TradingView
        days = [x.strip() for x in str(e.get("days", "")).split(",") if x.strip().isdigit()]
        if len(days) != 1:
            continue
        y, mo = (int(x) for x in str(e.get("month", "0-0")).split("-"))
        ck = _clock(e.get("time", ""))
        try:
            t = datetime(y, mo, int(days[0]), *(ck or (12, 0)))
        except ValueError:
            continue
        if not (start.replace(tzinfo=None) - timedelta(days=1) <= t <= end.replace(tzinfo=None)):
            continue
        if typ in ("Speeches", "Testimony"):
            kind, _, who = title.partition(" - ")
            surname = who.split()[-1] if who else ""
            role = re.sub(r"\s+[A-Z][a-z]+(\s+[A-Z]\.)*(\s+[A-Z][a-z]+)+$", "", who).strip()
            desc = html.unescape(re.sub(r"<[^>]+>", "", e.get("description", ""))).strip()
            label = f"Fed {role} {surname} - {kind.lower()}" + (f": {desc}" if desc else "")
            imp = 1 if re.search(r"^Chair\b", role) or typ == "Testimony" else 0
        else:
            label, imp = "Fed " + title if not title.startswith("FOMC") else title, 1 if "Press" in title or "Minutes" in title else 0
        where = html.unescape(re.sub(r"<[^>]+>", "", e.get("location", ""))).replace("At ", "", 1)
        out.append(_ev("FedBoard", t, ET, "US", label, imp, allday=not ck, where=where))
    return out


def ecb_weekly(start, end):
    """Executive Board speaking engagements from the ECB's weekly schedule (CET).
    Press contacts on that page are left out on purpose."""
    page = get("https://www.ecb.europa.eu/press/calendars/weekly/html/index.en.html")
    out = []
    for dt_txt, dd in re.findall(r"<dt>\s*([^<]+?)\s*</dt>\s*<dd>(.*?)</dd>", page, re.S):
        who = re.search(r"Board member:</strong>\s*([^<]+)", dd)
        evm = re.search(r"Event:</strong>(.*?)<br", dd, re.S)
        if not who or not evm:
            continue
        event = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", evm.group(1)))).strip()
        if not SPEAK_ECB.search(event):
            continue                      # Eurogroup/Ecofin attendance and the like
        try:
            day = datetime.strptime(re.sub(r"^\w+,\s*", "", dt_txt.strip()), "%d %B %Y")
        except ValueError:
            continue
        tm = re.search(r"Time:</strong>\s*([^<]+)", dd)
        ck = _clock(tm.group(1)) if tm else None
        t = day.replace(hour=ck[0], minute=ck[1]) if ck else day.replace(hour=12)
        if not (start.replace(tzinfo=None) - timedelta(days=1) <= t <= end.replace(tzinfo=None)):
            continue
        name = who.group(1).strip()
        surname = name.split()[-1]
        imp = 1 if surname in ("Lagarde", "Lane") else 0
        out.append(_ev("ECB", t, CET, "EU", f"ECB {surname}: {event}"[:160], imp, allday=not ck))
    return out


def boc_events(start, end):
    """Speeches from the Bank of Canada's upcoming-events page (Eastern time; most
    list no time until a media advisory three business days before)."""
    page = get("https://www.bankofcanada.ca/press/upcoming-events/")
    out = []
    for art in re.findall(r"<article class=\"media\".*?</article>", page, re.S):
        dm = re.search(r"media-date[^>]*>\s*([A-Z][a-z]+ \d{1,2}, \d{4})", art)
        hm = re.search(r"media-heading\">\s*<a[^>]*>([^<]+)</a>", art)
        if not dm or not hm or not re.match(r"\s*(Speech|Remarks|Press conference|Testimony|Appearance)", hm.group(1), re.I):
            continue
        ex = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", (re.search(r"media-excerpt\">(.*?)</div>", art, re.S) or [None, ""])[1]))).strip()
        try:
            day = datetime.strptime(dm.group(1), "%B %d, %Y")
        except ValueError:
            continue
        ck = _clock(ex)
        t = day.replace(hour=ck[0], minute=ck[1]) if ck else day.replace(hour=12)
        if not (start.replace(tzinfo=None) - timedelta(days=1) <= t <= end.replace(tzinfo=None)):
            continue
        head = html.unescape(hm.group(1)).strip()            # "Speech: Tiff Macklem, Governor"
        kind, _, rest = head.partition(":")
        name = rest.split(",")[0].strip()
        surname = name.split()[-1] if name else ""
        imp = 1 if "Governor" in rest and "Deputy" not in rest else 0
        out.append(_ev("BoC", t, ET, "CA", f"BoC {surname} {kind.lower()}" + (f" ({ex[:70]})" if ex else ""), imp, allday=not ck))
    return out


STOP = {"speaks", "speech", "member", "president", "governor", "chair", "deputy", "fomc", "board",
        "vice", "supervision", "remarks", "keynote", "panel", "discussion", "participation", "economic",
        "outlook", "conference", "german", "buba", "conversation", "external"}


def _names(s):
    return {w for w in re.findall(r"[A-Za-zÀ-ž]{4,}", s.lower())} - STOP


def _same(a, b, hours=3):
    if a["c"] != b["c"]:
        return False
    ta = datetime.fromisoformat(a["t"].replace("Z", "+00:00"))
    tb = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
    near = abs((ta - tb).total_seconds()) <= hours * 3600 or ((a.get("allday") or b.get("allday")) and ta.date() == tb.date())
    return near and bool(_names(a["title"]) & _names(b["title"]))


def merge_speeches(events, official, ff):
    """The banks' own schedules win; then ForexFactory adds what nobody else has.
    A TradingView speech that matches an official one is replaced by it."""
    stats = {"official": len(official), "ff": len(ff), "added": 0, "replaced": 0}
    for o in official:
        tv = [e for e in events if SPEECH.search(e["title"]) and _same(e, o)]
        for e in tv:
            events.remove(e); stats["replaced"] += 1
        if not any(e.get("src") in ("FedBoard", "ECB", "BoC") and _same(e, o, 1) for e in events):
            events.append(o); stats["added"] += 1
    for f in ff:
        if any(_same(e, f) for e in events if SPEECH.search(e["title"]) or e.get("src")):
            continue
        events.append(f); stats["added"] += 1
    return stats


def main():
    args = sys.argv[1:]
    if "--dump" in args:
        MODE["dump"] = args[args.index("--dump") + 1]
    if "--cache" in args:
        MODE["cache"] = args[args.index("--cache") + 1]
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(days=BACK_DAYS), now + timedelta(days=AHEAD_DAYS)
    events = []
    try:
        events = tradingview(start, end)
        health["source"] = "TradingView"
    except Exception as e:  # noqa: BLE001
        health["errors"].append(f"TradingView: {e}"[:200])
    if not events:
        try:
            events = forexfactory()
            health["source"] = "ForexFactory (no actuals)"
        except Exception as e:  # noqa: BLE001
            health["errors"].append(f"ForexFactory: {e}"[:200])
    if events and health["source"] == "TradingView":
        official, counts = [], {}
        for name, fn in (("Fed Board", fed_board), ("ECB", ecb_weekly), ("BoC", boc_events)):
            try:
                got = fn(start, end); official += got; counts[name] = len(got)
            except Exception as e:  # noqa: BLE001
                counts[name] = "failed"
                health["errors"].append(f"{name} schedule: {e}"[:200])
        try:
            ff = ff_speeches(now)
        except Exception as e:  # noqa: BLE001
            ff = []
            health["errors"].append(f"ForexFactory: {e}"[:200])
        counts["ForexFactory"] = len(ff)
        stats = merge_speeches(events, official, ff)
        stats["by_source"] = counts
        # a coverage check, so a source going quiet is noticed: a normal week has
        # well over a dozen central bank speakers across these banks
        wk = now + timedelta(days=7)
        n7 = sum(1 for e in events if SPEECH.search(e["title"]) or e.get("src") in ("FedBoard", "ECB", "BoC")
                 if now - timedelta(hours=12) <= datetime.fromisoformat(e["t"].replace("Z", "+00:00")) <= wk)
        stats["next_7_days"] = n7
        if n7 < 5:
            health["errors"].append(f"only {n7} central bank speakers in the next 7 days - a source may have stopped")
        health["speeches"] = stats
    if not events:
        # keep the last good file rather than publishing an empty calendar
        print("calendar: no source answered; keeping the previous file", health["errors"])
        return
    events.sort(key=lambda e: (e["t"], -(e["imp"] if e["imp"] is not None else -1), e["c"]))
    built = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"built": built, "from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d"),
               "events": events, "health": health}
    out = OUT if not MODE["cache"] else os.path.join(MODE["cache"], "calendar.js")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write("window.ECON_CAL = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n")
    print(f"calendar: {len(events)} events from {health['source']}, errors: {health['errors'] or 'none'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("calendar failed:", e, file=sys.stderr)
    sys.exit(0)
