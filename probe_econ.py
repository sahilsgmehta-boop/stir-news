"""Probe 3: SECO GDP csv, BFS CPI xlsx, BFS core-inflation table, SECO unemployment."""
import os, re, json, io, urllib.request
from econ import get, UA
os.makedirs("probe_out", exist_ok=True)
log = open("probe_out/summary3.txt", "w")
def P(*a):
    print(*a); print(*a, file=log); log.flush()
def g(name, url, show=1500):
    try:
        t = get(url); open("probe_out/%s.txt" % name, "w").write(t[:400000]); P("OK  ", name, len(t), re.sub(r"\s+", " ", t[:show])); return t
    except Exception as e:
        P("FAIL", name, url, repr(e)[:200])
t = g("seco_gdp_csv", "https://scheduler.swissdatas.ch/scheduled/ch-seco-gdp.csv", 600)
if t:
    rows = t.splitlines(); P("rows", len(rows)); P("\n".join(rows[:3])); P("\n".join(rows[-40:]))
g("seco_gdp_json", "https://scheduler.swissdatas.ch/scheduled/ch-seco-gdp.json", 3000)
g("swissdatas_root", "https://scheduler.swissdatas.ch/scheduled/", 2000)
for n in ("ch-seco-alv", "ch-seco-unemployment", "ch-seco-gdp-flash", "ch-seco-arbeitslosigkeit"):
    g("sd_" + n, "https://scheduler.swissdatas.ch/scheduled/%s.csv" % n, 600)
# BFS CPI xlsx
def bfs_assets(order):
    d = json.loads(get("https://dam-api.bfs.admin.ch/hub/api/dam/assets?orderNr=" + order))
    return d.get("data", [])
try:
    import openpyxl
    a = [x for x in bfs_assets("cc-d-05.02.08") if x["bfs"]["lifecycle"]["code"] == "CURRENT"][0]
    href = [l["href"] for l in a["links"] if l.get("rel") == "master"][0]
    b = urllib.request.urlopen(urllib.request.Request(href, headers={"User-Agent": UA}), timeout=60).read()
    open("probe_out/lik.xlsx", "wb").write(b)
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        P("SHEET", ws.title, len(rows), "x", max(len(r) for r in rows) if rows else 0)
        for r in rows[:8]: P("  top", r[:16])
        for r in rows[-6:]: P("  end", r[:16])
except Exception as e:
    import traceback; P("FAIL lik xlsx", traceback.format_exc()[-600:])
# scan BFS order numbers 05.02.xx for titles (core inflation)
for i in list(range(1, 100)):
    o = "cc-d-05.02.%02d" % i
    try:
        for x in bfs_assets(o):
            if x["bfs"]["lifecycle"]["code"] == "CURRENT":
                P("ORDER", o, x["bfs"]["embargo"][:10], x["description"]["titles"].get("main"),
                  [l.get("format") for l in x["links"] if l.get("rel") == "master"])
    except Exception as e:
        P("ORDERFAIL", o, repr(e)[:80])
log.close()
