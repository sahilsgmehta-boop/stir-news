"""Probe 4: long history for the debt-ceiling study -> probe_out/dc_*.json"""
import os, json, time, urllib.parse
from econ import get
os.makedirs("probe_out", exist_ok=True)
log = open("probe_out/summary4.txt", "w")
def P(*a):
    print(*a); print(*a, file=log); log.flush()
def J(url):
    return json.loads(get(url, accept="application/json", timeout=120))
def save(name, obj):
    json.dump(obj, open("probe_out/dc_%s.json" % name, "w"), separators=(",", ":"))
END = "2026-11-19"
# NY Fed reference rates
for name, path, start in (("sofr", "secured/sofr", "2018-04-02"), ("tgcr", "secured/tgcr", "2018-04-02"),
                          ("effr", "unsecured/effr", "2010-01-01"), ("obfr", "unsecured/obfr", "2016-03-01")):
    try:
        out = {}
        for a, b in (("2010-01-01", "2015-12-31"), ("2016-01-01", "2020-12-31"), ("2021-01-01", END)):
            if b < start: continue
            d = J("https://markets.newyorkfed.org/api/rates/%s/search.json?startDate=%s&endDate=%s" % (path, max(a, start), b))
            for r in d.get("refRates", []):
                out[r["effectiveDate"]] = [r.get("percentRate"), r.get("percentPercentile1"), r.get("percentPercentile99"), r.get("volumeInBillions")]
            time.sleep(1)
        save(name, out); P("OK", name, len(out), min(out) if out else None, max(out) if out else None)
    except Exception as e:
        P("FAIL", name, repr(e)[:200])
# ON RRP
try:
    out = {}
    for a, b in (("2013-09-01", "2017-12-31"), ("2018-01-01", "2021-12-31"), ("2022-01-01", END)):
        d = J("https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json?startDate=%s&endDate=%s" % (a, b))
        for r in d.get("repo", {}).get("operations", []):
            out[r["operationDate"]] = [r.get("totalAmtAccepted"), r.get("participatingCpty")]
        time.sleep(1)
    save("rrp", out); P("OK rrp", len(out), min(out), max(out))
except Exception as e:
    P("FAIL rrp", repr(e)[:200])
# Standing repo / repo operations (SRF take-up)
try:
    out = {}
    d = J("https://markets.newyorkfed.org/api/rp/repo/all/results/search.json?startDate=2019-09-01&endDate=%s" % END)
    for r in d.get("repo", {}).get("operations", []):
        out.setdefault(r["operationDate"], 0); out[r["operationDate"]] += float(r.get("totalAmtAccepted") or 0)
    save("repoops", out); P("OK repoops", len(out))
except Exception as e:
    P("FAIL repoops", repr(e)[:200])
# TGA (Daily Treasury Statement)
try:
    out = {}; page = 1
    while True:
        u = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
             "?filter=record_date:gte:2010-06-01&fields=record_date,account_type,close_today_bal,open_today_bal&page[size]=10000&page[number]=%d" % page)
        d = J(u)
        for r in d["data"]:
            out.setdefault(r["record_date"], []).append([r["account_type"], r["close_today_bal"], r["open_today_bal"]])
        if page >= d["meta"]["total-pages"]: break
        page += 1
    save("tga", out); P("OK tga", len(out), min(out), max(out)); P(" types", sorted({x[0] for v in out.values() for x in v}))
except Exception as e:
    P("FAIL tga", repr(e)[:200])
# Bills outstanding (MSPD)
try:
    u = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_1"
         "?filter=record_date:gte:2010-01-01,security_class_desc:eq:Bills&fields=record_date,security_type_desc,security_class_desc,total_mil_amt&page[size]=10000")
    d = J(u); out = {}
    for r in d["data"]:
        if r["security_type_desc"] == "Marketable": out[r["record_date"]] = r["total_mil_amt"]
    save("bills", out); P("OK bills", len(out), min(out), max(out))
except Exception as e:
    P("FAIL bills", repr(e)[:200])
# Debt subject to limit (DTS table III-C)
try:
    out = {}; page = 1
    while True:
        u = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/debt_subject_to_limit"
             "?filter=record_date:gte:2010-06-01&page[size]=10000&page[number]=%d" % page)
        d = J(u)
        for r in d["data"]:
            out.setdefault(r["record_date"], []).append([r.get("debt_catg"), r.get("close_today_bal")])
        if page >= d["meta"]["total-pages"]: break
        page += 1
    save("dsl", out); P("OK dsl", len(out), min(out), max(out)); P(" catg", sorted({x[0] for v in out.values() for x in v})[:20])
except Exception as e:
    P("FAIL dsl", repr(e)[:200])
# OFR short-term funding monitor: GCF / tri-party / DVP repo before SOFR
try:
    d = J("https://data.financialresearch.gov/v1/series/search?query=GCF")
    P("OFR search GCF:", json.dumps(d)[:1500])
    d2 = J("https://data.financialresearch.gov/v1/series/search?query=effective%20federal%20funds")
    P("OFR search EFFR:", json.dumps(d2)[:800])
except Exception as e:
    P("FAIL ofr search", repr(e)[:200])
for m in ("REPO-GCF_AR_T-P", "REPO-GCF_AR_AG-P", "REPO-TRI_AR_OO-P", "REPO-DVP_AR_OO-P", "FNYR-EFFR-A", "FNYR-SOFR-A"):
    try:
        d = J("https://data.financialresearch.gov/v1/series/timeseries?mnemonic=%s" % m)
        if isinstance(d, list) and d:
            save("ofr_" + m, d); P("OK OFR", m, len(d), d[0], d[-1])
        else:
            P("EMPTY OFR", m, str(d)[:200])
    except Exception as e:
        P("FAIL OFR", m, repr(e)[:150])
log.close()
