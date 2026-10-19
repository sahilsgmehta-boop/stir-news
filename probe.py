import subprocess, json, csv, io, datetime
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url):
    p = subprocess.run(["curl","-sS","-L","--compressed","-m","60","-A",UA,url],capture_output=True); return p.stdout.decode("utf-8","replace")
def cnbc(sym):
    d = json.loads(get(f"https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol={sym}"))
    bars = d["barData"]["priceBars"]
    print(sym, "raw sample:", [(b.get("tradeTime"), b.get("tradeTimeinMills"), b.get("close")) for b in bars[-8:]])
    out = {}
    for b in bars:
        t = str(b["tradeTime"]); out[f"{t[:4]}-{t[4:6]}-{t[6:8]}"] = float(b["close"])
    return out
def bbk(t):
    txt = get(f"https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.{t}.R.A.A._Z._Z.A?format=csv&lang=en&startPeriod=2025-10-01")
    out = {}
    for line in txt.splitlines():
        p = line.split(",")
        if len(p) >= 2 and len(p[0]) == 10 and p[0][:2] == "20" and p[1] not in (".", ""):
            out[p[0]] = float(p[1])
    return out
def boc(s):
    d = json.loads(get(f"https://www.bankofcanada.ca/valet/observations/{s}/json?start_date=2025-10-01"))
    return {o["d"]: float(o[s]["v"]) for o in d["observations"] if o.get(s, {}).get("v")}
def mof(col):
    out = {}
    for url in ["https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv",
                "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"]:
        rows = list(csv.reader(io.StringIO(get(url))))
        hdr = rows[1]; j = hdr.index(col)
        for r in rows[2:]:
            try:
                y, m, d = r[0].split("/"); dt = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
                if dt >= "2025-10-01" and r[j] not in ("-", ""): out[dt] = float(r[j])
            except Exception: pass
    return out
def boe(code):
    txt = get(f"https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=01/Oct/2025&Dateto=now&SeriesCodes={code}&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    out = {}
    for line in txt.splitlines()[1:]:
        p = line.split(",")
        try: out[datetime.datetime.strptime(p[0], "%d %b %Y").date().isoformat()] = float(p[1])
        except Exception: pass
    return out
def chg(m):
    ds = sorted(m); return {ds[i]: (m[ds[i]] - m[ds[i-1]]) * 100 for i in range(1, len(ds))}
def corr(a, b):
    k = [x for x in a if x in b]
    if len(k) < 20: return None, len(k)
    xa = [a[x] for x in k]; xb = [b[x] for x in k]
    ma = sum(xa)/len(xa); mb = sum(xb)/len(xb)
    num = sum((p-ma)*(q-mb) for p, q in zip(xa, xb))
    den = (sum((p-ma)**2 for p in xa) * sum((q-mb)**2 for q in xb)) ** .5
    return round(num/den, 3), len(k)
def shift(m, days):
    # move each date by n business days within the series own calendar
    ds = sorted(m); return {ds[i+days]: m[ds[i]] for i in range(len(ds)) if 0 <= i+days < len(ds)}
def compare(name, cn, off):
    cnw = {d: v for d, v in cn.items() if datetime.date.fromisoformat(d).weekday() < 5}
    for label, src in (("all", cn), ("weekdays", cnw)):
        cc = chg(src); oc = chg(off)
        res = {}
        for lag in (-1, 0, 1):
            # lag: compare cnbc date d with official date shifted
            od = sorted(off); idx = {d: i for i, d in enumerate(od)}
            m = {}
            for d, v in cc.items():
                if d in idx and 0 <= idx[d] + lag < len(od) and od[idx[d]+lag] in oc: m[d] = oc[od[idx[d]+lag]]
            res[lag] = corr(cc, m)
        # level diff
        k = [d for d in cnw if d in off]
        lv = sum(cnw[d] - off[d] for d in k) / max(len(k), 1) * 100
        print(f"{name} [{label}] corr of daily changes vs official at lag -1/0/+1: {res}  mean level gap {lv:.1f}bp over {len(k)} days")
pairs = [
  ("DE10", cnbc("DE10Y-DE"), bbk("R10XX")), ("DE2", cnbc("DE2Y-DE"), bbk("R02XX")),
  ("CA10", cnbc("CA10Y"), boc("BD.CDN.10YR.DQ.YLD")), ("CA2", cnbc("CA2Y"), boc("BD.CDN.2YR.DQ.YLD")),
  ("JP10", cnbc("JP10Y-JP"), mof("10Y")), ("JP2", cnbc("JP2Y-JP"), mof("2Y")),
  ("UK10", cnbc("GB10Y-GB"), boe("IUDMNPY")), ("UK5", cnbc("GB5Y-GB"), boe("IUDSNPY")),
  ("US10", cnbc("US10Y"), {}),
]
for n, a, b in pairs:
    if b: compare(n, a, b)
