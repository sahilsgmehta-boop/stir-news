"""Debt-limit tracker for the STIR dashboard's Repo page -> docs/debtlimit.js (window.DEBTLIMIT).

Public data only:
  Treasury Daily Treasury Statement (fiscaldata.treasury.gov): debt subject to the limit, the limit,
    the TGA, total deposits/withdrawals and public-debt cash issues/redemptions (to strip borrowing out).
  Kalshi and Polymarket public market data: any open market about the debt ceiling / limit / default.
  data/debtlimit_sources.json: published estimates (CBO, BPC, NTU, ...), kept by hand.

Model (all $bn):
  1. Binding date. Room = limit - debt subject to limit. Debt is projected forward with the daily
     debt changes of analog years with no debt limit in force over the same calendar days
     (Nov-Jul 2023-24 and 2025-26), scaled by how fast the deficit is running now versus then.
  2. X-date. From the binding day: resources = TGA on that day + extraordinary measures (EM).
     Each day resources fall by the non-debt cash deficit (deposits less withdrawals, both
     excluding public-debt cash issues and redemptions), taken from the analog years' same
     calendar days and scaled the same way. The one-time 30 June measure is added if the
     standoff reaches it. X-date = first day resources drop below a minimum cash buffer.
     EM is calibrated on 2023: the size that makes actual 2023 flows run out on 2 June 2023
     (Treasury's X-date was 5 June), grown with federal debt since.
  3. A grid of analogs x deficit scale x EM size x binding date gives the range (10/50/90%).
  Once the limit binds for real, actual TGA and flows replace the projection day by day.
Paces itself: the full run happens at most every 3 hours (the DTS publishes once a day).
"""
import json, os, time, signal, urllib.request, urllib.parse, datetime as dt

OUT, CACHE, SRC = "docs/debtlimit.js", "data/debtlimit_cache.json", "data/debtlimit_sources.json"
FD = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/"
UA = {"User-Agent": "Mozilla/5.0 (stir-news debt-limit tracker)", "Accept": "application/json"}
START = "2021-10-01"
D = dt.date


def _alarm(*a):
    raise TimeoutError("hard timeout")


signal.signal(signal.SIGALRM, _alarm)


def get(u, tries=3):
    err = None
    for i in range(tries):
        signal.alarm(70)
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=50) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            err = e
            time.sleep(3)
        finally:
            signal.alarm(0)
    raise err


def fd_rows(table, flt, fields):
    out, page = [], 1
    while True:
        u = (FD + table + "?filter=" + urllib.parse.quote(flt, safe=":,") + "&fields=" + fields
             + f"&page[size]=10000&page[number]={page}")
        j = json.loads(get(u))
        out += j.get("data", [])
        tot = (j.get("meta") or {}).get("total-pages", 1)
        if page >= tot:
            return out
        page += 1


def num(x):
    try:
        return float(x)
    except Exception:
        return None


def iso(d):
    return d.isoformat()


def p(s):
    return D.fromisoformat(s)


# ------------------------------------------------------------------ data
def refresh(cache):
    days = cache.setdefault("days", {})
    since = START if not days else max(START, iso(p(max(days)) - dt.timedelta(days=10)))
    flt = f"record_date:gte:{since}"
    # debt subject to the limit, and the limit
    for r in fd_rows("debt_subject_to_limit", flt, "record_date,debt_catg,close_today_bal"):
        d = days.setdefault(r["record_date"], {})
        if d.get("_dsl_seen") != since:
            for k in ("pub", "intra", "notsub", "other", "limit"):
                d[k] = 0.0
            d["_dsl_seen"] = since
        v = (num(r["close_today_bal"]) or 0) / 1000
        c = r["debt_catg"]
        key = {"Debt Held by the Public": "pub", "Intragovernmental Holdings": "intra", "Debt Not Subject to Limit": "notsub",
               "Other Debt Subject to Limit": "other", "Statutory Debt Limit": "limit"}.get(c)
        if key:
            d[key] += v
    # TGA close and total deposits / withdrawals (current format puts the amount in open_today_bal)
    for r in fd_rows("operating_cash_balance", flt, "record_date,account_type,close_today_bal,open_today_bal"):
        d = days.setdefault(r["record_date"], {})
        a = r["account_type"]
        v = num(r["open_today_bal"]) if num(r["close_today_bal"]) is None else num(r["close_today_bal"])
        if a in ("Treasury General Account (TGA) Closing Balance",):
            d["tga"] = (num(r["open_today_bal"]) or 0) / 1000
        elif a == "Total TGA Deposits (Table II)":
            d["dep"] = (num(r["open_today_bal"]) or 0) / 1000
        elif a == "Total TGA Withdrawals (Table II) (-)":
            d["wd"] = (num(r["open_today_bal"]) or 0) / 1000
        elif a == "Treasury General Account (TGA)" and v is not None and "tga" not in d:
            d["tga"] = v / 1000
    # public-debt cash issues and redemptions (to strip borrowing out of the cash flows)
    for cat, key in (("Public Debt Cash Issues (Table IIIB)", "pdi"), ("Public Debt Cash Redemp. (Table IIIB)", "pdr")):
        for r in fd_rows("deposits_withdrawals_operating_cash", flt + f",transaction_catg:eq:{cat}",
                         "record_date,transaction_type,transaction_catg,transaction_today_amt"):
            d = days.setdefault(r["record_date"], {})
            d[key] = (num(r["transaction_today_amt"]) or 0) / 1000
    for k, d in days.items():
        d.pop("_dsl_seen", None)
        if "pub" in d and "limit" in d:
            d["dsl"] = round(d["pub"] + d["intra"] - d["notsub"] + d.get("other", 0), 1)
        if all(x in d for x in ("dep", "wd", "pdi", "pdr")):
            d["net"] = round((d["dep"] - d["pdi"]) - (d["wd"] - d["pdr"]), 2)   # non-debt cash flow; negative = deficit


