import json, subprocess, time
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url):
    p = subprocess.run(["curl", "-sS", "-L", "-m", "30", "--compressed", "-A", UA, "-w", "\n@@%{http_code}", url], capture_output=True)
    body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n@@")
    return code, body
out = []
for s in ["US1M", "US3M", "US6M", "US1Y", "US5Y", "US30Y", "DE10Y-DE", "GB10Y-GB", "UK10Y-GB", "GB10YT=RR", ".V2TX", ".VSTOXX", "V2TX"]:
    for rng in ["1Y", "3Y"]:
        code, b = get(f"https://ts-api.cnbc.com/harmony/app/charts/{rng}.json?symbol={s}")
        try:
            bars = json.loads(b).get("barData", {}).get("priceBars", [])
            gaps = [ (bars[i+1]['tradeTimeinMills']-bars[i]['tradeTimeinMills'])/86400000 for i in range(min(5,len(bars)-1))]
            out.append(f"{code} {rng} {s:12s} n={len(bars)} first={bars[0]['tradeTime'] if bars else ''} last={bars[-1]['tradeTime'] + ' ' + bars[-1]['close'] if bars else ''} gaps={gaps}")
        except Exception:
            out.append(f"{code} {rng} {s:12s} {b[:120]}")
        time.sleep(0.3)
code, b = get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=GB10Y-GB|UK10Y-GB|.V2TX|US1M&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
try:
    for q in json.loads(b)["FormattedQuoteResult"]["FormattedQuote"]:
        out.append(f"quote {q.get('symbol')} code={q.get('code')} last={q.get('last')} prev={q.get('previous_day_closing')} t={q.get('last_time')}")
except Exception:
    out.append("quote " + b[:300])
open("probe/REPORT3.txt", "w").write("\n".join(out) + "\n")
