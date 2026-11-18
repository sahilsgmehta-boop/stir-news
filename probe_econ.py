"""Probe candidate sources for fresher economic data. Writes probe_out/*.txt"""
import os, sys, json, traceback, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import econ
from econ import get, estat, estat_ea, ons, yoy

os.makedirs("probe_out", exist_ok=True)
log = open("probe_out/summary.txt", "w")


def P(*a):
    print(*a)
    print(*a, file=log)
    log.flush()


def tail(s, n=6):
    return sorted(s.items())[-n:] if isinstance(s, dict) else s


def tryit(name, fn):
    try:
        r = fn()
        P("OK  ", name, "->", tail(r) if isinstance(r, dict) else str(r)[:600])
        return r
    except Exception as e:
        P("FAIL", name, "->", repr(e)[:300])


def raw(name, url, keep=4000, **kw):
    try:
        t = get(url, **kw)
        open("probe_out/%s.txt" % name, "w").write(t[:200000])
        P("OK  ", name, len(t), "bytes:", re.sub(r"\s+", " ", t[:keep // 8]))
        return t
    except Exception as e:
        P("FAIL", name, url, "->", repr(e)[:300])


# --- euro area IP and retail straight from Eurostat
tryit("EZ ip sts_inpr_m PCH_SM CA", lambda: estat_ea("sts_inpr_m", indic_bt="PRD", nace_r2="B-D", s_adj="CA", unit="PCH_SM"))
tryit("EZ ip sts_inpr_m I21 SCA", lambda: estat_ea("sts_inpr_m", indic_bt="PRD", nace_r2="B-D", s_adj="SCA", unit="I21"))
tryit("EZ retail sts_trtu_m PCH_SM CA", lambda: estat_ea("sts_trtu_m", indic_bt="VOL_SLS", nace_r2="G47", s_adj="CA", unit="PCH_SM"))
tryit("EZ core final", lambda: estat_ea("prc_hicp_minr", coicop18="TOT_X_NRG_FOOD", unit="RCH_A"))

# --- UK IP and retail straight from ONS
for cd in ("K222", "K27Q", "J5EK", "J5C4", "J4MC", "J5DB"):
    tryit("ONS " + cd, lambda cd=cd: ons(cd))

# --- US industrial production: Fed G.17 text file
t = raw("g17_ip_sa", "https://www.federalreserve.gov/releases/g17/ipdisk/ip_sa.txt")
if t:
    P("G17 B50001 lines:", [l for l in t.splitlines() if l.startswith('"B50001"') or l.startswith("B50001")][-3:])

# --- US retail sales: Census MARTS (no key, small request)
raw("census_marts", "https://api.census.gov/data/timeseries/eits/marts?get=cell_value,time_slot_id,category_code,data_type_code,seasonally_adj&category_code=44X72&data_type_code=SM&seasonally_adj=yes&time=from+2025-01")

# --- Michigan preliminary: home page
t = raw("umich_home", "http://www.sca.isr.umich.edu/")
if t:
    txt = re.sub(r"<[^>]+>", " ", t)
    txt = re.sub(r"\s+", " ", txt)
    i = txt.find("Preliminary")
    P("UMICH text:", txt[max(0, i - 300):i + 2500])

# --- Swiss: SECO GDP CSV, BFS PxWeb, DBnomics search
for nm, u in [
    ("seco_gdp_en", "https://www.seco.admin.ch/dam/seco/en/dokumente/Wirtschaft/Wirtschaftslage/BIP_Daten/ch_seco_gdp.csv.download.csv/ch_seco_gdp.csv"),
    ("seco_gdp_de", "https://www.seco.admin.ch/dam/seco/de/dokumente/Wirtschaft/Wirtschaftslage/BIP_Daten/ch_seco_gdp.csv.download.csv/ch_seco_gdp.csv"),
    ("seco_gdp_short", "https://www.seco.admin.ch/dam/seco/de/dokumente/Wirtschaft/Wirtschaftslage/BIP_Daten/ch_seco_gdp.csv"),
    ("pxweb_root", "https://www.pxweb.bfs.admin.ch/api/v1/en/"),
    ("pxweb_lik", "https://www.pxweb.bfs.admin.ch/api/v1/en/px-x-0502010000_101/px-x-0502010000_101.px"),
    ("pxweb_lik2", "https://www.pxweb.bfs.admin.ch/api/v1/en/px-x-0502010000_102/px-x-0502010000_102.px"),
    ("dbn_search_ch_cpi", "https://api.db.nomics.world/v22/search?q=switzerland%20consumer%20price%20index&limit=20"),
    ("dbn_search_ch_unemp", "https://api.db.nomics.world/v22/search?q=switzerland%20unemployment%20seco&limit=20"),
    ("snb_cubes_cpi", "https://data.snb.ch/api/cube/plkopr/dimensions/en"),
    ("ilo_ch", "https://rplumber.ilo.org/data/indicator/?id=UNE_DEAP_SEX_AGE_RT_M&ref_area=CHE&timefrom=2025&format=.csv"),
]:
    raw(nm, u)

# SNB cube latest dates, to see how far each lags
for cube, code in (("plkopr", "VVP"), ("plkoprex", "K1"), ("amarbma", "S1")):
    tryit("SNB %s %s" % (cube, code), lambda cube=cube, code=code: econ.snb(cube, code))

log.close()