# ------------------------------------------------------------------ model helpers
def series(days, key):
    return {p(k): v[key] for k, v in days.items() if key in v and v[key] is not None}


def same_day(d, year_shift):
    try:
        return d.replace(year=d.year - year_shift)
    except ValueError:
        return d.replace(year=d.year - year_shift, day=28)


LAST = [None]


def flow_on(net, day, shift):
    """Non-debt cash flow on the analog day. Cash flows don't depend on the debt limit, so if the
    analog day is past the data, step back another year."""
    a = same_day(day, shift)
    while LAST[0] and a > LAST[0]:
        shift += 1
        a = same_day(day, shift)
    return net.get(a, 0.0)


def deficit_scale(net, today, shift):
    """Trailing-180-day deficit now vs the analog year's same window."""
    def tot(end):
        return -sum(v for d, v in net.items() if end - dt.timedelta(days=180) < d <= end)
    a, b = tot(today), tot(same_day(today, shift))
    return a / b if b > 100 and a > 100 else 1.0


def ddsl_on(dsl, day):
    """Change in debt subject to the limit on a business day (0 otherwise)."""
    if day not in dsl:
        return 0.0
    prev = day - dt.timedelta(days=1)
    for _ in range(6):
        if prev in dsl:
            return dsl[day] - dsl[prev]
        prev -= dt.timedelta(days=1)
    return 0.0


def project_binding(dsl, net, today, room, shift, k):
    """First day the analog-year debt path (scaled by k) uses up the room. None if beyond 300 days."""
    cum = 0.0
    for i in range(1, 300):
        day = today + dt.timedelta(days=i)
        cum += k * ddsl_on(dsl, same_day(day, shift))
        if cum >= room:
            return day
    return None


def run_out(net, start, resources, shift, k, buffer, jun30):
    """Walk the analog-year non-debt deficit forward from the binding day until resources < buffer."""
    r, path = resources, []
    added = False
    for i in range(0, 500):
        day = start + dt.timedelta(days=i)
        r += k * flow_on(net, day, shift)
        if not added and day >= D(day.year, 6, 30) and start < D(day.year, 6, 30):
            r += jun30
            added = True
        if i % 7 == 0:
            path.append([iso(day), round(r, 1)])
        if r < buffer:
            return day, path
    return None, path


def calibrate_em(days):
    """EM size implied by 2023: resources from binding (19 Jan 2023) running out on 2 Jun 2023."""
    tga, net = series(days, "tga"), series(days, "net")
    b, x = D(2023, 1, 19), D(2023, 6, 2)
    if b not in tga or x not in tga:
        return None
    drain = -sum(v for d, v in net.items() if b < d <= x)
    return round(drain - tga[b] + tga[x], 1)


def pct(vals, q):
    v = sorted(vals)
    if not v:
        return None
    i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[i]


# ------------------------------------------------------------------ prediction markets
WORDS = ("debt ceiling", "debt limit", "us defaults", "u.s. defaults", "us default", "u.s. default")


def EXCL(t):
    return any(w in t for w in ("france", "eu ", "european", "uk ", "japan", "china", "italy", "downgrade", "peak us national debt"))


