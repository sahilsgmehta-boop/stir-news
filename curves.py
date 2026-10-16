"""Curves and inflation for the dashboard's Curves page -> docs/curves.js

  Government yields  2Y, 5Y, 10Y, 30Y for the US, Germany, UK, Japan, France,
                     Italy and Canada from CNBC (quotes for the latest, charts
                     for history: two years daily, ten years weekly)
  US curve shape     Treasury's official daily par yield curve, 1M to 30Y
  US inflation       Treasury's official daily real (TIPS) yield curve;
                     breakeven = nominal par yield - real yield, same maturity,
                     and the 5y5y forward breakeven = 2 x 10Y - 5Y

Spreads (2s10s, 5s30s, cross-market) are worked out in the page from the
levels, so every definition sits in one place. History is refetched once a
day; other runs only update the latest values.

python curves.py [--full] [--dump DIR | --cache DIR]
"""
import csv, hashlib, io, json, os, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "curves.json")
OUT = os.path.join(HERE, "docs", "curves.js")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
KEEP_DAYS = 5 * 366 + 45
COUNTRIES = {   # CNBC symbols for 2Y, 5Y, 10Y, 30Y
    "US": ["US2Y", "US5Y", "US10Y", "US30Y"],
    "DE": ["DE2Y-DE", "DE5Y-DE", "DE10Y-DE", "DE30Y-DE"],
    "UK": ["GB2Y-GB", "GB5Y-GB", "GB10Y-GB", "GB30Y-GB"],
    "JP": ["JP2Y-JP", "JP5Y-JP", "JP10Y-JP", "JP30Y-JP"],
    "FR": ["FR2Y-FR", "FR5Y-FR", "FR10Y-FR", "FR30Y-FR"],
    "IT": ["IT2Y-IT", "IT5Y-IT", "IT10Y-IT", "IT30Y-IT"],
    "CA": ["CA2Y", "CA5Y", "CA10Y", "CA30Y"],
}
TENORS = ["2Y", "5Y", "10Y", "30Y"]
UST_COLS = ["1 Mo", "2 Mo", "3 Mo", "4 Mo", "6 Mo", "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr"]
REAL_COLS = ["5 YR", "7 YR", "10 YR", "20 YR", "30 YR"]
health = {"errors": [], "requests": 0}
MODE = {"dump": None, "cache": None}


def get(url):
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    if MODE["cache"]:
        p = os.path.join(MODE["cache"], key)
        if not os.path.exists(p):
            raise IOError("not in cache")
        return open(p, encoding="utf-8").read()
    health["requests"] += 1
    last = ""
    for attempt in range(3):
        p = subprocess.run(["curl", "-sS", "-L", "-m", "60", "--compressed", "-A", UA,
                            "-w", "\n@@%{http_code}", url], capture_output=True)
        body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n@@")
        if code == "200":
            if MODE["dump"]:
                os.makedirs(MODE["dump"], exist_ok=True)
                open(os.path.join(MODE["dump"], key), "w", encoding="utf-8").write(body)
            return body
        last = f"HTTP {code or 'error'}"
        if code in ("400", "404"):
            break
        time.sleep(2 + 4 * attempt)
    raise IOError(last)


def note(m):
    health["errors"].append(str(m)[:200])


