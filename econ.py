"""Economic data for the dashboard's Economic data page -> docs/econ.js

Ten years of the main releases for the five rate markets on the dashboard
(US, euro area, UK, Canada, Switzerland), from free official sources that
need no key:

  US           BLS public API (CPI, unemployment, payrolls, hourly earnings),
               BEA tables through DBnomics (PCE prices, GDP), University of
               Michigan (sentiment, inflation expectations)
  Euro area    Eurostat (HICP, unemployment, GDP, consumer survey), ECB
               (negotiated wages)
  UK           ONS (CPI, unemployment, average weekly earnings, GDP)
  Canada       Statistics Canada (CPI and the Bank's core measures, labour
               force, GDP), Bank of Canada Valet (consumer expectations)
  Switzerland  SNB data portal (CPI, registered unemployment)
  all five     OECD Key Economic Indicators (GDP, retail sales volume,
               industrial production, consumer confidence), which also fills
               in where a national source fails

FRED is not used: it refuses connections from GitHub's servers. PMIs and the
ISM are paid data and are not here.

Every series is stored as "period:value" pairs (YYYY-MM or YYYY-Qn). A source
that fails keeps its last good data (data/econ.json) and is named in health.
The script paces itself: a full refresh every 3 hours, otherwise it exits.

python econ.py [--full]
"""
import csv, io, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "econ.json")
OUT = os.path.join(HERE, "docs", "econ.js")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
VERSION = 1
EVERY_HOURS = 3
NOW = datetime.now(timezone.utc)
Y0 = NOW.year - 11            # fetch from here; one spare year so year-on-year rates reach back ten
KEEP_FROM = "%d-01" % (NOW.year - 10)
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
health = {"errors": [], "requests": 0, "notes": []}


def get(url, body=None, accept="*/*", timeout=60):
    health["requests"] += 1
    h = {"User-Agent": UA, "Accept": accept}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt == 1:
                time.sleep(6)
                continue
            raise
        except Exception:
            if attempt == 1:
                time.sleep(3)
                continue
            raise


def num(x):
    try:
        v = float(str(x).replace(",", "").strip())
        return v if v == v else None
    except Exception:
        return None


