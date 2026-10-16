import json, subprocess, time, re
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url, extra=()):
    p = subprocess.run(["curl", "-sS", "-L", "-m", "40", "--compressed", "-A", UA, *extra, "-w", "\n@@%{http_code}", url], capture_output=True)
    body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n@@")
    return code, body
out = []
for u in ["https://nfs.faireconomy.media/ff_calendar_thisweek.json", "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
          "https://nfs.faireconomy.media/ff_calendar_lastweek.json", "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"]:
    code, b = get(u)
    out.append(f"== {code} {u} bytes={len(b)}")
    try:
        d = json.loads(b); out.append(f"   n={len(d)} keys={list(d[0].keys())}")
        for e in d[:200]:
            if e.get("country") in ("USD","EUR","GBP","CAD","CHF") and e.get("impact") in ("High","Medium"):
                out.append("   " + json.dumps(e)[:220])
    except Exception:
        out.append("   " + b[:600].replace("\n", " "))
    time.sleep(1)
for u, h in [("https://calendar-api.fxstreet.com/en/api/v1/eventDates/2026-10-12T00:00:00Z/2026-10-17T00:00:00Z?volatilities=HIGH&countries=US", ("-H","Origin: https://www.fxstreet.com","-H","Referer: https://www.fxstreet.com/")),
             ("https://www.marketwatch.com/economy-politics/calendar", ()),
             ("https://economic-calendar.tradingview.com/events?from=2026-10-12T00:00:00.000Z&to=2026-10-17T00:00:00.000Z&countries=US,EU,GB,CA,CH", ("-H","Origin: https://www.tradingview.com","-H","Referer: https://www.tradingview.com/"))]:
    code, b = get(u, h)
    out.append(f"== {code} {u[:90]} bytes={len(b)}  {b[:1500]}")
import os; os.makedirs("probe", exist_ok=True)
open("probe/CAL.txt","w").write("\n".join(out)+"\n")
