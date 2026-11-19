# One-off (v2): public data for the SERFF liquidity-regime study. FRED refuses GitHub, so primary sources only.
# Every request has a hard 45s limit; each file is written as soon as it is done.
import urllib.request, urllib.parse, json, os, signal
os.makedirs("episodes", exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (stir-news episodes)", "Accept": "*/*"}
class TO(Exception): pass
def _alarm(*a): raise TO("hard timeout")
signal.signal(signal.SIGALRM, _alarm)
def get(u):
    signal.alarm(45)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30) as r: return r.read().decode("utf-8", "replace")
    finally: signal.alarm(0)
LOG = []
def log(s): LOG.append(s); print(s, flush=True); open("episodes/LOG.txt", "w").write("\n".join(LOG) + "\n")
NYF = "https://markets.newyorkfed.org/api"
YEARS = range(2018, 2027)
# 1. reference rates with percentiles, volumes and the target range
for kind, name in (("secured","sofr"),("secured","tgcr"),("secured","bgcr"),("unsecured","effr"),("unsecured","obfr")):
    rows = []
    for y in YEARS:
        try:
            for r in json.loads(get(f"{NYF}/rates/{kind}/{name}/search.json?startDate={y}-01-01&endDate={y}-12-31")).get("refRates", []):
                rows.append([r.get("effectiveDate"), r.get("percentRate"), r.get("percentPercentile1"), r.get("percentPercentile25"),
                             r.get("percentPercentile75"), r.get("percentPercentile99"), r.get("volumeInBillions"), r.get("targetRateFrom"), r.get("targetRateTo")])
        except Exception as e: log(f"{name} {y}: FAIL {e}")
    rows.sort(key=lambda x: x[0] or "")
    open(f"episodes/nyfed_{name}.csv", "w").write("date,rate,p1,p25,p75,p99,volume_bn,target_lo,target_hi\n" + "\n".join(",".join("" if v is None else str(v) for v in r) for r in rows) + "\n")
    log(f"{name}: {len(rows)} rows")
# 2. reverse repo and standing repo operations
for op in ("reverserepo", "repo"):
    rows = []
    for y in YEARS:
        try:
            d = json.loads(get(f"{NYF}/rp/{op}/all/results/search.json?startDate={y}-01-01&endDate={y}-12-31"))
            for o in d.get("repo", {}).get("operations", []):
                rows.append([o.get("operationDate"), o.get("operationType"), o.get("totalAmtSubmitted"), o.get("totalAmtAccepted"), o.get("acceptedCpty")])
        except Exception as e: log(f"{op} {y}: FAIL {e}")
    rows.sort(key=lambda x: x[0] or "")
    open(f"episodes/nyfed_{op}_ops.csv", "w").write("date,type,submitted,accepted,cpty\n" + "\n".join(",".join("" if v is None else str(v) for v in r) for r in rows) + "\n")
    log(f"{op} ops: {len(rows)} rows")
# 3. Treasury cash (TGA) and debt subject to the limit, daily
FD = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/"
for tab, fields in (("operating_cash_balance", "record_date,account_type,close_today_bal,open_today_bal"),
                    ("debt_subject_to_limit", "record_date,debt_catg,close_today_bal")):
    rows = []
    for y in YEARS:
        try:
            u = FD + tab + f"?filter=record_date:gte:{y}-01-01,record_date:lte:{y}-12-31&page[size]=10000&fields={fields}"
            for r in json.loads(get(u))["data"]: rows.append(",".join('"%s"' % (r.get(k) or "") for k in fields.split(",")))
        except Exception as e: log(f"{tab} {y}: FAIL {e}")
    open(f"episodes/dts_{tab}.csv", "w").write(fields + "\n" + "\n".join(rows) + "\n"); log(f"{tab}: {len(rows)} rows")
# 4. discovery: where reserves, the Fed balance sheet and money-fund assets live (saved for the next run)
for nm, u in (("ofr_search_reserve", "https://data.financialresearch.gov/v1/metadata/search?query=reserve*"),
              ("ofr_search_mmf", "https://data.financialresearch.gov/v1/metadata/search?query=money%20market%20fund*"),
              ("ofr_mnemonics_fnyr", "https://data.financialresearch.gov/v1/metadata/mnemonics?dataset=fnyr"),
              ("ofr_mnemonics_mmf", "https://data.financialresearch.gov/v1/metadata/mnemonics?dataset=mmf"),
              ("dbn_fed_datasets", "https://api.db.nomics.world/v22/datasets/FED?limit=200"),
              ("dbn_h41_search", "https://api.db.nomics.world/v22/series/FED/H41?limit=50&q=reserve%20balances%20wednesday"),
              ("fed_h41_ddp", "https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H41")):
    try: t = get(u); open(f"episodes/disc_{nm}.txt", "w").write(t[:400000]); log(f"{nm}: {len(t)} bytes")
    except Exception as e: log(f"{nm}: FAIL {e}")
log("done")
