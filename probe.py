import subprocess, re, json, sys
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url, ref=None, accept="*/*"):
    cmd = ["curl", "-sS", "-L", "--compressed", "-m", "40", "-A", UA, "-H", "Accept: " + accept,
           "-H", "Accept-Language: en-US,en;q=0.9", "-w", "\n@@%{http_code}"]
    if ref: cmd += ["-H", "Referer: " + ref]
    p = subprocess.run(cmd + [url], capture_output=True)
    b, _, c = p.stdout.decode("utf-8", "replace").rpartition("\n@@")
    return c, b
def show(name, url, n=700, **kw):
    try:
        c, b = get(url, **kw)
        print(f"\n=== {name} HTTP {c} len={len(b)}\n{b[:n]}")
        return b
    except Exception as e:
        print(f"\n=== {name} ERR {e}")
        return ""
# --- official curves
show("BoC valet", "https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json?recent=3")
show("MOF JGB current", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv", 600)
b = show("MOF JGB all", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv", 300)
print("MOF all tail:", b[-300:])
for t in ["R02XX", "R05XX", "R10XX", "R30XX"]:
    b = show("Bundesbank " + t, f"https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.{t}.R.A.A._Z._Z.A?format=csv&lang=en&lastNObservations=5", 300)
    print("tail:", b[-250:])
b = show("BoE IADB", "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=01/Sep/2026&Dateto=now&SeriesCodes=IUDSNPY,IUDMNPY,IUDLNPY&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N", 500, ref="https://www.bankofengland.co.uk/boeapps/database/")
print("tail:", b[-300:])
show("BoE latest zip head", "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip", 80)
# --- CME delayed quotes
for name, pid in [("SR3", 8462), ("ZQ", 305), ("TY", 316)]:
    b = show("CME quotes " + name, f"https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/{pid}/G?isProtected&_t=1", 1200,
             ref="https://www.cmegroup.com/markets/interest-rates/stirs/three-month-sofr.quotes.html", accept="application/json, text/plain, */*")
# --- ICE
for name, pid in [("Euribor", 38527986), ("SONIA", 68361266)]:
    c, b = get(f"https://www.ice.com/products/{pid}/x/data")
    print(f"\n=== ICE page {name} HTTP {c} len={len(b)}")
    for m in sorted(set(re.findall(r"(?:productId|hubId|marketId|getContractsAsJson|marketdata/[A-Za-z/._?=&-]+)[^\"'<>\s]{0,80}", b)))[:40]:
        print("  ", m)
    show("ICE delayed " + name, f"https://www.ice.com/marketdata/DelayedMarkets.shtml?getContractsAsJson=&productId={pid}&hubId=", 600,
         ref=f"https://www.ice.com/products/{pid}/x/data", accept="application/json")
# barchart as fallback check
show("barchart IM", "https://www.barchart.com/futures/quotes/IMZ26", 200)
