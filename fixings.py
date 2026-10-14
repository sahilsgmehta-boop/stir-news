"""Daily overnight-rate fixings for the dashboard pricer, all free and official:

    sofr, effr   New York Fed reference rates API
    sonia        Bank of England statistical database (series IUDSOIA)
    corra        Bank of Canada Valet API (series AVG.INTWO)
    estr         ECB Data Portal (EST.B.EU000A2X2A25.WT)


Runs in the same GitHub Action as collect.py. Free, official, no key.
Writes docs/fixings.js:

    window.STELLAR_FIX = {
      built: "2026-10-14T12:07:00Z",
      sofr:  [["2026-10-13", 3.89], ...],     # oldest first
      effr:  [["2026-10-09", 3.88], ...],
      sonia / corra / estr: same shape
      range: [3.75, 4.00]                     # fed funds target range, latest
    };

Each fixing is published the morning after the day it belongs to (around
8:00 New York time for SOFR, 9:00 for EFFR), so the latest date is normally
yesterday's business day.

A failed fetch never wipes good data: the last good set is kept in
data/fixings.json and re-published unchanged. This script never exits with an
error, so a NY Fed outage cannot stop the news collector either.
"""
import csv
import datetime as dt
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "fixings.json")
OUT = os.path.join(HERE, "docs", "fixings.js")

# Long enough to cover the oldest SR3 reference quarter still trading (about
# three months) plus a margin. Older fixings are kept in the store too.
LOOKBACK_DAYS = 200

API = "https://markets.newyorkfed.org/api/rates/{path}/search.json?startDate={a}&endDate={b}"
SERIES = {"sofr": "secured/sofr", "effr": "unsecured/effr"}


def fetch(path, start, end):
    url = API.format(path=path, a=start, b=end)
    req = urllib.request.Request(url, headers={"User-Agent": "stir-news fixings (github actions)",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode("utf-8"))
    out, rng = {}, None
    for rec in body.get("refRates", []):
        d = str(rec.get("effectiveDate", ""))[:10]
        v = rec.get("percentRate")
        try:
            dt.date.fromisoformat(d)
            v = float(v)
        except (TypeError, ValueError):
            continue
        if not (-5 < v < 25):               # anything outside this is not a rate
            continue
        out[d] = round(v, 4)
        lo, hi = rec.get("targetRateFrom"), rec.get("targetRateTo")
        if lo is not None and hi is not None:
            try:
                if rng is None or d > rng[0]:
                    rng = (d, [float(lo), float(hi)])
            except (TypeError, ValueError):
                pass
    return out, (rng[1] if rng else None)


UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 stir-news-fixings")


def get(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8-sig", "replace")


def keep(out, d, v):
    try:
        d = dt.date.fromisoformat(str(d)[:10]).isoformat()
        v = float(v)
    except (TypeError, ValueError):
        return
    if -5 < v < 25:
        out[d] = round(v, 4)


def fetch_sonia(start, end):
    # Bank of England database CSV: "DATE,IUDSOIA" then "13 Oct 2026,3.9700"
    a = dt.date.fromisoformat(start).strftime("%d/%b/%Y")
    url = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
           "?csv.x=yes&Datefrom=" + a + "&Dateto=now&SeriesCodes=IUDSOIA"
           "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    out = {}
    for row in csv.reader(io.StringIO(get(url, "text/csv"))):
        if len(row) < 2:
            continue
        for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                keep(out, dt.datetime.strptime(row[0].strip(), fmt).date(), row[1])
                break
            except ValueError:
                pass
    return out, None


def fetch_corra(start, end):
    url = ("https://www.bankofcanada.ca/valet/observations/AVG.INTWO/json?start_date="
           + start + "&end_date=" + end)
    body = json.loads(get(url, "application/json"))
    out = {}
    for o in body.get("observations", []):
        keep(out, o.get("d"), (o.get("AVG.INTWO") or {}).get("v"))
    return out, None


def fetch_estr(start, end):
    url = ("https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT"
           "?startPeriod=" + start + "&endPeriod=" + end + "&format=csvdata")
    out = {}
    rd = csv.DictReader(io.StringIO(get(url, "text/csv")))
    for row in rd:
        keep(out, row.get("TIME_PERIOD"), row.get("OBS_VALUE"))
    return out, None


def fetch_nyfed(path):
    def f(start, end):
        return fetch(path, start, end)
    return f


SOURCES = [("sofr", fetch_nyfed("secured/sofr")), ("effr", fetch_nyfed("unsecured/effr")),
           ("sonia", fetch_sonia), ("corra", fetch_corra), ("estr", fetch_estr)]
KEYS = [k for k, _ in SOURCES]


def main():
    try:
        with open(STORE, encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, ValueError):
        store = {}
    for k in KEYS:
        store.setdefault(k, {})

    end = dt.date.today() + dt.timedelta(days=1)
    start = end - dt.timedelta(days=LOOKBACK_DAYS)
    status = {}
    for key, fn in SOURCES:
        try:
            got, rng = fn(start.isoformat(), end.isoformat())
            if not got:
                raise ValueError("empty response")
            store[key].update(got)            # later publication wins (revisions)
            if key == "effr" and rng:
                store["range"] = rng
            status[key] = "ok, %d fixings, latest %s" % (len(got), max(got))
        except Exception as e:                # keep the last good data
            status[key] = "FAILED (%s), kept %d stored" % (e, len(store[key]))
    print("fixings:", status)

    if not any(store[k] for k in KEYS):
        return                                # nothing good ever fetched; write nothing

    # Only rewrite when a fixing actually changed, so the repository gets one
    # commit a day for this rather than one every half hour.
    try:
        with open(STORE, encoding="utf-8") as f:
            before = json.load(f)
    except (OSError, ValueError):
        before = {}
    same = all(before.get(k) == store.get(k) for k in KEYS + ["range"]) \
        and before.get("status") == status
    if same and os.path.exists(OUT):
        print("fixings: no change")
        return

    store["built"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store["status"] = status
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=1, sort_keys=True)

    js = {
        "built": store["built"],
        **{k: sorted([d, v] for d, v in store[k].items()) for k in KEYS},
        "range": store.get("range"),
        "status": status,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.STELLAR_FIX = " + json.dumps(js, separators=(",", ":")) + ";\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                    # never fail the workflow
        print("fixings: unexpected error, nothing written:", e, file=sys.stderr)
