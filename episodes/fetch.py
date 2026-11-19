# One-off (v3): weekly Fed balance-sheet items (H.4.1 via DBnomics) and monthly money-fund holdings (OFR).
import urllib.request, urllib.parse, json, os, signal
H = {"User-Agent": "Mozilla/5.0 (stir-news episodes)"}
def _a(*x): raise TimeoutError("hard timeout")
signal.signal(signal.SIGALRM, _a)
def get(u):
    signal.alarm(60)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=40) as r: return r.read().decode("utf-8", "replace")
    finally: signal.alarm(0)
LOG = [l for l in open("episodes/LOG.txt").read().splitlines()] if os.path.exists("episodes/LOG.txt") else []
def log(s): LOG.append(s); print(s, flush=True); open("episodes/LOG.txt", "w").write("\n".join(LOG) + "\n")
log("--- v3")
WANT = {"reserves": ["Reserve balances with Federal Reserve Banks"],
        "rrp_others": ["Reverse repurchase agreements", "Others"],
        "rrp_total": ["Reverse repurchase agreements", "Total"],
        "tga_h41": ["Treasury, General Account"],
        "fed_total_assets": ["Total assets"],
        "fed_treasuries": ["U.S. Treasury securities", "Bills"]}
for key, words in WANT.items():
    try:
        q = urllib.parse.quote(" ".join(words) + " Wednesday level")
        docs = json.loads(get(f"https://api.db.nomics.world/v22/series/FED/H41?limit=100&q={q}"))["series"]["docs"]
        c = [d for d in docs if all(w.lower() in d["series_name"].lower() for w in words) and "Wednesday level" in d["series_name"]
             and "Discontinued" not in d["series_name"] and "Change" not in d["series_name"]]
        c.sort(key=lambda d: len(d["series_name"]))
        if not c: log(f"{key}: no match"); continue
        s = c[0]
        d = json.loads(get(f"https://api.db.nomics.world/v22/series/FED/H41/{s['series_code']}?observations=1"))["series"]["docs"][0]
        rows = [f"{p},{v}" for p, v in zip(d["period"], d["value"]) if p >= "2017-06-01"]
        open(f"episodes/h41_{key}.csv", "w").write(f"# {s['series_code']} | {s['series_name']}\ndate,value\n" + "\n".join(rows) + "\n")
        log(f"{key}: {len(rows)} rows ({s['series_code']}: {s['series_name'][:90]})")
    except Exception as e: log(f"{key}: FAIL {e}")
for m in ["MMF-MMF_TOT-M", "MMF-MMF_RP_TOT-M", "MMF-MMF_T_TOT-M", "MMF-MMF_RP_OO-M"]:
    try:
        t = get(f"https://data.financialresearch.gov/v1/series/timeseries?mnemonic={m}&start_date=2017-01-01")
        open(f"episodes/ofr_{m}.json", "w").write(t); log(f"{m}: {len(t)} bytes")
    except Exception as e: log(f"{m}: FAIL {e}")
log("done v3")
