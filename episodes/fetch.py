# probe v4: DTS table shapes + prediction-market endpoints for the debt-limit tracker
import urllib.request, urllib.parse, json, os, signal
H = {"User-Agent": "Mozilla/5.0 (stir-news probe)", "Accept": "application/json"}
def _a(*x): raise TimeoutError("hard timeout")
signal.signal(signal.SIGALRM, _a)
def get(u):
    signal.alarm(60)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=40) as r: return r.read().decode("utf-8", "replace")
    finally: signal.alarm(0)
os.makedirs("episodes/probe", exist_ok=True)
FD = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/"
P = {
 "dw": FD + "deposits_withdrawals_operating_cash?filter=record_date:eq:2026-11-16&page[size]=500",
 "pdt": FD + "public_debt_transactions?filter=record_date:eq:2026-11-16&page[size]=500",
 "dsl": FD + "debt_subject_to_limit?filter=record_date:eq:2026-11-16&page[size]=50",
 "ocb": FD + "operating_cash_balance?filter=record_date:eq:2026-11-16&page[size]=50",
 "kalshi_series": "https://api.elections.kalshi.com/trade-api/v2/series?limit=1000",
 "kalshi_events": "https://api.elections.kalshi.com/trade-api/v2/events?limit=200&status=open&with_nested_markets=true",
 "poly_search": "https://gamma-api.polymarket.com/public-search?q=debt%20ceiling&limit_per_type=20",
 "poly_markets": "https://gamma-api.polymarket.com/markets?limit=50&closed=false&tag_slug=economy",
}
for k, u in P.items():
    try: t = get(u); open(f"episodes/probe/{k}.json", "w").write(t[:3000000]); print(k, len(t))
    except Exception as e: print(k, "FAIL", e); open(f"episodes/probe/{k}.json", "w").write("FAIL " + str(e))
# Kalshi: page through events looking for debt-ceiling titles
hits, cur = [], ""
for i in range(25):
    try:
        j = json.loads(get("https://api.elections.kalshi.com/trade-api/v2/events?limit=200&status=open&with_nested_markets=true" + (f"&cursor={cur}" if cur else "")))
    except Exception as e: print("kalshi page", i, e); break
    for ev in j.get("events", []):
        if any(w in (ev.get("title","") + ev.get("series_ticker","")).lower() for w in ("debt ceiling", "debt limit", "dceil", "debtlim")):
            hits.append(ev)
    cur = j.get("cursor") or ""
    if not cur: break
open("episodes/probe/kalshi_debt.json", "w").write(json.dumps(hits)[:2000000]); print("kalshi debt events", len(hits))
