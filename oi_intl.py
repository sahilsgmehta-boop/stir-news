"""Non-US open interest for the dashboard -> docs/oi_intl.js

Sources (all free and public, no login, no CAPTCHA):
  Eurex     - the statistics behind each product page,
              /api/v1/overallstatistics/<id>?busdate=YYYYMMDD&filtertype=overview
              Returns every contract month with volume, open interest and
              daily settlement, plus the last ~21 trading dates, so a month of
              history is filled in on the first run.
  Montreal  - Montreal Exchange (TMX). The historical-data CSV for CORRA
              futures, falling back to the live quotes page, which shows
              open interest for every contract month.

ICE Futures Europe (Euribor, SONIA, SARON, Gilt) is NOT here: every one of
ICE's open interest reports sits behind a CAPTCHA, which is ICE saying it
does not want automated downloads.

Same shape as oi.js (window.STELLAR_OI) so the page can treat both alike:
  cols = date, pid, product, month, settle, volume, oi, status
Never fails the workflow; problems are recorded under "health".
"""
import csv, io, json, os, re, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "oi_intl.json")
OUT = os.path.join(HERE, "docs", "oi_intl.js")

# pid is the exchange's product code; name is what the page shows
EUREX = [
    {"pid": "FGBS", "id": "34678",   "name": "Schatz"},
    {"pid": "FGBM", "id": "34670",   "name": "Bobl"},
    {"pid": "FGBL", "id": "34656",   "name": "Bund"},
    {"pid": "FGBX", "id": "42066",   "name": "Buxl"},
    {"pid": "FOAT", "id": "34684",   "name": "OAT"},
    {"pid": "FBTP", "id": "34680",   "name": "BTP"},
    {"pid": "FST3", "id": "3402482", "name": "3M €STR"},
]
MX = [{"pid": "CRA", "name": "3M CORRA"}]
ORDER = [p["pid"] for p in EUREX] + [p["pid"] for p in MX]

LOOKBACK_DAYS = 32      # rolling month, like the US page
RECENT_DAYS = 3         # days younger than this are asked again (late revisions)
MAX_MONTHS = 24
MAX_REQUESTS = 200
PAUSE = 0.3

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
CODE = {c: i for i, c in enumerate("FGHJKMNQUVXZ")}
health = {"errors": [], "requests": 0}


def get(url, accept="application/json, text/html;q=0.9, */*;q=0.8", referer=None):
    health["requests"] += 1
    cmd = ["curl", "-sS", "-L", "-m", "40", "--compressed", "-A", UA,
           "-H", "Accept: " + accept, "-H", "Accept-Language: en-GB,en;q=0.9",
           "-w", "\n@@%{http_code}", url]
    if referer:
        cmd[1:1] = ["-H", "Referer: " + referer]
    p = subprocess.run(cmd, capture_output=True)
    out = p.stdout.decode("utf-8", "replace")
    body, _, code = out.rpartition("\n@@")
    time.sleep(PAUSE)
    if code != "200":
        raise IOError(f"HTTP {code or 'error'} {p.stderr.decode()[:120]}".strip())
    return body


def label(y, m):
    return f"{MON[m-1]} {y % 100:02d}"


def num(v):
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f


# ------------------------------------------------------------------ Eurex
def eurex_day(p, ymd):
    url = (f"https://www.eurex.com/api/v1/overallstatistics/{p['id']}"
           f"?busdate={ymd}&filtertype=overview")
    d = json.loads(get(url, referer="https://www.eurex.com/ex-en/markets"))
    rows = []
    for r in d.get("dataRows") or []:
        if r.get("contractType") not in (None, "M"):
            continue
        ds = str(r.get("date", ""))
        if len(ds) != 8:
            continue
        oi, vol = num(r.get("openInt")), num(r.get("volume"))
        if not oi and not vol:
            continue
        st = num(r.get("dSettle"))
        rows.append([label(int(ds[:4]), int(ds[4:6])), st or None,
                     int(vol or 0), int(oi or 0), ds])
    rows.sort(key=lambda r: r[4])
    dates = []
    for t in (d.get("header") or {}).get("tradingDates") or []:
        m = re.match(r"(\d\d)-(\d\d)-(\d{4})", t)
        if m:
            dates.append(f"{m.group(3)}-{m.group(2)}-{m.group(1)}")
    return [r[:4] for r in rows[:MAX_MONTHS]], dates


def run_eurex(store, today):
    cutoff = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    recent = (today - timedelta(days=RECENT_DAYS)).isoformat()
    for p in EUREX:
        try:
            # the latest session first; its answer also lists the dates on file
            probe_day = today
            latest_rows, dates = eurex_day(p, probe_day.strftime("%Y%m%d"))
            if latest_rows:
                store.setdefault(probe_day.isoformat(), {})[p["pid"]] = latest_rows
            for ds in dates:
                if ds < cutoff or health["requests"] >= MAX_REQUESTS:
                    continue
                have = store.get(ds, {}).get(p["pid"])
                if have and ds < recent:
                    continue
                rows, _ = eurex_day(p, ds.replace("-", ""))
                if rows:
                    store.setdefault(ds, {})[p["pid"]] = rows
        except Exception as e:  # noqa: BLE001
            health["errors"].append(f"Eurex {p['name']}: {e}"[:200])


