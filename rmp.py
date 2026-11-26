"""RMP watch for the STIR dashboard -> docs/rmp.js (window.RMP).

Public data only, from the New York Fed:
  - the Treasury securities operational details page: the Desk's planned amount for each monthly
    period (reinvestment purchases of bills, plus reserve management purchases, RMPs);
  - markets.newyorkfed.org API: results of every Treasury purchase operation (amount bought).

Output:
  periods  newest first: {start, end, reinv, rmp, text}  ($bn over the monthly period, about 4 weeks)
  current  the period covering today (or the newest one)
  change   set when the newest period's RMP differs from the period before it (restart, stop, resize)
  actual   bills bought per calendar month, $bn, from the operation results
  ops      the last 15 purchase operations: [date, settle, $bn, maturity range]
Paces itself: runs at most every 3 hours (the schedule is released once a month, around the 9th
business day; operations run a few times a week).
"""
import json, os, re, time, signal, urllib.request, datetime as dt

OUT, CACHE = "docs/rmp.js", "data/rmp_cache.json"
PAGE = ("https://www.newyorkfed.org/markets/domestic-market-operations/monetary-policy-implementation/"
        "treasury-securities/treasury-securities-operational-details")
API = "https://markets.newyorkfed.org/api/tsy/all/results/summary/search.json?startDate={a}&endDate={b}"
UA = {"User-Agent": "Mozilla/5.0 (stir-news RMP watch)"}


def _alarm(*a):
    raise TimeoutError("hard timeout")


signal.signal(signal.SIGALRM, _alarm)


def get(u, tries=3):
    err = None
    for _ in range(tries):
        signal.alarm(70)
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=50) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(3)
        finally:
            signal.alarm(0)
    raise err


def mdy(s):
    m, d, y = s.split("/")
    y = int(y)
    return dt.date(y + 2000 if y < 100 else y, int(m), int(d))


BN = r"\$\s*([\d.,]+)\s*(billion|million)"


def amount(t, what):
    """$bn of `what` ('reinvestment' or 'reserve management') in one period's sentence."""
    if re.search(r"no\s+" + what, t, re.I):
        return 0.0
    m = re.search(BN + r"[^$.]*?\b" + what, t, re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v / 1000 if m.group(2).lower() == "million" else v


def parse(html):
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"\s+", " ", t)
    rx = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})\s+(The Desk .*?period(?: from [\d/]+ to [\d/]+)?\.)")
    out, seen = [], set()
    for m in rx.finditer(t):
        a, b, txt = mdy(m.group(1)), mdy(m.group(2)), m.group(3)
        if a in seen:
            continue
        seen.add(a)
        none = re.search(r"will not conduct any", txt, re.I)
        small = re.search(r"small value", txt, re.I)
        reinv = 0.0 if (none or small) else amount(txt, "reinvestment")
        rmp = 0.0 if (none or small) else amount(txt, "reserve management")
        out.append({"start": a.isoformat(), "end": b.isoformat(), "reinv": reinv, "rmp": rmp,
                    "small": bool(small), "text": txt})
    out.sort(key=lambda p: p["start"], reverse=True)
    return out


def summarise(periods, today):
    cur = next((p for p in periods if p["start"] <= today.isoformat() <= p["end"]), periods[0] if periods else None)
    change = None
    if len(periods) >= 2:
        n, p = periods[0], periods[1]
        if n["rmp"] is not None and p["rmp"] is not None and abs(n["rmp"] - p["rmp"]) > 0.05:
            kind = "restart" if p["rmp"] == 0 else "stop" if n["rmp"] == 0 else "size change"
            change = {"kind": kind, "start": n["start"], "end": n["end"], "from": p["rmp"], "to": n["rmp"]}
    return cur, change


def main():
    os.makedirs("docs", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    if time.time() - cache.get("ran", 0) < 3 * 3600 and os.path.exists(OUT) and not os.environ.get("RMP_FORCE"):
        print("rmp: paced, skipping")
        return
    today, notes = dt.date.today(), []
    try:
        periods = parse(get(PAGE))
        if periods:
            cache["periods"] = periods
        else:
            notes.append("schedule page parsed no periods")
    except Exception as e:  # noqa: BLE001
        notes.append(f"schedule page: {e}")
    periods = cache.get("periods", [])
    actual, ops = cache.get("actual", {}), cache.get("ops", [])
    try:
        j = json.loads(get(API.format(a=(today - dt.timedelta(400)).isoformat(), b=(today + dt.timedelta(30)).isoformat())))
        a, o = {}, []
        for x in j.get("treasury", {}).get("auctions", []):
            if x.get("operationDirection") != "P" or "Bill" not in (x.get("operationType") or ""):
                continue
            amt = float(x.get("totalParAmtAccepted") or 0) / 1e9
            a[x["operationDate"][:7]] = round(a.get(x["operationDate"][:7], 0) + amt, 3)
            o.append([x["operationDate"], x.get("settlementDate"), round(amt, 3),
                      f'{x.get("maturityRangeStart", "")} to {x.get("maturityRangeEnd", "")}'])
        if a:
            actual = a
            ops = sorted(o, reverse=True)[:15]
    except Exception as e:  # noqa: BLE001
        notes.append(f"operation results: {e}")
    cur, change = summarise(periods, today)
    out = {"built": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "source": PAGE, "periods": periods[:30],
           "current": cur, "change": change, "actual": dict(sorted(actual.items())), "ops": ops, "notes": notes}
    with open(OUT, "w") as f:
        f.write("window.RMP = " + json.dumps(out, separators=(",", ":")) + ";\n")
    cache.update(ran=time.time(), actual=actual, ops=ops)
    json.dump(cache, open(CACHE, "w"))
    print(f"rmp: {len(periods)} periods, current {cur and cur['start']} rmp {cur and cur['rmp']}, change {change}, notes {notes}")


if __name__ == "__main__":
    main()