# ------------------------------------------------------------------ period arithmetic
def p_shift(p, n):
    """period n steps back/forward: months for YYYY-MM, quarters for YYYY-Qn"""
    if "Q" in p:
        y, q = int(p[:4]), int(p[6])
        t = y * 4 + (q - 1) + n
        return "%d-Q%d" % (t // 4, t % 4 + 1)
    y, m = int(p[:4]), int(p[5:7])
    t = y * 12 + (m - 1) + n
    return "%d-%02d" % (t // 12, t % 12 + 1)


def per_year(s):
    return 4 if any("Q" in p for p in s) else 12


def yoy(s):
    n = per_year(s)
    return {p: (v / s[p_shift(p, -n)] - 1) * 100 for p, v in s.items() if s.get(p_shift(p, -n))}


def pop(s, k=1):
    """% change on k periods earlier"""
    return {p: (v / s[p_shift(p, -k)] - 1) * 100 for p, v in s.items() if s.get(p_shift(p, -k))}


def diff(s, scale=1.0):
    return {p: (v - s[p_shift(p, -1)]) * scale for p, v in s.items() if p_shift(p, -1) in s}


def ann3(s):
    """3-month change at an annual rate, for a seasonally adjusted index"""
    return {p: ((v / s[p_shift(p, -3)]) ** 4 - 1) * 100 for p, v in s.items() if s.get(p_shift(p, -3))}


# ------------------------------------------------------------------ sources
_cache = {}


def once(key, fn):
    if key not in _cache:
        try:
            _cache[key] = ("ok", fn())
        except Exception as e:
            _cache[key] = ("err", e)
    st, v = _cache[key]
    if st == "err":
        raise v
    return v


def dbn(sid):
    """DBnomics mirror of official tables; sid = provider/dataset/series"""
    d = json.loads(get("https://api.db.nomics.world/v22/series/" + sid + "?observations=1"))
    doc = d["series"]["docs"][0]
    out = {}
    for p, v in zip(doc["period"], doc["value"]):
        v = num(v)
        if v is not None:
            out[p] = v
    return out


BLS_IDS = ["CUUR0000SA0", "CUUR0000SA0L1E", "CUSR0000SA0", "CUSR0000SA0L1E", "CUUR0000SASLE",
           "LNS14000000", "CES0000000001", "CES0500000003"]


def _bls_all():
    out = {i: {} for i in BLS_IDS}
    for a, b in ((Y0, Y0 + 5), (Y0 + 6, NOW.year)):
        d = json.loads(get("https://api.bls.gov/publicAPI/v1/timeseries/data/",
                           body={"seriesid": BLS_IDS, "startyear": str(a), "endyear": str(b)}))
        if d.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError("BLS: " + str(d.get("message"))[:200])
        for s in d["Results"]["series"]:
            for o in s["data"]:
                if re.match(r"M(0[1-9]|1[0-2])$", o["period"]):
                    v = num(o["value"])
                    if v is not None:
                        out[s["seriesID"]]["%s-%s" % (o["year"], o["period"][1:])] = v
        time.sleep(1)
    return out


def bls(sid):
    try:
        s = once("bls", _bls_all)[sid]
        if len(s) > 24:
            return s
    except Exception as e:
        note("BLS direct failed (%s); using the DBnomics copy" % str(e)[:80])
    return dbn("BLS/%s/%s" % (sid[:2].lower(), sid))


def estat(dataset, **dims):
    q = "&".join("%s=%s" % (k, urllib.parse.quote(str(v))) for k, v in dims.items())
    d = json.loads(get("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/%s?%s&sinceTimePeriod=%d-01"
                       % (dataset, q, Y0)))
    size = 1
    for k in d["id"]:
        if k != "time":
            size *= len(d["dimension"][k]["category"]["index"])
    if size != 1:
        raise RuntimeError("Eurostat %s: filter leaves %d series" % (dataset, size))
    out = {}
    for p, i in d["dimension"]["time"]["category"]["index"].items():
        v = d["value"].get(str(i))
        if v is not None:
            out[p] = float(v)
    return out


def ecb(key):
    flow, k = key.split("/", 1)
    t = get("https://data-api.ecb.europa.eu/service/data/%s/%s?format=csvdata&startPeriod=%d-01" % (flow, k, Y0), accept="text/csv")
    out = {}
    for r in csv.DictReader(io.StringIO(t)):
        v = num(r.get("OBS_VALUE"))
        if v is not None:
            out[r["TIME_PERIOD"]] = v
    return out


def ons(cdid):
    d = json.loads(get("https://api.beta.ons.gov.uk/v1/search?content_type=timeseries&cdids=" + cdid))
    items = [i for i in d.get("items", []) if str(i.get("cdid", "")).upper() == cdid.upper() and i.get("uri")]
    if not items:
        raise RuntimeError("ONS: no series " + cdid)
    items.sort(key=lambda i: str(i.get("release_date", "")), reverse=True)
    time.sleep(0.6)
    d = json.loads(get("https://api.beta.ons.gov.uk/v1/data?uri=" + items[0]["uri"]))
    time.sleep(0.6)
    out = {}
    for o in d.get("months", []):
        m = str(o.get("month", ""))[:3].upper()
        v = num(o.get("value"))
        if m in MONTHS and v is not None and int(o["year"]) >= Y0:
            out["%s-%02d" % (o["year"], MONTHS.index(m) + 1)] = v
    if not out:
        for o in d.get("quarters", []):
            v = num(o.get("value"))
            if v is not None and int(o["year"]) >= Y0 and re.match(r"Q[1-4]$", str(o.get("quarter", ""))):
                out["%s-%s" % (o["year"], o["quarter"])] = v
    return out


CA_VEC = {"cpi": 41690973, "core_xfe": 41691233, "trim": 108785715, "median": 108785714, "unemp": 2062815,
          "emp": 2062811, "wage": 2132579, "gdp_m": 65201210, "gdp_q": 62305752}


def _statcan_all():
    body = [{"vectorId": v, "latestN": 12 * 12} for v in CA_VEC.values()]
    d = json.loads(get("https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods", body=body))
    out = {}
    for x in d:
        if x.get("status") != "SUCCESS":
            continue
        o = x["object"]
        s = {}
        for p in o["vectorDataPoint"]:
            v = num(p.get("value"))
            if v is None:
                continue
            y, m = p["refPer"][:4], int(p["refPer"][5:7])
            s["%s-Q%d" % (y, (m - 1) // 3 + 1) if o["vectorId"] == CA_VEC["gdp_q"] else "%s-%02d" % (y, m)] = v
        out[o["vectorId"]] = s
    return out


def statcan(name):
    s = once("statcan", _statcan_all).get(CA_VEC[name])
    if not s:
        raise RuntimeError("StatCan: no data for " + name)
    return s


def snb(cube, code):
    t = once("snb:" + cube, lambda: get("https://data.snb.ch/api/cube/%s/data/csv/en?fromDate=%d-01" % (cube, Y0)))
    out = {}
    for line in t.splitlines():
        c = [x.strip('"') for x in line.strip().lstrip("﻿").split(";")]
        if len(c) >= 3 and re.match(r"\d{4}-(\d{2}|Q\d)$", c[0]) and c[-2] == code:
            v = num(c[-1])
            if v is not None:
                out[c[0]] = v
    return out


OECD_AREA = {"US": "USA", "EZ": "EA20", "UK": "GBR", "CA": "CAN", "CH": "CHE"}


def _oecd_all():
    url = ("https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_KEI@DF_KEI,/"
           "USA+EA20+GBR+CAN+CHE.M+Q.PRVM+TOVM+CCICP+B1GQ_Q+UNEMP+CP....?startPeriod=%d-01&format=csvfile" % Y0)
    t = get(url, accept="text/csv", timeout=120)
    out = {}
    for r in csv.DictReader(io.StringIO(t)):
        v = num(r.get("OBS_VALUE"))
        if v is None:
            continue
        k = (r["REF_AREA"], r["FREQ"], r["MEASURE"], r["UNIT_MEASURE"], r["ACTIVITY"], r["TRANSFORMATION"])
        out.setdefault(k, {})[r["TIME_PERIOD"]] = v
    return out


def oecd(c, freq, measure, unit, activity, transf):
    s = once("oecd", _oecd_all).get((OECD_AREA[c], freq, measure, unit, activity, transf))
    if not s:
        raise RuntimeError("OECD: no %s %s %s for %s" % (measure, freq, transf, c))
    return s


def umich(file, col):
    t = once("umich:" + file, lambda: get("http://www.sca.isr.umich.edu/files/%s.csv" % file))
    rows = list(csv.reader(io.StringIO(t)))
    hdr = None
    out = {}
    for r in rows:
        r = [x.strip() for x in r]
        if hdr is None:
            if col in r:
                hdr = r
            continue
        if len(r) <= hdr.index(col):
            continue
        m = r[0][:3].upper()
        v = num(r[hdr.index(col)])
        if m in MONTHS and v is not None and r[1].isdigit() and int(r[1]) >= Y0:
            out["%s-%02d" % (r[1], MONTHS.index(m) + 1)] = v
    return out


def boc_ces(*want):
    """Bank of Canada consumer expectations (quarterly): the series whose label has every word in want"""
    d = once("boc:CES_C1", lambda: json.loads(get("https://www.bankofcanada.ca/valet/observations/group/CES_C1/json")))
    det = d.get("seriesDetail", {})
    if "boc" not in health:
        health["boc"] = {k: v.get("label") for k, v in det.items()}
    pick = [k for k, v in det.items() if all(w.lower() in (str(v.get("label", "")) + " " + k).lower() for w in want)]
    if not pick:
        raise RuntimeError("BoC CES_C1: no series matching " + "/".join(want))
    out = {}
    for o in d.get("observations", []):
        v = num((o.get(pick[0]) or {}).get("v"))
        if v is not None:
            y, m = o["d"][:4], int(o["d"][5:7])
            out["%s-Q%d" % (y, (m - 1) // 3 + 1)] = v
    return out


def note(msg):
    if msg not in health["notes"]:
        health["notes"].append(msg)


def first(*fns):
    """the first source that answers with data"""
    err = None
    for fn in fns:
        try:
            s = fn()
            if s and len(s) >= 8:
                return s
            err = RuntimeError("too little data")
        except Exception as e:
            err = e
    raise err


# ------------------------------------------------------------------ what the page shows
GROUPS = [["inf", "Inflation"], ["lab", "Labour market"], ["gro", "Growth & activity"], ["exp", "Expectations & sentiment"]]
COUNTRIES = [["US", "United States"], ["EZ", "Euro area"], ["UK", "United Kingdom"], ["CA", "Canada"], ["CH", "Switzerland"]]
# rows of the summary grid, in order: key, label, group
INDICATORS = [
    ["cpi", "CPI, headline", "inf"], ["core", "CPI, core", "inf"], ["svc", "CPI, services", "inf"],
    ["core3m", "Core, 3m annualised", "inf"], ["pce", "PCE prices", "inf"], ["corepce", "Core PCE prices", "inf"],
    ["median", "CPI-median", "inf"],
    ["unemp", "Unemployment rate", "lab"], ["jobs", "Jobs, monthly change", "lab"], ["wages", "Wage growth", "lab"],
    ["wages2", "Wage growth, total pay", "lab"],
    ["gdp_q", "GDP, quarter on quarter", "gro"], ["gdp_y", "GDP, year on year", "gro"], ["gdp_saar", "GDP, annualised", "gro"],
    ["gdp_m", "Monthly GDP", "gro"], ["retail", "Retail sales volume", "gro"], ["ip", "Industrial production", "gro"],
    ["conf", "Consumer confidence", "exp"], ["sent", "Michigan sentiment", "exp"],
    ["infexp1", "Inflation expected, 1 year", "exp"], ["infexp5", "Inflation expected, 5 years", "exp"],
]
S = []


def add(c, k, name, unit, src, fn, dp=1, hint=""):
    S.append({"c": c, "k": k, "name": name, "unit": unit, "src": src, "fn": fn, "dp": dp, "hint": hint})


# United States
add("US", "cpi", "CPI", "% y/y", "BLS", lambda: yoy(bls("CUUR0000SA0")))
add("US", "core", "Core CPI (ex food & energy)", "% y/y", "BLS", lambda: yoy(bls("CUUR0000SA0L1E")))
add("US", "svc", "Services ex energy services", "% y/y", "BLS", lambda: yoy(bls("CUUR0000SASLE")))
add("US", "core3m", "Core CPI, 3-month annualised", "% saar", "BLS", lambda: ann3(bls("CUSR0000SA0L1E")),
    hint="Seasonally adjusted core index, change over three months at an annual rate")
add("US", "pce", "PCE price index", "% y/y", "BEA", lambda: yoy(dbn("BEA/NIPA-T20804/DPCERG-M")))
add("US", "corepce", "Core PCE price index", "% y/y", "BEA", lambda: yoy(dbn("BEA/NIPA-T20804/DPCCRG-M")))
add("US", "unemp", "Unemployment rate", "%", "BLS", lambda: bls("LNS14000000"))
add("US", "jobs", "Nonfarm payrolls", "k m/m", "BLS", lambda: diff(bls("CES0000000001")), dp=0)
add("US", "wages", "Average hourly earnings", "% y/y", "BLS", lambda: yoy(bls("CES0500000003")))
add("US", "gdp_q", "GDP", "% q/q", "OECD", lambda: oecd("US", "Q", "B1GQ_Q", "GR", "_T", "G1"), dp=2)
add("US", "gdp_y", "GDP", "% y/y", "OECD", lambda: oecd("US", "Q", "B1GQ_Q", "GR", "_T", "GY"))
add("US", "gdp_saar", "GDP, annualised", "% q/q saar", "BEA", lambda: dbn("BEA/NIPA-T10101/A191RL-Q"))
add("US", "retail", "Retail sales volume", "% y/y", "OECD", lambda: oecd("US", "M", "TOVM", "GR", "G47", "GY"))
add("US", "ip", "Industrial production", "% y/y", "OECD", lambda: oecd("US", "M", "PRVM", "GR", "BTE", "GY"))
add("US", "conf", "Consumer confidence (OECD standardised)", "balance", "OECD", lambda: oecd("US", "M", "CCICP", "PB", "_Z", "_Z"))
add("US", "sent", "Michigan consumer sentiment", "index", "Univ. of Michigan", lambda: umich("tbmics", "ICS_ALL"))
add("US", "infexp1", "Michigan inflation expectations, 1 year", "%", "Univ. of Michigan", lambda: umich("tbmpx1px5", "PX_MD"))
add("US", "infexp5", "Michigan inflation expectations, 5 years", "%", "Univ. of Michigan", lambda: umich("tbmpx1px5", "PX5_MD"))

# Euro area
add("EZ", "cpi", "HICP", "% y/y", "Eurostat", lambda: estat("prc_hicp_manr", geo="EA", coicop="CP00", unit="RCH_A"))
add("EZ", "core", "Core HICP (ex energy, food, alcohol & tobacco)", "% y/y", "Eurostat",
    lambda: estat("prc_hicp_manr", geo="EA", coicop="TOT_X_NRG_FOOD", unit="RCH_A"))
add("EZ", "svc", "Services HICP", "% y/y", "Eurostat", lambda: estat("prc_hicp_manr", geo="EA", coicop="SERV", unit="RCH_A"))
add("EZ", "unemp", "Unemployment rate", "%", "Eurostat",
    lambda: estat("une_rt_m", geo="EA20", s_adj="SA", age="TOTAL", sex="T", unit="PC_ACT"))
add("EZ", "wages", "Negotiated wages", "% y/y", "ECB", lambda: ecb("STS/Q.U2.N.INWR.000000.3.ANR"))
add("EZ", "gdp_q", "GDP", "% q/q", "Eurostat", lambda: first(
    lambda: estat("namq_10_gdp", geo="EA20", s_adj="SCA", na_item="B1GQ", unit="CLV_PCH_PRE"),
    lambda: oecd("EZ", "Q", "B1GQ_Q", "GR", "_T", "G1")), dp=2)
add("EZ", "gdp_y", "GDP", "% y/y", "Eurostat", lambda: first(
    lambda: estat("namq_10_gdp", geo="EA20", s_adj="SCA", na_item="B1GQ", unit="CLV_PCH_SM"),
    lambda: oecd("EZ", "Q", "B1GQ_Q", "GR", "_T", "GY")))
add("EZ", "retail", "Retail sales volume", "% y/y", "OECD", lambda: oecd("EZ", "M", "TOVM", "GR", "G47", "GY"))
add("EZ", "ip", "Industrial production", "% y/y", "OECD", lambda: oecd("EZ", "M", "PRVM", "GR", "BTE", "GY"))
add("EZ", "conf", "Consumer confidence (European Commission)", "balance", "Eurostat", lambda: first(
    lambda: estat("ei_bsco_m", geo="EA20", indic="BS-CSMCI", s_adj="SA", unit="BAL"),
    lambda: oecd("EZ", "M", "CCICP", "PB", "_Z", "_Z")))
add("EZ", "infexp1", "Consumers expecting prices to rise, next 12 months", "balance", "Eurostat",
    lambda: estat("ei_bsco_m", geo="EA20", indic="BS-PT-NY", s_adj="SA", unit="BAL"),
    hint="European Commission consumer survey: a balance of answers, not a percentage rate")

# United Kingdom
add("UK", "cpi", "CPI", "% y/y", "ONS", lambda: ons("D7G7"))
add("UK", "core", "Core CPI (ex energy, food, alcohol & tobacco)", "% y/y", "ONS", lambda: ons("DKO8"))
add("UK", "svc", "Services CPI", "% y/y", "ONS", lambda: ons("D7NN"))
add("UK", "unemp", "Unemployment rate (3-month)", "%", "ONS", lambda: ons("MGSX"))
add("UK", "wages", "Average weekly earnings, regular pay (3m y/y)", "% y/y", "ONS", lambda: ons("KAI9"))
add("UK", "wages2", "Average weekly earnings, total pay (3m y/y)", "% y/y", "ONS", lambda: ons("KAC3"))
add("UK", "gdp_q", "GDP", "% q/q", "ONS", lambda: first(lambda: ons("IHYQ"), lambda: oecd("UK", "Q", "B1GQ_Q", "GR", "_T", "G1")), dp=2)
add("UK", "gdp_y", "GDP", "% y/y", "ONS", lambda: first(lambda: ons("IHYR"), lambda: oecd("UK", "Q", "B1GQ_Q", "GR", "_T", "GY")))
add("UK", "gdp_m", "Monthly GDP", "% m/m", "ONS", lambda: ons("ECYX"))
add("UK", "retail", "Retail sales volume", "% y/y", "OECD", lambda: oecd("UK", "M", "TOVM", "GR", "G47", "GY"))
add("UK", "ip", "Industrial production", "% y/y", "OECD", lambda: oecd("UK", "M", "PRVM", "GR", "BTE", "GY"))
add("UK", "conf", "Consumer confidence (GfK, via OECD)", "balance", "OECD", lambda: oecd("UK", "M", "CCICP", "PB", "_Z", "_Z"))

# Canada
add("CA", "cpi", "CPI", "% y/y", "Statistics Canada", lambda: yoy(statcan("cpi")))
add("CA", "core", "CPI-trim", "% y/y", "Statistics Canada", lambda: statcan("trim"), hint="One of the Bank of Canada's two preferred core measures")
add("CA", "median", "CPI-median", "% y/y", "Statistics Canada", lambda: statcan("median"))
add("CA", "unemp", "Unemployment rate", "%", "Statistics Canada", lambda: statcan("unemp"))
add("CA", "jobs", "Employment", "k m/m", "Statistics Canada", lambda: diff(statcan("emp")), dp=0)
add("CA", "wages", "Average hourly wage", "% y/y", "Statistics Canada", lambda: yoy(statcan("wage")))
add("CA", "gdp_q", "GDP", "% q/q", "Statistics Canada", lambda: first(
    lambda: pop(statcan("gdp_q")), lambda: oecd("CA", "Q", "B1GQ_Q", "GR", "_T", "G1")), dp=2)
add("CA", "gdp_y", "GDP", "% y/y", "Statistics Canada", lambda: first(
    lambda: yoy(statcan("gdp_q")), lambda: oecd("CA", "Q", "B1GQ_Q", "GR", "_T", "GY")))
add("CA", "gdp_m", "Monthly GDP", "% m/m", "Statistics Canada", lambda: pop(statcan("gdp_m")), dp=2)
add("CA", "retail", "Retail sales volume", "% y/y", "OECD", lambda: oecd("CA", "M", "TOVM", "GR", "G47", "GY"))
add("CA", "ip", "Industrial production", "% y/y", "OECD", lambda: oecd("CA", "M", "PRVM", "GR", "BTE", "GY"))
add("CA", "infexp1", "Consumer inflation expectations, 1 year", "%", "Bank of Canada", lambda: boc_ces("1-year"))
add("CA", "infexp5", "Consumer inflation expectations, 5 years", "%", "Bank of Canada", lambda: boc_ces("5-year"))

# Switzerland
add("CH", "cpi", "CPI", "% y/y", "SNB", lambda: snb("plkopr", "VVP"), dp=2)
add("CH", "core", "Core inflation 1 (ex fresh & seasonal products, energy & fuels)", "% y/y", "SNB",
    lambda: yoy(snb("plkoprex", "K1")), dp=2)
add("CH", "unemp", "Unemployment rate (registered, seasonally adjusted)", "%", "SNB", lambda: snb("amarbma", "S1"), dp=2)
add("CH", "gdp_q", "GDP", "% q/q", "OECD", lambda: oecd("CH", "Q", "B1GQ_Q", "GR", "_T", "G1"), dp=2)
add("CH", "gdp_y", "GDP", "% y/y", "OECD", lambda: oecd("CH", "Q", "B1GQ_Q", "GR", "_T", "GY"))
add("CH", "retail", "Retail sales volume", "% y/y", "OECD", lambda: oecd("CH", "M", "TOVM", "GR", "G47", "GY"))
add("CH", "ip", "Industrial production", "% y/y", "OECD", lambda: first(
    lambda: oecd("CH", "M", "PRVM", "GR", "BTE", "GY"), lambda: oecd("CH", "Q", "PRVM", "GR", "BTE", "GY")))
add("CH", "conf", "Consumer sentiment (SECO, via OECD)", "balance", "OECD", lambda: first(
    lambda: oecd("CH", "M", "CCICP", "PB", "_Z", "_Z"), lambda: oecd("CH", "Q", "CCICP", "PB", "_Z", "_Z")))


def pack(s, dp):
    return ",".join("%s:%s" % (p, ("%.*f" % (dp + 1, s[p])).rstrip("0").rstrip(".")) for p in sorted(s) if p >= KEEP_FROM)


def main():
    store = {}
    if os.path.exists(STORE):
        try:
            store = json.load(open(STORE, encoding="utf-8"))
        except Exception:
            store = {}
    if "--full" not in sys.argv and store.get("version") == VERSION and store.get("built"):
        age = (NOW - datetime.fromisoformat(store["built"].replace("Z", "+00:00"))).total_seconds() / 3600
        if age < EVERY_HOURS and os.path.exists(OUT):
            print("econ: %.1f h old, next refresh at %d h" % (age, EVERY_HOURS))
            return
    old = store.get("series", {})
    series, kept = [], []
    for d in S:
        sid = d["c"] + "." + d["k"]
        rec = {"id": sid, "c": d["c"], "k": d["k"], "name": d["name"], "unit": d["unit"], "src": d["src"], "dp": d["dp"]}
        if d["hint"]:
            rec["hint"] = d["hint"]
        try:
            s = d["fn"]()
            data = pack(s, d["dp"])
            if data.count(",") < 6:
                raise RuntimeError("only %d points" % (data.count(",") + 1))
            rec["data"] = data
            rec["got"] = NOW.strftime("%Y-%m-%d")
        except Exception as e:
            health["errors"].append("%s: %s" % (sid, str(e)[:140]))
            if sid in old and old[sid].get("data"):
                rec["data"] = old[sid]["data"]
                rec["got"] = old[sid].get("got")
                rec["stale"] = True
                kept.append(sid)
            else:
                continue
        rec["f"] = "Q" if "Q" in rec["data"].split(",")[0] else "M"
        series.append(rec)
        print("%-12s %-9s %3d pts  last %s" % (sid, d["src"][:9], rec["data"].count(",") + 1, rec["data"].split(",")[-1]))
    built = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"built": built, "version": VERSION, "countries": COUNTRIES, "groups": GROUPS, "indicators": INDICATORS,
           "series": series, "health": health}
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    json.dump({"built": built, "version": VERSION, "series": {r["id"]: r for r in series}}, open(STORE, "w", encoding="utf-8"),
              separators=(",", ":"))
    open(OUT, "w", encoding="utf-8").write("window.ECON = " + json.dumps(out, separators=(",", ":"), ensure_ascii=False) + ";\n")
    print("econ: %d series, %d errors, %d kept from before, %d requests" % (len(series), len(health["errors"]), len(kept), health["requests"]))
    for e in health["errors"]:
        print("  ! " + e)


if __name__ == "__main__":
    main()