def num(v):
    try:
        return float(str(v).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def cnbc_chart(sym, rng):
    d = json.loads(get(f"https://ts-api.cnbc.com/harmony/app/charts/{rng}.json?symbol={sym}"))
    out = {}
    for b in (d.get("barData") or {}).get("priceBars") or []:
        c, t = num(b.get("close")), str(b.get("tradeTime") or "")
        if c is not None and len(t) >= 8:
            out[f"{t[:4]}-{t[4:6]}-{t[6:8]}"] = c
    return out


def cnbc_quotes(syms):
    out = {}
    for i in range(0, len(syms), 20):
        url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
               + "|".join(syms[i:i + 20]) + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
        try:
            for q in json.loads(get(url))["FormattedQuoteResult"]["FormattedQuote"]:
                last, t = num(q.get("last")), q.get("last_time")
                if last is None or not t:
                    continue
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                if dt.date().weekday() < 5:
                    out[q["symbol"]] = (dt.date().isoformat(), last,
                                        dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        except Exception as e:  # noqa: BLE001
            note(f"CNBC quotes: {e}")
    return out


def treasury(kind, year):
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
           f"{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
    rows = list(csv.DictReader(io.StringIO(get(url))))
    out = {}
    for r in rows:
        try:
            d = datetime.strptime(r["Date"], "%m/%d/%Y").date().isoformat()
        except (KeyError, ValueError):
            continue
        out[d] = {k.strip().upper(): num(v) for k, v in r.items() if k != "Date" and num(v) is not None}
    return out


def main():
    args = sys.argv[1:]
    if "--dump" in args:
        MODE["dump"] = args[args.index("--dump") + 1]
    if "--cache" in args:
        MODE["cache"] = args[args.index("--cache") + 1]
    now = datetime.now(timezone.utc)
    try:
        store = json.load(open(STORE))
    except Exception:  # noqa: BLE001
        store = {}
    full = ("--full" in args or MODE["dump"] or MODE["cache"]
            or store.get("full_date") != now.date().isoformat())
    hist = store.setdefault("hist", {})
    at = store.setdefault("at", {})

    syms = [s for ss in COUNTRIES.values() for s in ss]
    if full:
        for s in syms:
            try:
                h = {}
                weekly, daily = cnbc_chart(s, "5Y"), cnbc_chart(s, "1Y")
                cut = min(daily) if daily else None
                for d, v in weekly.items():
                    if cut is None or d < cut:
                        h[d] = v
                h.update(daily)
                if h:
                    hist[s] = {**hist.get(s, {}), **h}
            except Exception as e:  # noqa: BLE001
                note(f"CNBC chart {s}: {e}")
            if not MODE["cache"]:
                time.sleep(0.25)
    for s, (d, v, t) in cnbc_quotes(syms).items():
        hist.setdefault(s, {})[d] = v
        at[s] = t

    # Treasury curves: every year back five on a full run, this year otherwise
    ust = store.setdefault("ust", {})
    real = store.setdefault("real", {})
    years = range(now.year - 5, now.year + 1) if full else [now.year]
    for y in years:
        for kind, dest in (("daily_treasury_yield_curve", ust), ("daily_treasury_real_yield_curve", real)):
            try:
                dest.update(treasury(kind, y))
            except Exception as e:  # noqa: BLE001
                note(f"Treasury {kind} {y}: {e}")

    cutoff = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    for s in list(hist):
        hist[s] = {d: v for d, v in hist[s].items() if d >= cutoff}
    for dct in (ust, real):
        for d in [d for d in dct if d < cutoff]:
            del dct[d]

    # breakevens from the official curves, same maturity
    be = {}
    for d in sorted(set(ust) & set(real)):
        n, r = ust[d], real[d]
        row = {}
        for t, nk, rk in (("5Y", "5 YR", "5 YR"), ("7Y", "7 YR", "7 YR"), ("10Y", "10 YR", "10 YR"),
                          ("20Y", "20 YR", "20 YR"), ("30Y", "30 YR", "30 YR")):
            if nk in n and rk in r:
                row[t] = round(n[nk] - r[rk], 3)
        if "5Y" in row and "10Y" in row:
            row["5y5y"] = round(2 * row["10Y"] - row["5Y"], 3)
        if row:
            be[d] = row

    def series(dct):
        return sorted(dct.items())

    countries = {}
    for c, ss in COUNTRIES.items():
        countries[c] = {}
        for t, s in zip(TENORS, ss):
            sr = series(hist.get(s, {}))
            countries[c][t] = {"sym": s, "d": [x[0] for x in sr], "v": [x[1] for x in sr], "at": at.get(s)}
    ust_dates = sorted(ust)
    payload = {
        "built": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tenors": TENORS,
        "countries": countries,
        "ust": {"cols": UST_COLS, "dates": ust_dates,
                "rows": [[ust[d].get(k.upper()) for k in UST_COLS] for d in ust_dates]},
        "real": {"cols": ["5Y", "7Y", "10Y", "20Y", "30Y"], "dates": sorted(real),
                 "rows": [[real[d].get(k) for k in REAL_COLS] for d in sorted(real)]},
        "be": {"cols": ["5Y", "7Y", "10Y", "20Y", "30Y", "5y5y"], "dates": sorted(be),
               "rows": [[be[d].get(k) for k in ["5Y", "7Y", "10Y", "20Y", "30Y", "5y5y"]] for d in sorted(be)]},
        "health": health,
    }
    missing = [f"{c} {t}" for c in countries for t in TENORS if not countries[c][t]["v"]]
    if missing:
        health["missing"] = missing
    if full:
        store["full_date"] = now.date().isoformat()
    if not MODE["cache"]:
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        json.dump(store, open(STORE, "w"), separators=(",", ":"))
    out = OUT if not MODE["cache"] else os.path.join(MODE["cache"], "curves.js")
    with open(out, "w") as f:
        f.write("window.CURVES = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(f"curves: {health['requests']} requests, missing: {missing or 'none'}, errors: {health['errors'] or 'none'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("curves failed:", e, file=sys.stderr)
    sys.exit(0)
