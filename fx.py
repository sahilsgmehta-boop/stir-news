"""G10 currencies for the dashboard's Currencies page - collected online, no Excel.

Runs in the same GitHub Action as collect.py (every 30 minutes). Writes
docs/fx.js in exactly the shape the old Excel macro wrote, so the page is
unchanged:

    window.STELLAR_FX = {
      built: "2026-10-15T14:07:00Z",
      base:  "USD",
      ccys:  ["USD","EUR","JPY","GBP","CHF","CAD","AUD","NZD","SEK","NOK"],
      live:  {source: "Twelve Data", at: "...", rate: {"EUR": [spot, prevClose], ...}} | null,
      hist:  [["2025-09-10", eur, jpy, ...], ...]      # units per USD, oldest first
    };

SOURCES
  History (week, month, YTD, 1 year): ECB reference rates via Frankfurter,
    api.frankfurter.dev. No key. One daily fix around 16:00 CET.
  Live spot + previous close (the Day view): Twelve Data /quote, all nine pairs
    in ONE batched request (the free plan allows 8 requests a minute and 800
    credits a day; one batch of nine every 30 minutes is about 430 a day).
    Needs the key in the repository secret TWELVE_DATA_KEY. Without it the
    page still works: the Day view falls back to the last two ECB fixes and
    says so.

THE KEY IS NEVER WRITTEN ANYWHERE: not to the output, not to the store, not to
the log. Error messages are scrubbed of it before they are printed.

Pairs are requested the way the market quotes them (EUR/USD, USD/JPY ...) and
inverted where needed, because an inverted symbol is not guaranteed to exist.
This script never fails the run, and a failed fetch never wipes good data.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "fx.json")
OUT = os.path.join(HERE, "docs", "fx.js")

CCYS = ["EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK"]
# currency, market symbol, True when quoted as CCY/USD (so invert to get per-USD)
PAIRS = [("EUR", "EUR/USD", True), ("JPY", "USD/JPY", False), ("GBP", "GBP/USD", True),
         ("CHF", "USD/CHF", False), ("CAD", "USD/CAD", False), ("AUD", "AUD/USD", True),
         ("NZD", "NZD/USD", True), ("SEK", "USD/SEK", False), ("NOK", "USD/NOK", False)]
HIST_DAYS = 400          # enough for the 1-year view

KEY = os.environ.get("TWELVE_DATA_KEY", "").strip()
UA = "stir-news fx (github actions)"


def scrub(s):
    s = str(s)
    return s.replace(KEY, "<key>") if KEY else s


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_history(today):
    start = (today - dt.timedelta(days=HIST_DAYS)).isoformat()
    url = ("https://api.frankfurter.dev/v1/%s..%s?base=USD&symbols=%s"
           % (start, today.isoformat(), ",".join(CCYS)))
    body = get_json(url)
    rows = []
    for d, rates in sorted((body.get("rates") or {}).items()):
        if len(d) != 10:
            continue
        rows.append([d] + [rates.get(c) for c in CCYS])
    if len(rows) < 50:
        raise ValueError("only %d days returned" % len(rows))
    return rows


def _num(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _quote_url(symbols):
    return ("https://api.twelvedata.com/quote?symbol="
            + urllib.parse.quote(",".join(symbols), safe=",") + "&apikey=" + KEY)


def fetch_live():
    """{ccy: [spot, prevClose]} per USD, the newest quote time, and a note."""
    want = {sym: (ccy, inv) for ccy, sym, inv in PAIRS}
    got, at, note = {}, "", ""

    def take(sym, q):
        nonlocal at, note
        if not isinstance(q, dict):
            return
        if q.get("status") == "error" or q.get("code"):
            note = note or str(q.get("message", ""))[:120]
            return
        ccy, inv = want[sym]
        px, pc = _num(q.get("close")), _num(q.get("previous_close"))
        if px is None:
            return
        got[ccy] = [1 / px if inv else px, (1 / pc if inv else pc) if pc else None]
        at = max(at, str(q.get("datetime") or ""))

    def batch(symbols):
        nonlocal note
        body = get_json(_quote_url(symbols))
        if not isinstance(body, dict):
            return
        if len(symbols) == 1:
            take(symbols[0], body)
        elif "symbol" not in body and not body.get("code"):
            for sym, q in body.items():       # several symbols come back keyed by symbol
                if sym in want:
                    take(sym, q)
        else:                                 # a single error comes back flat
            note = note or str(body.get("message", ""))[:120]

    # The free plan allows 8 credits a MINUTE and each symbol costs one, so
    # nine at once would always lose the ninth. Two batches a minute apart.
    syms = [sym for _, sym, _ in PAIRS]
    for i, chunk in enumerate((syms[:5], syms[5:])):
        if i:
            time.sleep(62)
        try:
            batch(chunk)
        except Exception as e:
            note = note or scrub(e)[:120]
    missing = [sym for ccy, sym, _ in PAIRS if ccy not in got]
    missing = missing[:8]
    if missing and got:                       # one more go for anything missed (not when nothing worked - a bad key stays bad)
        time.sleep(62)
        try:
            batch(missing)
        except Exception as e:
            note = note or scrub(e)[:120]
    return got, at, note


def main():
    try:
        with open(STORE, encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, ValueError):
        store = {}

    # The job runs every 15 minutes, but the free Twelve Data plan allows 800
    # credits a day and each refresh costs 9, so currencies refresh at most
    # every 25 minutes (about 450 credits a day, even if every run happens).
    last = store.get("built")
    if last:
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
        if age < dt.timedelta(minutes=25):
            print(f"fx: refreshed {int(age.total_seconds() // 60)} minutes ago, skipping")
            return

    today = dt.datetime.now(dt.timezone.utc).date()
    status = {}

    try:
        store["hist"] = fetch_history(today)
        status["history"] = "ok, %d days, latest %s" % (len(store["hist"]), store["hist"][-1][0])
    except Exception as e:
        status["history"] = "FAILED (%s), kept %d stored" % (scrub(e)[:100], len(store.get("hist") or []))

    if not KEY:
        store["live"] = None
        status["live"] = "no TWELVE_DATA_KEY secret - Day view uses the last ECB fixes"
    else:
        try:
            got, at, note = fetch_live()
            if got:
                store["live"] = {"source": "Twelve Data", "at": at, "rate": got}
            missing = [c for c in CCYS if c not in got]
            status["live"] = ("ok, %d of 9" % len(got)
                              + (", missing " + " ".join(missing) if missing else "")
                              + (" - " + scrub(note) if note and missing else ""))
        except Exception as e:
            status["live"] = "FAILED (%s), kept last" % scrub(e)[:100]
    print("fx:", json.dumps(status))

    if not store.get("hist"):
        return                                # nothing good yet; write nothing

    before = None
    try:
        with open(STORE, encoding="utf-8") as f:
            before = json.load(f)
    except (OSError, ValueError):
        pass
    if (before is not None and before.get("hist") == store.get("hist")
            and before.get("live") == store.get("live") and os.path.exists(OUT)):
        print("fx: no change")
        return

    store["built"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store["status"] = status
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(store, f, separators=(",", ":"))

    js = {"built": store["built"], "base": "USD", "ccys": ["USD"] + CCYS,
          "live": store.get("live"), "hist": store["hist"], "status": status}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.STELLAR_FX = " + json.dumps(js, separators=(",", ":")) + ";\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                    # never fail the workflow
        print("fx: unexpected error, nothing written:", scrub(e), file=sys.stderr)
