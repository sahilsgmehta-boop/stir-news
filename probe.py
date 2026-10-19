import subprocess, json
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url, h=()):
    cmd=["curl","-sS","-L","--compressed","-m","60","-A",UA,"-w","\n@@%{http_code}"]
    for x in h: cmd += ["-H", x]
    p = subprocess.run(cmd+[url],capture_output=True); b,_,c=p.stdout.decode("utf-8","replace").rpartition("\n@@"); return c,b
for sym in ["tmbmkde-10y","tmbmkfr-10y","tmbmkit-02y"]:
    c,b = get(f"https://www.marketwatch.com/investing/bond/{sym}/downloaddatapartial?startdate=09/01/2026%2000:00:00&enddate=10/19/2026%2000:00:00&daterange=d30&frequency=p1d&csvdownload=true&downloadpartial=false&newdates=false&countrycode=bx")
    print("MW", sym, c, b[:300].replace("\n"," | "))
for k in ["FM.D.FR.EUR.FR2.BB.FR10YT_RR.YLD","FM.D.FR.EUR.FR2.BB.FR2YT_RR.YLD","FM.D.FR.EUR.FR2.BB.FR5YT_RR.YLD","FM.D.FR.EUR.FR2.BB.FR30YT_RR.YLD"]:
    c,b = get(f'https://webstat.banque-france.fr/api/explore/v2.1/catalog/datasets/observations/exports/csv?where=series_key%3D%22{k}%22&order_by=time_period_end%20desc&limit=5&delimiter=%3B')
    print("BdF", k, c, b[:400].replace("\n"," | "))
c,b = get("https://webstat.banque-france.fr/api/explore/v2.1/catalog/datasets/series/records?where=search(title_en,%22OAT%22)%20and%20search(title_en,%22year%22)&limit=30&select=series_key,title_en")
print("BdF search", c, b[:3000])
for rng in ["1M","5D"]:
    c,b = get(f"https://ts-api.cnbc.com/harmony/app/charts/{rng}.json?symbol=DE10Y-DE")
    try:
        bars=json.loads(b)["barData"]["priceBars"]; print("CNBC",rng,len(bars),[(x["tradeTime"],x["close"]) for x in bars[-12:]])
    except Exception as e: print("CNBC",rng,c,b[:200])
