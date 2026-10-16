"""Temporary: alternatives for the missing Markets-page sources -> probe/REPORT2.txt"""
import json, subprocess, time, os
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url, extra=()):
    p = subprocess.run(["curl", "-sS", "-L", "-m", "30", "--compressed", "-A", UA, *extra, "-w", "\n@@%{http_code}", url], capture_output=True)
    body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n@@")
    return code, body
out = []
def yahoo(sym):
    code, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5y&interval=1d")
    try:
        r = json.loads(b)["chart"]["result"][0]; ts = r.get("timestamp") or []
        out.append(f"{code} Y {sym:20s} n={len(ts)} first={time.strftime('%Y-%m-%d', time.gmtime(ts[0])) if ts else ''} price={r['meta'].get('regularMarketPrice')}")
    except Exception as e:
        out.append(f"{code} Y {sym:20s} ERR {b[:100]}")
    time.sleep(0.4)
for s in ["BCI", "CMDY", "^BCOMTR", "^BCOMSP", "^SPGSCITR", "^V2TX", "V2TX.DE", "^VSTOXX", "510300.SS", "ASHR", "^CSI300",
          "^NSEMDCP50", "^CRSMID", "NIFTYMIDCAP150.NS", "MID150BEES.NS", "^NIFTYMIDCAP100", "USDCNH=X", "CNY=X", "CNH=F"]:
    yahoo(s)
syms = ["US10Y", "US2Y", "DE10Y-DE", "DE2Y-DE", "GB10Y-GB", "GB2Y-GB", "JP10Y-JP", "JP2Y-JP", "FR10Y-FR", "FR2Y-FR",
        "IT10Y-IT", "IT2Y-IT", "ES10Y-ES", "CA10Y", "CA2Y", "AU10Y-AU"]
for s in syms:
    code, b = get(f"https://ts-api.cnbc.com/harmony/app/charts/5Y.json?symbol={s}")
    try:
        d = json.loads(b); bars = d.get("barData", {}).get("priceBars", [])
        out.append(f"{code} CNBC5Y {s:10s} n={len(bars)} first={bars[0] if bars else ''} last={bars[-1] if bars else ''}")
    except Exception:
        out.append(f"{code} CNBC5Y {s:10s} {b[:160]}")
    time.sleep(0.4)
code, b = get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=" + "|".join(syms) + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
out.append(f"{code} CNBC quote {b[:900]}")
for name, url in [
  ("STOXX v2tx", "https://www.stoxx.com/document/Indices/Current/HistoricalData/h_v2tx.txt"),
  ("Bundesbank 10y", "https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?format=csv&lang=en&startPeriod=2026-09-01"),
  ("BoC 10y", "https://www.bankofcanada.ca/valet/observations/BD.CDN.10YR.DQ.YLD/json?start_date=2026-10-01"),
  ("MoF JGB", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"),
  ("MoF JGB all", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"),
]:
    code, b = get(url)
    lines = b.strip().splitlines()
    out.append(f"{code} {name}: rows={len(lines)} head={' | '.join(lines[:2])[:200]} tail={lines[-1][:120] if lines else ''}")
open("probe/REPORT2.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out))