def markets():
    out = []
    try:      # Kalshi: walk open events and keep debt-ceiling ones
        cur = ""
        for _ in range(30):
            j = json.loads(get("https://api.elections.kalshi.com/trade-api/v2/events?limit=200&status=open&with_nested_markets=true"
                               + (f"&cursor={cur}" if cur else "")))
            for ev in j.get("events", []):
                t = (ev.get("title") or "").lower()
                if (any(w in t for w in WORDS) and not EXCL(t)) or "DCEIL" in (ev.get("series_ticker") or ""):
                    for m in ev.get("markets", []):
                        px = m.get("last_price_dollars") or m.get("last_price")
                        px = num(px)
                        if px is not None and px > 1:
                            px = px / 100
                        out.append({"venue": "Kalshi", "event": ev.get("title"), "market": m.get("yes_sub_title") or m.get("title"),
                                    "prob": px, "vol": num(m.get("volume_fp") or m.get("volume")), "closes": (m.get("close_time") or "")[:10],
                                    "url": "https://kalshi.com/markets/" + (ev.get("series_ticker") or "").lower()})
            cur = j.get("cursor") or ""
            if not cur:
                break
    except Exception as e:
        out.append({"venue": "Kalshi", "error": str(e)[:120]})
    try:      # Polymarket: public search, open events only
        for q in ("debt ceiling", "debt limit", "default on debt"):
            j = json.loads(get("https://gamma-api.polymarket.com/public-search?q=" + urllib.parse.quote(q) + "&limit_per_type=25&events_status=active"))
            for ev in j.get("events", []):
                if ev.get("closed") or EXCL((ev.get("title") or "").lower()) or not any(w in (ev.get("title") or "").lower() for w in WORDS):
                    continue
                for m in ev.get("markets", []) or []:
                    if m.get("closed"):
                        continue
                    try:
                        pr = json.loads(m.get("outcomePrices") or "[]")
                        prob = float(pr[0]) if pr else None
                    except Exception:
                        prob = None
                    out.append({"venue": "Polymarket", "event": ev.get("title"), "market": m.get("groupItemTitle") or m.get("question"),
                                "prob": prob, "vol": num(m.get("volume")), "closes": (m.get("endDate") or "")[:10],
                                "url": "https://polymarket.com/event/" + (ev.get("slug") or "")})
    except Exception as e:
        out.append({"venue": "Polymarket", "error": str(e)[:120]})
    seen, uniq = set(), []
    for m in out:
        k = (m.get("venue"), m.get("event"), m.get("market"))
        if k not in seen:
            seen.add(k)
            uniq.append(m)
    return uniq


