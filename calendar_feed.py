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
import hashlib, json, os, re, subprocess, sys, time
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
            imp = {"High": 1, "Medium": 0, "Low": -1}.get(e.get("impact"), -1)
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


def merge_speeches(events, speeches):
    """Add speeches TradingView does not already have (same country within 90 minutes
    and a shared name word counts as the same event)."""
    have = [e for e in events if SPEECH.search(e["title"])]
    words = lambda s: {w for w in re.findall(r"[A-Za-z]{4,}", s.lower())} - {"speaks", "speech", "member", "president", "governor", "chair", "deputy"}
    added = 0
    for s in speeches:
        ts = datetime.fromisoformat(s["t"].replace("Z", "+00:00"))
        dup = any(e["c"] == s["c"] and abs((datetime.fromisoformat(e["t"].replace("Z", "+00:00")) - ts).total_seconds()) <= 5400
                  and words(e["title"]) & words(s["title"]) for e in have)
        if not dup:
            events.append(s); added += 1
    health["speeches"] = {"source": "ForexFactory", "found": len(speeches), "added": added}


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
        try:
            merge_speeches(events, ff_speeches(now))
        except Exception as e:  # noqa: BLE001
            health["errors"].append(f"speeches: {e}"[:200])
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
