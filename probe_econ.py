"""One-off probe: which free economic-data sources answer from GitHub's servers, and with what series codes."""
import json, os, re, sys, time, urllib.request, urllib.error
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
OUT = "probe_out"
DB = "https://api.db.nomics.world/v22"
OE = "https://sdmx.oecd.org/public/rest/data/"
C5 = "USA+EA20+GBR+CAN+CHE"
P = []
def add(name, url, body=None, accept=None, keep=300000): P.append((name, url, body, accept, keep))

# --- reachability of official sources
add("fred", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE&cosd=2025-01-01", keep=2000)
add("bls_v1", "https://api.bls.gov/publicAPI/v1/timeseries/data/", body={"seriesid": ["CUSR0000SA0", "LNS14000000"], "startyear": "2025", "endyear": "2026"}, keep=3000)
add("ecb_hicp", "https://data-api.ecb.europa.eu/service/data/ICP/M.U2.N.000000.4.ANR?format=csvdata&lastNObservations=3", keep=3000)
add("estat_hicp", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr?geo=EA&coicop=CP00&coicop=TOT_X_NRG_FOOD&coicop=SERV&lastTimePeriod=3", keep=4000)
add("estat_une", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m?geo=EA20&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT&lastTimePeriod=3", keep=3000)
add("estat_gdp", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp?geo=EA20&s_adj=SCA&na_item=B1GQ&unit=CLV_PCH_PRE&unit=CLV_PCH_SM&lastTimePeriod=3", keep=3000)
add("estat_retail", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_trtu_m?geo=EA20&lastTimePeriod=1", keep=12000)
add("estat_ip", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_inpr_m?geo=EA20&lastTimePeriod=1", keep=12000)
add("estat_conf", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/ei_bsco_m?geo=EA20&lastTimePeriod=1", keep=12000)
add("estat_wages", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/lc_lci_r2_q?geo=EA20&lastTimePeriod=1", keep=12000)
add("ecb_wages", "https://data-api.ecb.europa.eu/service/data/STS/Q.U2.N.INWR.000000.3.ANR?format=csvdata&lastNObservations=3", keep=3000)
for cd, ds in [("d7g7", "mm23"), ("dko8", "mm23"), ("d7nn", "mm23"), ("mgsx", "lms"), ("kac3", "lms"), ("kai9", "lms"), ("ihyq", "qna"), ("ihyr", "qna"), ("ed3h", "mgdp"), ("j5ek", "drsi"), ("k27q", "diop")]:
    add("ons_" + cd, "https://www.ons.gov.uk/generator?format=csv&uri=/economy/inflationandpriceindices/timeseries/%s/%s" % (cd, ds), keep=600)
add("ons_api", "https://api.beta.ons.gov.uk/v1/search?content_type=timeseries&cdids=D7G7,DKO8,D7NN,MGSX,KAC3,KAI9,IHYQ,IHYR,ED3H,J5EK,K27Q,J467,ECYX,K222", keep=20000)
add("ons_api_data", "https://api.beta.ons.gov.uk/v1/data?uri=/economy/inflationandpriceindices/timeseries/d7g7/mm23", keep=1500)
add("statcan", "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
    body=[{"vectorId": v, "latestN": 2} for v in (41690973, 41690914, 2062815, 2062811, 65201210, 108785715, 108785714, 108785713, 41691233, 52367097, 2132579, 62305752)], keep=20000)
add("statcan_meta", "https://www150.statcan.gc.ca/t1/wds/rest/getSeriesInfoFromVector",
    body=[{"vectorId": v} for v in (41690973, 41690914, 2062815, 2062811, 65201210, 108785715, 108785714, 108785713, 41691233, 52367097, 2132579, 62305752)], keep=20000)
add("boc_groups", "https://www.bankofcanada.ca/valet/lists/groups/json", keep=1500000)
add("boc_cpi", "https://www.bankofcanada.ca/valet/observations/group/CPI_MONTHLY/json?recent=2", keep=8000)
for cube in ("plkopr", "amarbma", "gdpap", "gdprpq", "plkoprex", "amarbm"):
    add("snb_" + cube, "https://data.snb.ch/api/cube/%s/data/csv/en?fromDate=2026-01" % cube, keep=3000)
add("snb_dims", "https://data.snb.ch/api/cube/plkopr/dimensions/en", keep=6000)
add("umich_ics", "http://www.sca.isr.umich.edu/files/tbmics.csv", keep=1500)
add("umich_px", "http://www.sca.isr.umich.edu/files/tbmpx1px5.csv", keep=1500)
add("nyfed_sce", "https://www.newyorkfed.org/medialibrary/interactives/sce/sce/downloads/data/frbny-sce-data.xlsx", keep=200)
add("atl_wage", "https://www.atlantafed.org/-/media/documents/datafiles/chcs/wage-growth-tracker/wage-growth-data.xlsx", keep=200)

# --- DBnomics
add("dbn_providers", DB + "/providers", keep=400000)
ids = ["BLS/cu/CUSR0000SA0", "BLS/cu/CUSR0000SA0L1E", "BLS/cu/CUUR0000SA0", "BLS/ln/LNS14000000", "BLS/ce/CES0000000001", "BLS/ce/CES0500000003",
       "Eurostat/prc_hicp_manr/M.RCH_A.CP00.EA", "Eurostat/prc_hicp_manr/M.RCH_A.TOT_X_NRG_FOOD.EA", "Eurostat/prc_hicp_manr/M.RCH_A.SERV.EA",
       "Eurostat/prc_hicp_manr/M.RCH_A.CP00.CH", "Eurostat/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA20", "Eurostat/namq_10_gdp/Q.CLV_PCH_PRE.SCA.B1GQ.EA20",
       "ONS/MM23/D7G7.M", "ONS/MM23/D7G7", "ONS/LMS/MGSX.M", "BEA/NIPA-T10101/A191RL-Q", "BEA/NIPA-T20804/DPCERG-M", "BEA/NIPA-T20807/DPCERAM1M225NBEA",
       "Fed/G17/IP.B50001.S", "OECD/MEI/CHE.CPALTT01.GY.M", "OECD/KEI/CPALTT01.CHE.GY.M", "OECD/DP_LIVE/CHE.CPI.TOT.AGRWTH.M"]
for i in ids: add("dbn_" + re.sub(r"\W+", "_", i), DB + "/series/" + i + "?observations=1", keep=1500)
for pv in ("BLS", "BEA", "ONS", "STATCAN", "SECO", "FSO", "BFS", "Fed", "FED", "CENSUS", "SNB", "OECD", "UMICH", "ISM", "ECB", "BOE", "BOC"):
    add("dbn_ds_" + pv, DB + "/datasets/" + pv + "?limit=1", keep=1200)
for q in ("personal consumption expenditures price index monthly", "retail sales advance monthly United States", "industrial production index United States",
          "Canada consumer price index monthly all-items", "Canada labour force unemployment rate", "Canada gross domestic product monthly industry",
          "Switzerland consumer price index", "Switzerland unemployment rate registered", "Switzerland gross domestic product quarterly real",
          "UK consumer prices index annual rate", "UK unemployment rate aged 16 and over", "UK gross domestic product quarter on quarter growth",
          "average weekly earnings total pay", "consumer confidence indicator", "inflation expectations consumers"):
    add("dbn_search_" + re.sub(r"\W+", "_", q)[:40], DB + "/search?q=" + urllib.request.quote(q) + "&limit=12", keep=9000)

# --- OECD (new SDMX API), labels on so the codes explain themselves
add("oecd_kei", OE + "OECD.SDD.STES,DSD_KEI@DF_KEI,/" + C5 + ".M+Q.....?lastNObservations=1&format=csvfilewithlabels", accept="text/csv")
add("oecd_kei_b", OE + "OECD.SDD.STES,DSD_KEI@DF_KEI,/" + C5 + "......?lastNObservations=1&format=csvfilewithlabels", accept="text/csv")
add("oecd_prices", OE + "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,/" + C5 + ".M......?lastNObservations=1&format=csvfilewithlabels", accept="text/csv")
add("oecd_une", OE + "OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,/" + C5 + "........M?lastNObservations=1&format=csvfilewithlabels", accept="text/csv")
add("oecd_qna", OE + "OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD,/Q.." + C5 + "...B1GQ......?lastNObservations=1&format=csvfilewithlabels", accept="text/csv")
add("oecd_flows", "https://sdmx.oecd.org/public/rest/dataflow/all?detail=allstubs", accept="application/vnd.sdmx.structure+json", keep=900000)

os.makedirs(OUT, exist_ok=True)
summary = []
for name, url, body, accept, keep in P:
    t0 = time.time()
    try:
        h = {"User-Agent": UA, "Accept": accept or "*/*"}
        data = None
        if body is not None:
            data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
        r = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=90)
        raw = r.read(); code = r.status
    except urllib.error.HTTPError as e:
        raw = e.read() or b""; code = e.code
    except Exception as e:
        raw = repr(e).encode(); code = 0
    txt = raw[:keep].decode("utf-8", "replace") if not raw[:4] == b"PK\x03\x04" else "ZIP/XLSX %d bytes" % len(raw)
    open(os.path.join(OUT, name + ".txt"), "w", encoding="utf-8").write(url + "\n" + txt)
    summary.append("%-48s %3d %8d bytes %5.1fs" % (name, code, len(raw), time.time() - t0))
    print(summary[-1]); sys.stdout.flush()
    time.sleep(1.2 if "oecd" in name else 0.3)
open(os.path.join(OUT, "_summary.txt"), "w").write("\n".join(summary) + "\n")
