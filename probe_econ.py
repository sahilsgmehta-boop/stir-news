import os, re, urllib.request, urllib.error
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0 Safari/537.36"
os.makedirs("probe_out", exist_ok=True)
def get(u, accept="*/*"):
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": accept}), timeout=120).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return "HTTP %d %s" % (e.code, (e.read() or b"")[:300].decode("utf-8", "replace"))
    except Exception as e:
        return "ERR " + repr(e)
E = "https://ec.europa.eu/eurostat/api/dissemination/"
toc = get(E + "catalogue/toc/txt?lang=en")
open("probe_out/toc_hicp.txt", "w").write("\n".join(l for l in toc.splitlines() if re.search(r"hicp|HICP", l))[:60000] or toc[:500])
for ds in ("prc_hicp_minr", "prc_hicp_mmor", "prc_hicp_midx", "prc_hicp_manr", "prc_hicp_mv12r", "prc_hicp_fp", "ei_cphi_m"):
    for geo in ("EA", "EA21", "EA20"):
        t = get(E + "statistics/1.0/data/%s?geo=%s&lastTimePeriod=1" % (ds, geo))
        open("probe_out/es_%s_%s.txt" % (ds, geo), "w").write(t[:200000])
open("probe_out/ecb_flow.txt", "w").write(get("https://data-api.ecb.europa.eu/service/dataflow/ECB/HICP?references=all", "application/vnd.sdmx.structure+xml;version=2.1")[:1500000])
open("probe_out/ecb_flows.txt", "w").write("\n".join(re.findall(r'<str:Dataflow[^>]*id="[^"]*"[^>]*>|<com:Name[^>]*>[^<]*', get("https://data-api.ecb.europa.eu/service/dataflow/ECB")))[:200000])
for k in ("M.U2.N.000000.4.ANR", "M.U2.N.CP00.4.ANR", "M.U2.N.TOTAL.4.ANR"):
    open("probe_out/ecb_HICP_%s.txt" % k, "w").write(get("https://data-api.ecb.europa.eu/service/data/HICP/%s?format=csvdata&lastNObservations=2" % k, "text/csv")[:3000])
open("probe_out/ecb_HICP_all.txt", "w").write(get("https://data-api.ecb.europa.eu/service/data/HICP/M.U2..........?format=csvdata&lastNObservations=1", "text/csv")[:400000])