# ------------------------------------------------------------------ Montreal
def mx_csv(p, today):
    frm = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    url = ("https://www.m-x.ca/en/trading/data/historical?symbol={s}&f={s}"
           "&from={a}&to={b}&dnld=").format(s=p["pid"], a=frm, b=today.isoformat())
    text = get(url, accept="text/csv,*/*;q=0.8",
               referer="https://www.m-x.ca/en/trading/data/historical")
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        sym = (r.get("Symbol") or "").strip()
        m = re.match(re.escape(p["pid"]) + r"([FGHJKMNQUVXZ])(\d\d)$", sym)
        day = (r.get("Date") or "").strip()[:10]
        if not m or not re.match(r"\d{4}-\d\d-\d\d$", day):
            continue
        oi, vol = num(r.get("Open Interest")), num(r.get("Volume"))
        if not oi and not vol:
            continue
        y, mo = 2000 + int(m.group(2)), CODE[m.group(1)] + 1
        out.setdefault(day, []).append(
            [label(y, mo), num(r.get("Settlement Price")), int(vol or 0), int(oi or 0), y * 100 + mo])
    for day in out:
        out[day] = [r[:4] for r in sorted(out[day], key=lambda r: r[4])][:MAX_MONTHS]
    return out


def mx_quotes(p, today):
    """The live quotes page: open interest per month as of the last close."""
    html = get(f"https://www.m-x.ca/en/trading/data/quotes?symbol={p['pid']}*",
               accept="text/html")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    t = re.sub(r"<[^>]+>", "|", t)
    t = re.sub(r"(&nbsp;|\s)+", " ", t)
    t = re.sub(r"(\| ?)+", "|", t)
    upd = re.search(r"Last update: ?\|([A-Za-z]+ \d{1,2}, \d{4})", t)
    if not upd:
        raise IOError("quotes page: no 'Last update' date")
    asof = datetime.strptime(upd.group(1), "%B %d, %Y").date()
    # OI on the page is from the previous close
    day = asof - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    months = {m: i + 1 for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"])}
    rows = []
    pat = (r"\|(" + "|".join(months) + r") (\d{4})\|([\d.]+|-)?\|?([\d.]+|-)?\|"
           r"([\d.]+)\|(-?[\d.]+)\|([\d,]+)\|([\d,]+)(?=\|)")
    for m in re.finditer(pat, t):
        y, mo = int(m.group(2)), months[m.group(1)]
        rows.append([label(y, mo), num(m.group(5)), int(m.group(8).replace(",", "")),
                     int(m.group(7).replace(",", "")), y * 100 + mo])
    rows = [r[:4] for r in sorted(rows, key=lambda r: r[4])][:MAX_MONTHS]
    return day.isoformat(), rows


# Montreal's history file records each session's open interest on the NEXT
# session's row (the row for 15 Oct carries the open interest after 14 Oct),
# while the quotes page shows the open interest after the last close. So a
# day's open interest is taken from the following row, and the latest day's
# from the quotes page; volume and settle stay on their own row.
MX_OI_NEXT_ROW = True


def run_mx(store, today):
    for p in MX:
        hist, qday, qrows = {}, None, []
        try:
            hist = mx_csv(p, today)
        except Exception as e:  # noqa: BLE001
            health["errors"].append(f"Montreal {p['name']} history: {e}"[:200])
        try:
            qday, qrows = mx_quotes(p, today)
        except Exception as e:  # noqa: BLE001
            health["errors"].append(f"Montreal {p['name']} quotes: {e}"[:200])

        got = {}
        if hist and MX_OI_NEXT_ROW:
            days = sorted(hist)
            for i, d in enumerate(days):
                if i + 1 < len(days):
                    nxt = {r[0]: r[3] for r in hist[days[i + 1]]}
                elif qday == d and qrows:
                    nxt = {r[0]: r[3] for r in qrows}
                else:
                    continue            # its open interest is not out yet
                rows = [[r[0], r[1], r[2], nxt[r[0]]] for r in hist[d] if nxt.get(r[0])]
                if rows:
                    got[d] = rows
            health["mx_mode"] = "history csv, open interest from the next row"
        elif hist:
            got = hist
            health["mx_mode"] = "history csv"
        if qday and qrows and qday not in got:
            # the history file is a day behind; the page's volume is the
            # session in progress, so it is left out
            got[qday] = [[r[0], r[1], None, r[3]] for r in qrows]
            health["mx_mode"] = health.get("mx_mode", "") + " + quotes page"
        if got:                         # rebuilt in full every run
            for day in store:
                store[day].pop(p["pid"], None)
        for day, rows in got.items():
            store.setdefault(day, {})[p["pid"]] = rows


# ------------------------------------------------------------------ main
def main():
    now = datetime.now(timezone.utc)
    today = now.date()
    try:
        old = json.load(open(STORE))
    except Exception:  # noqa: BLE001
        old = {}
    store = old.get("days", {})

    run_eurex(store, today)
    run_mx(store, today)

    cutoff = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    store = {d: v for d, v in store.items() if d >= cutoff and v}
    names = {p["pid"]: p["name"] for p in EUREX + MX}
    rows = []
    for d in sorted(store):
        for pid in ORDER:
            for r in store[d].get(pid, []):
                rows.append([d, pid, names[pid], r[0], r[1], r[2], r[3], "F"])

    latest = {}
    for d in store:
        for pid in store[d]:
            latest[pid] = max(latest.get(pid, ""), d)
    health["latest"] = latest
    built = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    json.dump({"built": built, "days": store, "health": health}, open(STORE, "w"),
              separators=(",", ":"))
    payload = {"built": built, "source": "Eurex and Montreal Exchange statistics",
               "cols": ["date", "pid", "product", "month", "settle", "volume", "oi", "status"],
               "rows": rows, "health": health}
    with open(OUT, "w") as f:
        f.write("window.STELLAR_OI_INTL = " + json.dumps(payload, separators=(",", ":"),
                                                       ensure_ascii=False) + ";\n")
    print(f"oi_intl: {len(rows)} rows, {health['requests']} requests, "
          f"errors: {health['errors'] or 'none'}, latest: {latest}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("oi_intl failed:", e, file=sys.stderr)
    sys.exit(0)
