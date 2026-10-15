"""CME open interest for the dashboard - collected online, no Excel.

Runs in the same GitHub Action as collect.py and fixings.py (every 30 minutes).
Free, official, no key. Writes docs/oi.js:

    window.STELLAR_OI = {
      built: "2026-10-15T13:37:00Z",
      source: "CME volume and open interest report",
      cols: ["date","pid","product","month","settle","volume","oi","status"],
      rows: [["2026-10-14","8462","3M SOFR","DEC 26","95.7150",950006,1519588,"P"], ...],
      health: {...}
    };

WHERE THE NUMBERS COME FROM
  Open interest and volume: CME's volume and open interest report
    /CmeWS/mvc/Volume/Details/F/{productId}/{yyyymmdd}/{F|P}
  "atClose" is that trade date's own open interest. It matched Bloomberg's
  OI and OI change to the contract on 15 Oct 2026 (21 lines checked).
  Settle: CME's settlements page for the same date. ONLY the settle is taken
  from there - its open interest column is the PRIOR day's, which is exactly
  the one-day-late bug the old Excel macro had.

TIMING
  Preliminary ("P") figures for trade date T publish about 05:20 UTC on T+1
  (10:50 IST); final ("F") about 15:20 UTC on T+1 (20:50 IST). A day held as
  preliminary is fetched again on later runs until it is final.

BUDGET
  The first run has about six weeks to backfill. Each run makes at most
  MAX_REQUESTS calls, newest dates first, so a backfill completes over a few
  runs and never pushes the shared workflow past its time limit.

A failed fetch never wipes good data, and this script never fails the run.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "oi.json")
OUT = os.path.join(HERE, "docs", "oi.js")

# Verified against the dsHeader of CME's settlements service. DO NOT guess:
# a wrong id returns real, plausible numbers for an entirely different
# contract (302 is Mini-Corn, 323 Chicago Wheat). Order = order on the page.
PRODUCTS = [
    ("8462", "3M SOFR"),
    ("8463", "1M SOFR"),
    ("305", "Fed Funds"),
    ("303", "2Y Note"),
    ("329", "5Y Note"),
    ("316", "10Y Note"),
    ("7978", "Ultra 10Y"),     # "Ultra 10-Year U.S. Treasury Note Futures", 15 Oct 2026
    ("307", "30Y Bond"),
    ("3141", "Ultra Bond"),
]

LOOKBACK_DAYS = 42      # calendar days kept - about 30 sessions, enough for 1 month
RECENT_DAYS = 4         # preliminary or empty days younger than this are re-asked
SETTLE_DAYS = 7         # settles only matter for the latest session shown
MAX_MONTHS = 24         # contract months kept per product
MAX_REQUESTS = 160      # per run
PAUSE = 0.25            # seconds between requests
MAX_FAILS = 4           # consecutive network failures before giving up this run
# A recent preliminary or empty day is re-asked only in the first run of these
# UTC hours - just after CME's preliminary (~05:20) and final (~15:20) releases,
# plus a few catch-ups - rather than every 30 minutes. Keyed to the clock so
# nothing has to be remembered between runs.
RECHECK_UTC_HOURS = (5, 6, 8, 11, 15, 16, 18, 21)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

VOI = "https://www.cmegroup.com/CmeWS/mvc/Volume/Details/F/{pid}/{ymd}/{kind}?tradeDate={ymd}"
SETTLE = ("https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/{pid}/FUT"
          "?strategy=DEFAULT&tradeDate={mdy}&pageSize=500")


class Budget(Exception):
    pass


class Net:
    def __init__(self):
        self.used = 0
        self.fails = 0
        self.errors = []

    def get_json(self, url):
        if self.used >= MAX_REQUESTS:
            raise Budget()
        if self.fails >= MAX_FAILS:
            raise Budget()
        self.used += 1
        time.sleep(PAUSE)
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.cmegroup.com/"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
            self.fails = 0
            return body
        except Exception as e:
            self.fails += 1
            if len(self.errors) < 8:
                self.errors.append("%s: %s" % (url.split("/CmeWS/mvc/")[-1][:70], str(e)[:80]))
            return None


def num(s):
    s = str(s if s is not None else "").replace(",", "").strip().rstrip("AB")
    if s in ("", "-"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return int(v) if v == int(v) else v


def short_month(m):
    # "DEC 2026" -> "DEC 26", the form the dashboard sorts on
    p = str(m or "").strip().upper().split()
    if len(p) == 2 and len(p[1]) == 4:
        return p[0] + " " + p[1][2:]
    return " ".join(p)


def fetch_voi(net, pid, day, kinds=("F", "P")):
    """[(month, volume, oi)], status   or   [], None   (not published / holiday)
    Returns None, None on a network failure."""
    ymd = day.strftime("%Y%m%d")
    answered = False
    for kind in kinds:
        body = net.get_json(VOI.format(pid=pid, ymd=ymd, kind=kind))
        if body is None or "monthData" not in body:
            continue
        answered = True
        rows = []
        for r in body.get("monthData") or []:
            m = short_month(r.get("month"))
            if not m or m == "-":
                continue
            rows.append((m, num(r.get("totalVolume")), num(r.get("atClose"))))
            if len(rows) >= MAX_MONTHS:
                break
        if rows:
            return rows, kind
    return ([], None) if answered else (None, None)


def fetch_settles(net, pid, day):
    body = net.get_json(SETTLE.format(pid=pid, mdy=day.strftime("%m/%d/%Y")))
    out = {}
    for r in (body or {}).get("settlements") or []:
        m = str(r.get("month") or "").strip().upper()
        if not m or m == "TOTAL":
            continue
        s = str(r.get("settle") or "").strip().rstrip("AB")
        if s and s != "-":
            out.setdefault(m, s)        # TEXT: Treasuries settle in 32nds, "104'190"
    return out


def weekdays(today):
    d = today
    while d >= today - dt.timedelta(days=LOOKBACK_DAYS):
        if d.weekday() < 5:
            yield d
        d -= dt.timedelta(days=1)


def main():
    try:
        with open(STORE, encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, ValueError):
        store = {}
    days = store.setdefault("days", {})       # iso -> pid -> {"s": status, "rows": [...]}
    empty = store.setdefault("empty", {})     # "iso|pid" -> True (holiday / not published)
    store.pop("asked", None)
    clock = dt.datetime.now(dt.timezone.utc)
    recheck = clock.hour in RECHECK_UTC_HOURS and clock.minute < 30

    today = dt.datetime.now(dt.timezone.utc).date()
    net = Net()
    fetched = refreshed = 0
    stopped = ""

    try:
        for day in weekdays(today):           # newest first
            iso = day.isoformat()
            recent = (today - day).days <= RECENT_DAYS
            for pid, _name in PRODUCTS:
                have = days.get(iso, {}).get(pid)
                key = iso + "|" + pid
                if have and (have["s"] == "F" or not recent):
                    continue
                if not have and key in empty and not recent:
                    continue
                # a recent day already asked about is re-asked only at set hours
                if (have or key in empty) and not recheck:
                    continue
                # holding a preliminary figure: only the final one is worth asking for
                rows, status = fetch_voi(net, pid, day, ("F",) if have else ("F", "P"))
                if rows is None:
                    continue                  # network trouble - next run
                if not rows:
                    if not have:
                        empty[key] = True
                    continue
                settles = fetch_settles(net, pid, day) if (today - day).days <= SETTLE_DAYS else {}
                days.setdefault(iso, {})[pid] = {
                    "s": status,
                    "rows": [[m, settles.get(m), v, o] for m, v, o in rows],
                }
                empty.pop(key, None)
                if have:
                    refreshed += 1
                else:
                    fetched += 1
    except Budget:
        stopped = ("request budget used - continues next run" if net.used >= MAX_REQUESTS
                   else "CME not answering - stopped after %d failures" % MAX_FAILS)

    # drop history older than the window
    cutoff = (today - dt.timedelta(days=LOOKBACK_DAYS + 3)).isoformat()
    for iso in [k for k in days if k < cutoff]:
        del days[iso]
    for k in [k for k in empty if k[:10] < cutoff]:
        del empty[k]


    health = {"requests": net.used, "fetched": fetched, "refreshed": refreshed,
              "stopped": stopped, "errors": net.errors,
              "latest": max(days) if days else None}
    print("oi:", json.dumps(health))

    before = None
    try:
        with open(STORE, encoding="utf-8") as f:
            before = json.load(f)
    except (OSError, ValueError):
        pass
    if before is not None and before.get("days") == days and os.path.exists(OUT):
        # nothing new; keep the file (and the repo) unchanged
        if before.get("health", {}).get("errors") == health["errors"]:
            print("oi: no change")
            return

    store["built"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store["health"] = health
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(store, f, separators=(",", ":"), sort_keys=True)

    names = dict(PRODUCTS)
    order = {pid: i for i, (pid, _) in enumerate(PRODUCTS)}
    rows = []
    for iso in sorted(days):
        for pid in sorted(days[iso], key=lambda p: order.get(p, 99)):
            e = days[iso][pid]
            for m, s, v, o in e["rows"]:
                rows.append([iso, pid, names.get(pid, pid), m, s, v, o, e["s"]])
    # the dashboard lists products in order of first appearance - put the
    # oldest date's rows in product order first so the chips come out right
    rows.sort(key=lambda r: (order.get(r[1], 99), r[0]))
    js = {"built": store["built"], "source": "CME volume and open interest report",
          "cols": ["date", "pid", "product", "month", "settle", "volume", "oi", "status"],
          "rows": rows, "health": health}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.STELLAR_OI = " + json.dumps(js, separators=(",", ":")) + ";\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                    # never fail the workflow
        print("oi: unexpected error, nothing written:", e, file=sys.stderr)