# ------------------------------------------------------------------ main
def main():
    os.makedirs("docs", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    if time.time() - cache.get("ran", 0) < 3 * 3600 and os.path.exists(OUT) and not os.environ.get("DL_FORCE"):
        print("debtlimit: paced, skipping")
        return
    notes = []
    try:
        refresh(cache)
    except Exception as e:
        notes.append(f"Treasury data refresh failed: {e}")
    days = cache.get("days", {})
    dsl, tga, net, lim = series(days, "dsl"), series(days, "tga"), series(days, "net"), series(days, "limit")
    if not dsl:
        print("debtlimit: no data", notes)
        return
    today = max(dsl)
    LAST[0] = max(net) if net else today
    limit, debt = lim[today], dsl[today]
    room = limit - debt
    tga_now = tga.get(today)
    # has it bound? debt within $25bn of the limit for 5+ business days
    recent = sorted(d for d in dsl if d > today - dt.timedelta(days=10))
    bound = len(recent) >= 5 and all(lim[d] - dsl[d] < 25 for d in recent[-5:])
    bind_day = None
    if bound:
        bind_day = min(d for d in dsl if d > today - dt.timedelta(days=400) and lim.get(d, 1e9) - dsl[d] < 25)

    em23 = calibrate_em(days)
    growth = debt / 31400.0            # federal debt subject to limit was ~$31.4tn in Jan 2023
    em_c = round((em23 or 330.0) * growth, 0)
    P = {"buffer": 30.0, "jun30": round(145.0 * growth, 0), "em": em_c, "em23": em23}

    analogs = [s for s in (3, 1) if same_day(today, s) >= D(2022, 7, 1)]    # 2023-24 and 2025-26 same calendar days
    binds, xs, paths = [], [], {}
    for s in analogs:
        k0 = deficit_scale(net, today, s)
        for kf in (0.9, 1.0, 1.1):
            k = k0 * kf
            b = bind_day if bound else project_binding(dsl, net, today, room, s, k)
            if b is None:
                continue
            binds.append(b)
            # TGA at binding: actual if bound; else Treasury's targets ($850bn end-Dec, $1.0tn end-Mar), interpolated
            if bound:
                res0, start = tga.get(bind_day, tga_now) + P["em"], bind_day
            else:
                tgt = [(D(today.year, 12, 31) if today.month < 12 else D(today.year + 1, 12, 31), 850.0), (D(b.year, 3, 31) if b.month <= 3 else D(b.year, 6, 30), 1000.0)]
                tb = tga_now
                for td, tv in tgt:
                    if b >= td:
                        tb = tv
                res0, start = tb + P["em"], b
            for ef in (0.85, 1.0, 1.15):
                r0 = res0 + P["em"] * (ef - 1)
                if bound:      # roll actual flows from the binding day to today, then project
                    r0 = r0 + sum(net.get(d, 0) for d in net if bind_day < d <= today)
                    start = today + dt.timedelta(days=1)
                x, path = run_out(net, start, r0, s, k, P["buffer"], P["jun30"])
                if x:
                    xs.append(x)
                if kf == 1.0 and ef == 1.0:
                    paths[str(today.year - s)] = path
    b10, b50, b90 = pct(binds, .1), pct(binds, .5), pct(binds, .9)
    x10, x50, x90 = pct(xs, .1), pct(xs, .5), pct(xs, .9)

    # backtest, out of sample: stand on 21 Jan 2025 (binding day) knowing only data up to then,
    # analog = calendar 2024, EM from 2023 scaled to 2025's debt. The limit was raised on 4 Jul 2025,
    # so compare with what CBO and Treasury projected at the time.
    bt = {}
    b = D(2025, 1, 21)
    if em23 and b in tga:
        keep = LAST[0]
        LAST[0] = D(2025, 1, 20)
        k = deficit_scale(net, b, 1)
        em25 = em23 * (dsl.get(b, 36100.0) / 31400.0)
        x, _ = run_out(net, b, tga[b] + em25, 1, k, P["buffer"], 145.0 * (dsl.get(b, 36100.0) / 31400.0))
        LAST[0] = keep
        bt["2025"] = {"bind": iso(b), "model_x": iso(x) if x else None, "em": round(em25), "scale": round(k, 2),
                      "then": "CBO (Mar 2025): Aug–Sep 2025; Treasury (Bessent, May 2025): mid-to-late August; limit raised 4 Jul 2025"}

    yr = (b50 or today).year
    key = [
        {"d": iso(b50) if b50 else None, "lo": iso(b10) if b10 else None, "hi": iso(b90) if b90 else None, "t": "Debt limit binds; extraordinary measures start", "k": "bind"},
        {"d": f"{yr}-04-15", "t": "Individual tax date: the biggest cash inflow of the year (pushes the X-date out)", "k": "tax"},
        {"d": f"{yr}-06-15", "t": "Quarterly corporate and estimated tax date", "k": "tax"},
        {"d": f"{yr}-06-30", "t": "One-time extraordinary measure (federal retirement fund interest), about $" + str(int(P["jun30"])) + "bn", "k": "em"},
        {"d": f"{yr}-08-01", "t": "Congress's August recess usually starts: a common deal deadline", "k": "congress"},
        {"d": f"{yr}-09-15", "t": "Quarterly tax date", "k": "tax"},
        {"d": f"{yr}-09-30", "t": "Fiscal year ends; appropriations deadline", "k": "congress"},
        {"d": iso(x50) if x50 else None, "lo": iso(x10) if x10 else None, "hi": iso(x90) if x90 else None, "t": "X-date: cash plus extraordinary measures run out", "k": "x"},
    ]
    sources = json.load(open(SRC)) if os.path.exists(SRC) else []
    mk = markets()
    hist = [[iso(d), round(limit - dsl[d], 1), round(tga.get(d, 0), 1)] for d in sorted(dsl) if d >= today - dt.timedelta(days=400)]
    out = {"built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "asof": iso(today),
           "limit": round(limit, 1), "debt": round(debt, 1), "room": round(room, 1), "tga": tga_now, "bound": bound,
           "bind_actual": iso(bind_day) if bind_day else None,
           "bind": {"p10": iso(b10) if b10 else None, "p50": iso(b50) if b50 else None, "p90": iso(b90) if b90 else None},
           "x": {"p10": iso(x10) if x10 else None, "p50": iso(x50) if x50 else None, "p90": iso(x90) if x90 else None},
           "params": P, "analog_years": [today.year - s for s in analogs], "paths": paths, "backtest": bt,
           "room_hist": hist, "key_dates": key, "sources": sources, "markets": mk, "notes": notes}
    open(OUT, "w").write("window.DEBTLIMIT = " + json.dumps(out, separators=(",", ":")) + ";\n")
    cache["ran"] = time.time()
    json.dump(cache, open(CACHE, "w"), separators=(",", ":"))
    print("debtlimit:", out["asof"], "room", out["room"], "bind", out["bind"], "x", out["x"], "EM", P, "markets", len(mk), notes)


if __name__ == "__main__":
    main()
