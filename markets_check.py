"""Temporary: does every asset on the Markets page have free data? -> probe/REPORT.txt"""
import json, subprocess, time, os
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url):
    p = subprocess.run(["curl", "-sS", "-L", "-m", "30", "--compressed", "-A", UA, "-w", "\n@@%{http_code}", url], capture_output=True)
    body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n@@")
    return code, body
cfg = json.load(open("markets_assets.json"))
syms = []
for g in cfg["groups"]:
    for s in g["subs"]:
        if s.get("proxy"): syms.append((s["name"] + " proxy", s["proxy"]))
        for name, sym in s["items"]: syms.append((name, sym))
os.makedirs("probe", exist_ok=True)
out = []
for name, sym in dict.fromkeys(syms):
    if sym.startswith("ust:"):
        continue
    if sym.startswith("stooq:"):
        code, b = get(f"https://stooq.com/q/d/l/?s={sym[6:]}&i=d")
        lines = [l for l in b.strip().splitlines() if l]
        out.append(f"{code} {sym:22s} {name:28s} rows={len(lines)} last={lines[-1][:60] if lines else ''} first={lines[1][:30] if len(lines)>1 else ''}")
    else:
        code, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5y&interval=1d")
        info = ""
        try:
            r = json.loads(b)["chart"]["result"][0]
            ts = r.get("timestamp") or []
            cl = r["indicators"]["quote"][0].get("close") or []
            m = r["meta"]
            info = (f"n={len(ts)} first={time.strftime('%Y-%m-%d', time.gmtime(ts[0])) if ts else ''} "
                    f"price={m.get('regularMarketPrice')} prev={m.get('chartPreviousClose')} ccy={m.get('currency')} "
                    f"t={time.strftime('%Y-%m-%d %H:%M', time.gmtime(m.get('regularMarketTime', 0)))}")
        except Exception as e:
            info = "ERR " + str(e)[:60] + " " + b[:120].replace("\n", " ")
        out.append(f"{code} {sym:22s} {name:28s} {info}")
    time.sleep(0.4)
code, b = get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv")
out.append(f"{code} UST CSV: " + " | ".join(b.splitlines()[:3])[:400])
open("probe/REPORT.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out))
