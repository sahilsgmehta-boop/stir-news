"""CFTC Traders in Financial Futures (futures only) for the dashboard's
Positioning page: SOFR, fed funds and Treasury futures, about three years of
weekly reports from the CFTC's free public API (publicreporting.cftc.gov).
Refreshed at most every 6 hours (the report comes out on Friday afternoons
ET, for the Tuesday before). Never fails the run.
"""
import json, os, subprocess, sys, time, urllib.parse
from datetime import datetime, timedelta, timezone

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "cftc.js")
URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
# name match -> short key, label, contract DV01 in $ per bp (approx, for risk-weighting)
MARKETS = [
    ("SOFR-3M", "SR3", "SOFR 3M", 25), ("SOFR-1M", "SR1", "SOFR 1M", 41.67),
    ("FED FUNDS", "FF", "Fed funds", 41.67),
    ("UST 2Y NOTE", "TU", "2Y note", 38), ("UST 5Y NOTE", "FV", "5Y note", 45),
    ("UST 10Y NOTE", "TY", "10Y note", 65), ("ULTRA UST 10Y", "TN", "Ultra 10Y", 95),
    ("UST BOND", "US", "Bond", 130), ("ULTRA UST BOND", "UB", "Ultra bond", 230),
]
F = ["open_interest_all", "dealer_positions_long_all", "dealer_positions_short_all",
     "asset_mgr_positions_long", "asset_mgr_positions_short",
     "lev_money_positions_long", "lev_money_positions_short",
     "other_rept_positions_long", "other_rept_positions_short",
     "nonrept_positions_long_all", "nonrept_positions_short_all"]


def get(url):
    p = subprocess.run(["curl", "-sS", "-L", "-m", "60", "--compressed", url], capture_output=True)
    if p.returncode:
        raise IOError(p.stderr.decode()[:200])
    return json.loads(p.stdout.decode("utf-8", "replace"))


def main():
    if os.path.exists(OUT) and time.time() - os.path.getmtime(OUT) < 6 * 3600 and "--force" not in sys.argv:
        print("cftc: fresh, skipped"); return
    since = (datetime.now(timezone.utc) - timedelta(days=3 * 366)).strftime("%Y-%m-%dT00:00:00")
    names = " OR ".join("upper(market_and_exchange_names) like '%" + m[0] + "%'" for m in MARKETS)
    q = {"$where": f"report_date_as_yyyy_mm_dd >= '{since}' AND ({names})",
         "$select": "market_and_exchange_names,report_date_as_yyyy_mm_dd," + ",".join(F),
         "$order": "report_date_as_yyyy_mm_dd", "$limit": "50000"}
    rows = get(URL + "?" + urllib.parse.urlencode(q))
    if not isinstance(rows, list) or not rows:
        print("cftc: nothing returned; keeping the old file", str(rows)[:200]); return
    out, seen = {}, set()
    for r in rows:
        nm = (r.get("market_and_exchange_names") or "").upper()
        # the most specific name wins (ULTRA UST BOND before UST BOND)
        hit = None
        for m in sorted(MARKETS, key=lambda m: -len(m[0])):
            if m[0] in nm:
                hit = m; break
        if not hit or ("ULTRA" in nm and "ULTRA" not in hit[0]):
            continue
        d = r["report_date_as_yyyy_mm_dd"][:10]
        if (hit[1], d) in seen:
            continue
        seen.add((hit[1], d))
        v = [int(float(r.get(k) or 0)) for k in F]
        out.setdefault(hit[1], {"label": hit[2], "dv01": hit[3], "name": nm.title(), "rows": []})["rows"].append([d] + v)
    payload = {"built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "fields": ["date", "oi", "dealer_l", "dealer_s", "am_l", "am_s", "lev_l", "lev_s", "oth_l", "oth_s", "nr_l", "nr_s"],
               "markets": out}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("window.CFTC = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    print("cftc:", {k: len(v["rows"]) for k, v in out.items()})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
    sys.exit(0)
