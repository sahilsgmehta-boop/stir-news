# One-off: public FRED / NY Fed / Treasury data for the SERFF liquidity-regime study. Writes episodes/*.csv
import urllib.request, json, os, time
os.makedirs("episodes", exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 stir-news episodes"}
def get(u):
    for i in range(3):
        try: return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read().decode()
        except Exception as e: err = e; time.sleep(3)
    raise err
log = []
FRED = ["SOFR","SOFR1","SOFR25","SOFR75","SOFR99","EFFR","IORB","IOER","RRPONTSYD","RRPONTSYAWARD","WTREGEN","WDTGAL",
        "WRESBAL","TOTRESNS","WALCL","WSHOTSL","RPONTSYD","WRMFNS","WIMFSL","MMMFFAQ027S","DTB4WK","DTB3","OBFR"]
for s in FRED:
    try:
        t = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}&cosd=2017-06-01")
        open(f"episodes/fred_{s}.csv", "w").write(t); log.append(f"{s}: {t.count(chr(10))} rows")
    except Exception as e: log.append(f"{s}: FAIL {e}")
# NY Fed secured rates (TGCR, BGCR) with volumes, in yearly chunks
for kind in ["tgcr", "bgcr", "sofr"]:
    rows = []
    for y in range(2018, 2027):
        try:
            j = json.loads(get(f"https://markets.newyorkfed.org/api/rates/secured/{kind}/search.json?startDate={y}-01-01&endDate={y}-12-31"))
            for r in j.get("refRates", []): rows.append(f'{r.get("effectiveDate")},{r.get("percentRate")},{r.get("volumeInBillions","")},{r.get("percentPercentile1","")},{r.get("percentPercentile99","")}')
        except Exception as e: log.append(f"nyfed {kind} {y}: FAIL {e}")
    open(f"episodes/nyfed_{kind}.csv", "w").write("date,rate,volume_bn,p1,p99\n" + "\n".join(sorted(rows)) + "\n"); log.append(f"nyfed {kind}: {len(rows)} rows")
# Treasury daily TGA (Daily Treasury Statement, operating cash balance)
rows = []
for y in range(2018, 2027):
    u = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
         f"?filter=record_date:gte:{y}-01-01,record_date:lte:{y}-12-31&page[size]=10000&fields=record_date,account_type,close_today_bal,open_today_bal")
    try:
        for r in json.loads(get(u))["data"]: rows.append(",".join('"%s"' % (r.get(k) or "") for k in ["record_date","account_type","close_today_bal","open_today_bal"]))
    except Exception as e: log.append(f"dts {y}: FAIL {e}")
open("episodes/dts_cash.csv", "w").write("record_date,account_type,close_today_bal,open_today_bal\n" + "\n".join(rows) + "\n"); log.append(f"dts: {len(rows)} rows")
# debt subject to limit (DTS table III-C)
rows = []
for y in range(2018, 2027):
    u = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/debt_subject_to_limit"
         f"?filter=record_date:gte:{y}-01-01,record_date:lte:{y}-12-31&page[size]=10000&fields=record_date,debt_catg,close_today_bal")
    try:
        for r in json.loads(get(u))["data"]: rows.append(",".join('"%s"' % (r.get(k) or "") for k in ["record_date","debt_catg","close_today_bal"]))
    except Exception as e: log.append(f"debtlimit {y}: FAIL {e}")
open("episodes/dts_debt_limit.csv", "w").write("record_date,debt_catg,close_today_bal\n" + "\n".join(rows) + "\n"); log.append(f"debt limit: {len(rows)} rows")
open("episodes/LOG.txt", "w").write("\n".join(log) + "\n"); print("\n".join(log))
