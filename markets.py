"""Cross-asset performance for the dashboard's Markets page -> docs/markets.js

Sources, all free:
  Yahoo Finance chart API   equities, sector and style funds, commodity futures,
                            bond funds, FX, crypto, VIX, MOVE
  CNBC quotes and charts    government bond yields (US curve, global 2Y/10Y)
                            and VSTOXX, which Yahoo does not carry

The asset list lives in markets_assets.json. Daily closes are kept in
data/markets.json: the full history (5 years) is fetched once a day, and every
other run (each 30 minutes) only fetches the last few days and the latest price.

Returns are in each asset's own currency. Yields are changes in basis points.
Futures (=F) are Yahoo's front contract, which jumps when it rolls to the next
month (natural gas into winter can jump 10-15%; lean hogs Aug 2026 -15%). So each
run looks up the actual contract behind the =F symbol (e.g. NGZ26.NYM) and keeps
that contract's own daily history (data/markets.json "ctr"). Every return and the
year's chart are measured on that one contract, so no roll is ever counted as a
price move. Horizons older than the contract's own history (a newly listed month)
are left blank rather than joined to another contract. When the front month moves
on, the new contract's history is fetched. A Sunday-evening futures price counts for
Monday, and weekend dates are dropped for futures.
(Until 18 Nov 2026 a roll-ratio method was used; it recorded the same roll on several
days and compounded them, which made lean hogs read -12.7% on a -4.3% day.)

python markets.py              normal run
python markets.py --full       refetch all history
python markets.py --dump DIR   save raw downloads   --cache DIR  read them back
"""
import hashlib, json, os, re, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "markets_assets.json")
STORE = os.path.join(HERE, "data", "markets.json")
OUT = os.path.join(HERE, "docs", "markets.js")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
HORIZONS = ["1D", "1W", "MTD", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y"]
KEEP_DAYS = 5 * 366 + 45
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
        p = subprocess.run(["curl", "-sS", "-L", "-m", "40", "--compressed", "-A", UA,
                            "-H", "Accept: application/json,*/*", "-w", "\n@@%{http_code}", url],
                           capture_output=True)
        body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n@@")
        if code == "200":
            if MODE["dump"]:
                os.makedirs(MODE["dump"], exist_ok=True)
                open(os.path.join(MODE["dump"], key), "w", encoding="utf-8").write(body)
            return body
        last = f"HTTP {code or 'error'}"
        if code in ("404", "400"):
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


# ------------------------------------------------------------- Yahoo
def yahoo(sym, rng, fut=None):
    d = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"))
    r = d["chart"]["result"][0]
    off = int(r["meta"].get("gmtoffset") or 0)
    ts = r.get("timestamp") or []
    cl = (r["indicators"]["quote"][0].get("close") or [])
    # funds: the dividend-adjusted close, so bond and commodity funds count
    # their payouts (for futures and indices it equals the close)
    adj = ((r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or [])
    if len(adj) == len(cl) and any(a is not None for a in adj):
        cl = [a if a is not None else c for a, c in zip(adj, cl)]
    out = {}
    for t, c in zip(ts, cl):
        if c is None:
            continue
        out[datetime.fromtimestamp(t + off, timezone.utc).date().isoformat()] = round(c, 6)
    m = r["meta"]
    fut = is_future(sym) if fut is None else fut
    if fut:   # futures trade Sunday evening: a weekend date is never a trading day
        out = {d: v for d, v in out.items() if date.fromisoformat(d).weekday() < 5}
    px, mt = m.get("regularMarketPrice"), m.get("regularMarketTime")
    if px is not None and mt:
        loc = datetime.fromtimestamp(mt + off, timezone.utc)
        d = loc.date()
        # futures: the evening session (from 5pm exchange time) belongs to the next trading day
        if fut and loc.hour >= 17:
            d += timedelta(days=1)
        while fut and d.weekday() >= 5:
            d += timedelta(days=1)
        out[d.isoformat()] = round(px, 6)
    info = {"ccy": m.get("currency"), "at": (datetime.fromtimestamp(mt, timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ") if mt else None),
            "name": m.get("shortName") or m.get("longName"), "exch": m.get("exchangeName")}
    return out, info


# ------------------------------------------------------------- futures rolls
def is_future(sym):
    return sym.endswith("=F")


MONTH_CODE = {"jan": "F", "feb": "G", "mar": "H", "apr": "J", "may": "K", "jun": "M",
              "jul": "N", "aug": "Q", "sep": "U", "oct": "V", "nov": "X", "dec": "Z"}


CODES = "FGHJKMNQUVXZ"
# where each future's contracts are listed on Yahoo (suffix), used when Yahoo's own code for the =F symbol is off
EXCH = {"CL": "NYM", "BZ": "NYM", "NG": "NYM", "RB": "NYM", "HO": "NYM", "TTF": "NYM", "GC": "CMX", "SI": "CMX",
        "HG": "CMX", "ALI": "CMX", "PL": "NYM", "PA": "NYM", "ZW": "CBT", "ZC": "CBT", "ZS": "CBT", "ZM": "CBT",
        "ZL": "CBT", "KE": "CBT", "KC": "NYB", "SB": "NYB", "CC": "NYB", "CT": "NYB", "OJ": "NYB",
        "LE": "CME", "GF": "CME", "HE": "CME"}


def contract_symbols(sym, info, today=None):
    """Candidates for the contract behind a Yahoo =F symbol: the month Yahoo's name gives ('Natural Gas Dec 26'
    -> NGZ26.NYM, 'Corn Futures,Dec-2026' -> ZCZ26.CBT), then the months either side of it - Yahoo's name can be
    a month or two ahead of the contract actually quoted (Lean Hog 'Feb-2027' was HEZ26 on 18 Nov 2026) or
    behind it. A name with no month (Brent 'Last Day Financ') starts from the current month."""
    name, exch = (info or {}).get("name") or "", (info or {}).get("exch") or ""
    # Yahoo's own exchange code for the =F symbol is sometimes wrong (cotton CT=F said NYM, 18 Nov 2026)
    exchs = [x for x in dict.fromkeys([exch, EXCH.get(sym[:-2])]) if x]
    if not exchs:
        return []
    hits = re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s.,'-]*(\d{4}|\d{2})\b", name.lower())
    if hits:
        mon, yr = hits[-1]
        m, y = CODES.index(MONTH_CODE[mon]), int(yr[-2:])
        offs = [0, 1, -1, 2, -2, 3, -3]
    else:
        t = today or date.today()
        m, y = t.month - 1, t.year % 100
        offs = [0, 1, 2, 3, 4]
    out = []
    for ex in exchs:
        for k in offs:
            mm, yy = (m + k) % 12, (y + (m + k) // 12) % 100
            out.append(f"{sym[:-2]}{CODES[mm]}{yy:02d}.{ex}")
    return out


# ------------------------------------------------------------- CNBC
def cnbc_chart(sym, rng):
    d = json.loads(get(f"https://ts-api.cnbc.com/harmony/app/charts/{rng}.json?symbol={sym}"))
    out = {}
    for b in (d.get("barData") or {}).get("priceBars") or []:
        c = num(b.get("close"))
        t = str(b.get("tradeTime") or "")
        if c is not None and len(t) >= 8:
            out[f"{t[:4]}-{t[4:6]}-{t[6:8]}"] = c
    return out


def cnbc_quotes(syms):
    out = {}
    for i in range(0, len(syms), 20):
        chunk = syms[i:i + 20]
        url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
               + "|".join(chunk) + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
        try:
            d = json.loads(get(url))
            for q in d["FormattedQuoteResult"]["FormattedQuote"]:
                last, t = num(q.get("last")), q.get("last_time")
                if last is None or not t:
                    continue
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                out[q["symbol"]] = {"last": last, "date": dt.date().isoformat(),
                                    "prev": num(q.get("previous_day_closing")),
                                    "at": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        except Exception as e:  # noqa: BLE001
            note(f"CNBC quotes: {e}")
    return out


# ------------------------------------------------------------- returns
def series_from(hist):
    return sorted((d, v) for d, v in hist.items() if v is not None)


def value_on_or_before(s, d):
    """Last (date, value) on or before date d, by bisection."""
    lo, hi = 0, len(s) - 1
    if not s or s[0][0] > d:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if s[mid][0] <= d:
            lo = mid
        else:
            hi = mid - 1
    return s[lo]


def months_back(d, n):
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def returns(s, kind, invert):
    if len(s) < 2:
        return {}, None
    ld, lv = s[-1]
    L = date.fromisoformat(ld)
    refs = {
        "1D": s[-2],
        "1W": value_on_or_before(s, (L - timedelta(days=7)).isoformat()),
        "MTD": value_on_or_before(s, (L.replace(day=1) - timedelta(days=1)).isoformat()),
        "1M": value_on_or_before(s, months_back(L, 1).isoformat()),
        "3M": value_on_or_before(s, months_back(L, 3).isoformat()),
        "6M": value_on_or_before(s, months_back(L, 6).isoformat()),
        "YTD": value_on_or_before(s, date(L.year - 1, 12, 31).isoformat()),
        "1Y": value_on_or_before(s, months_back(L, 12).isoformat()),
        "3Y": value_on_or_before(s, months_back(L, 36).isoformat()),
        "5Y": value_on_or_before(s, months_back(L, 60).isoformat()),
    }
    out = {}
    first = date.fromisoformat(s[0][0])
    for h, ref in refs.items():
        if not ref:
            continue
        # a reference far older than asked means the history does not reach back
        target = {"3Y": months_back(L, 36), "5Y": months_back(L, 60)}.get(h)
        if target and first > target + timedelta(days=10):
            continue
        rv = ref[1]
        if kind == "yield":
            out[h] = round((lv - rv) * 100, 1)
        elif rv:
            r = (rv / lv - 1) if invert else (lv / rv - 1)
            out[h] = round(r * 100, 2)
    return out, ld


def spark(s, kind, invert):
    """About a year of weekly points, for the little chart in each row."""
    if not s:
        return []
    L = date.fromisoformat(s[-1][0])
    pts = []
    for k in range(52, -1, -1):
        p = value_on_or_before(s, (L - timedelta(days=7 * k)).isoformat())
        if p:
            v = p[1]
            pts.append(round((1 / v if invert and v else v), 6))
    return pts


def check_contract(sym, info, h, store, full):
    """Find the actual contract behind sym (the one whose latest price is the =F price) and keep that contract's
    own daily history. Returns are then measured on that one contract, so a roll of the front month never shows
    up as a price move. The stored contract is tried first (one request); its full history is fetched again on
    the daily full run, or when the front month has moved on to a new contract."""
    fut = health.setdefault("futures", {})
    fut[sym] = {"name": info.get("name"), "contract": None}
    C = store.setdefault("ctr", {})
    prev = C.get(sym)
    last = max(h) if h else None
    cands = contract_symbols(sym, info)
    if prev:
        cands = [prev["c"]] + [x for x in cands if x != prev["c"]]
    hit, recent = None, None
    for x in cands:
        try:
            if not MODE["cache"]:
                time.sleep(0.25)
            e, _ = yahoo(x, "1mo", fut=True)
        except Exception:  # noqa: BLE001
            continue
        if last and last in e and h[last] and e[last] and abs(e[last] / h[last] - 1) < 0.002:
            hit, recent = x, e
            break
    if not hit:
        C.pop(sym, None)
        fut[sym]["note"] = "contract not found: front-month series, rolls not adjusted"
        return
    if prev and prev["c"] == hit and not full:
        ch = prev["h"]
    else:
        try:
            if not MODE["cache"]:
                time.sleep(0.25)
            ch, _ = yahoo(hit, "10y", fut=True)
        except Exception as e:  # noqa: BLE001
            note(f"Yahoo {hit} history: {e}")
            ch = dict(prev["h"]) if prev and prev["c"] == hit else {}
    ch.update(recent)
    cut = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    C[sym] = {"c": hit, "h": {d: v for d, v in ch.items() if v and d >= cut}}
    ds = sorted(C[sym]["h"])
    fut[sym].update({"contract": hit, "from": ds[0] if ds else None, "days": len(ds)})


# ------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    if "--dump" in args:
        MODE["dump"] = args[args.index("--dump") + 1]
    if "--cache" in args:
        MODE["cache"] = args[args.index("--cache") + 1]
    now = datetime.now(timezone.utc)
    cfg = json.load(open(CFG))
    try:
        store = json.load(open(STORE))
    except Exception:  # noqa: BLE001
        store = {}
    hist = store.setdefault("hist", {})
    meta = store.setdefault("meta", {})
    full = ("--full" in args or MODE["dump"] or MODE["cache"]
            or store.get("full_date") != now.date().isoformat())

    syms = []
    for g in cfg["groups"]:
        for s in g["subs"]:
            if s.get("proxy"):
                syms.append(s["proxy"])
            for _, sym in s["items"]:
                syms.append(sym)
    syms = list(dict.fromkeys(syms))

    for sym in syms:
        if sym.startswith("cnbc:"):
            continue
        try:
            # "5y" starts a couple of days short of five years, so ask for ten
            got, info = yahoo(sym, "10y" if full or sym not in hist else "5d")
            h = hist.setdefault(sym, {})
            if is_future(sym):    # weekend dates kept from earlier runs
                for d in [d for d in h if date.fromisoformat(d).weekday() >= 5]:
                    del h[d]
            h.update(got)
            meta[sym] = info
            if is_future(sym):
                check_contract(sym, info, h, store, full)
        except Exception as e:  # noqa: BLE001
            note(f"Yahoo {sym}: {e}")
        if not MODE["cache"]:
            time.sleep(0.25)

    cn = [s[5:] for s in syms if s.startswith("cnbc:")]
    for c in cn:
        key = "cnbc:" + c
        if full or key not in hist:
            try:
                h = hist.setdefault(key, {})
                weekly = cnbc_chart(c, "5Y")
                daily = cnbc_chart(c, "1Y")
                cut = min(daily) if daily else None
                for d, v in weekly.items():
                    if cut is None or d < cut:
                        h[d] = v
                h.update(daily)
            except Exception as e:  # noqa: BLE001
                note(f"CNBC chart {c}: {e}")
            if not MODE["cache"]:
                time.sleep(0.25)
    for c, q in cnbc_quotes(cn).items():
        h = hist.setdefault("cnbc:" + c, {})
        # a weekend quote is just Friday's close again; it would read as "no change"
        if date.fromisoformat(q["date"]).weekday() < 5:
            h[q["date"]] = q["last"]
        meta["cnbc:" + c] = {"ccy": None, "at": q["at"]}

    cutoff = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    for sym in list(hist):
        hist[sym] = {d: v for d, v in hist[sym].items() if d >= cutoff}
    store.pop("rolls", None)        # the old roll-ratio method (replaced by one-contract histories, 18 Nov 2026)
    store.pop("expl", None)

    def row(name, sym, kind, invert):
        s = series_from(hist.get(sym, {}))
        extra = {}
        if is_future(sym):
            c = store.get("ctr", {}).get(sym)
            if c and c.get("h"):
                # one contract all the way: no roll in any return. Horizons older than the contract's own
                # history are left out rather than filled from a different contract.
                s = series_from(c["h"])
                extra = {"contract": c["c"].split(".")[0], "since": s[0][0] if s else None}
            else:
                extra = {"unadj": True}
        ret, asof = returns(s, kind, invert)
        m = meta.get(sym, {})
        return dict({"name": name, "sym": sym.replace("cnbc:", ""), "kind": kind, "invert": bool(invert),
                "last": s[-1][1] if s else None, "asof": asof, "at": m.get("at"), "ccy": m.get("ccy"),
                "ret": ret, "spark": spark(s, kind, invert)}, **extra)

    groups = []
    for g in cfg["groups"]:
        subs = []
        for s in g["subs"]:
            kind = s.get("kind", "price")
            inv = s.get("invert", False)
            items = [row(n, sym, kind, inv) for n, sym in s["items"]]
            proxy = s.get("proxy") or (s["items"][0][1] if len(s["items"]) == 1 else None)
            if proxy:
                head = row(s["name"], proxy, kind, inv)
                head["proxy"] = next((n for n, sym in s["items"] if sym == proxy), proxy)
            else:
                avg = {}
                for h in HORIZONS:
                    vs = [it["ret"][h] for it in items if h in it["ret"]]
                    if vs and len(vs) >= max(1, len(items) // 2):
                        avg[h] = round(sum(vs) / len(vs), 2 if kind == "price" else 1)
                head = {"name": s["name"], "kind": kind, "ret": avg, "avg": True}
                # the year's chart: the members rebased to 100 and averaged, week by week (aligned at the latest week)
                sp = [it["spark"] for it in items if it.get("spark") and it["spark"][0]]
                if kind == "price" and sp and len(sp) >= max(1, len(items) // 2):
                    n = min(len(x) for x in sp)
                    head["spark"] = [round(sum(x[len(x) - n + i] / x[len(x) - n] * 100 for x in sp) / len(sp), 3) for i in range(n)]
            sub = {"name": s["name"], "kind": kind, "head": head, "items": items}
            if s.get("tenor"):
                sub["tenor"] = s["tenor"]     # the Markets page shows one tenor of the global yields at a time
            subs.append(sub)
        groups.append({"name": g["name"], "subs": subs})

    missing = [it["name"] for g in groups for s in g["subs"] for it in s["items"] if not it["ret"]]
    if missing:
        health["missing"] = missing
    if full:
        store["full_date"] = now.date().isoformat()
    built = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    store["built"] = built
    payload = {"built": built, "horizons": HORIZONS, "groups": groups, "health": health}
    if not MODE["cache"]:
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        json.dump(store, open(STORE, "w"), separators=(",", ":"))
    out = OUT if not MODE["cache"] else os.path.join(MODE["cache"], "markets.js")
    with open(out, "w") as f:
        f.write("window.MARKETS = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n")
    print(f"markets: {len(syms)} symbols, {health['requests']} requests, "
          f"missing: {missing or 'none'}, errors: {health['errors'] or 'none'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("markets failed:", e, file=sys.stderr)
    sys.exit(0)
