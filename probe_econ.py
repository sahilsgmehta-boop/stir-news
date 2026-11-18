"""Probe 2: find Swiss official files (SECO GDP, BFS CPI, SECO unemployment)."""
import os, re, json
from econ import get
os.makedirs("probe_out", exist_ok=True)
log = open("probe_out/summary2.txt", "w")
def P(*a):
    print(*a); print(*a, file=log); log.flush()
def page(name, url, pat=r'href="([^"]+\.(?:csv|xlsx|xls|json)[^"]*)"'):
    try:
        t = get(url)
        open("probe_out/%s.html" % name, "w").write(t)
        links = sorted(set(re.findall(pat, t)))
        P("OK  ", name, len(t), "links:", links[:60])
        dam = sorted(set(re.findall(r'(https?://dam-api\.bfs\.admin\.ch[^"\' <]+|/bfsstatic/dam/assets/\d+/[^"\' <]*|/dam/[^"\' <]+)', t)))
        P("     dam:", dam[:60])
        return t
    except Exception as e:
        P("FAIL", name, url, repr(e)[:200])
page("seco_gdp_page_en", "https://www.seco.admin.ch/seco/en/home/wirtschaftslage---wirtschaftspolitik/Wirtschaftslage/bip-quartalsschaetzungen-/daten.html")
page("seco_gdp_page_de", "https://www.seco.admin.ch/seco/de/home/wirtschaftslage---wirtschaftspolitik/Wirtschaftslage/bip-quartalsschaetzungen-/daten.html")
page("bfs_lik_page", "https://www.bfs.admin.ch/bfs/en/home/statistics/prices/consumer-price-index.html")
page("bfs_lik_tables", "https://www.bfs.admin.ch/bfs/en/home/statistics/prices/consumer-price-index/tables.html")
for nm, u in [
    ("dam_lik_search", "https://dam-api.bfs.admin.ch/hub/api/dam/assets?language=en&limit=30&prodima=900104&orderNr=cc-e-05.02.08"),
    ("dam_lik_order", "https://dam-api.bfs.admin.ch/hub/api/dam/assets?orderNr=cc-d-05.02.08"),
    ("dam_lik_order2", "https://dam-api.bfs.admin.ch/hub/api/dam/assets?orderNr=cc-d-05.02.67"),
    ("amstat", "https://www.amstat.ch/v2/index.jsp"),
]:
    try:
        t = get(u); open("probe_out/%s.txt" % nm, "w").write(t[:300000]); P("OK  ", nm, len(t), re.sub(r"\s+", " ", t[:1500]))
    except Exception as e:
        P("FAIL", nm, repr(e)[:200])
page("seco_alv_page", "https://www.arbeit.swiss/secoalv/de/home/menue/institutionen-medien/statistiken.html")
log.close()
