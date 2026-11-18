import json, os, sys, time
sys.argv = ["x"]
import markets as m
os.makedirs("probe_out", exist_ok=True)
out = {}
syms = ["HE=F", "LE=F", "GF=F", "NG=F", "CL=F", "GC=F", "ZC=F", "KC=F", "ALI=F", "OJ=F", "TTF=F", "BZ=F"]
for s in syms:
    try:
        h, info = m.yahoo(s, "1mo")
        out[s] = {"info": info, "last": sorted(h.items())[-3:]}
    except Exception as e:
        out[s] = {"err": str(e)}
    time.sleep(0.3)
cands = ["HEZ26.CME", "HEG27.CME", "LEZ26.CME", "LEG27.CME", "GFF27.CME", "GFZ26.CME", "NGZ26.NYM", "NGF27.NYM",
         "CLF27.NYM", "GCZ26.CMX", "GCG27.CMX", "ZCZ26.CBT", "ZCH27.CBT", "KCZ26.NYB", "KCH27.NYB", "ALIF27.CMX", "ALIG27.CMX",
         "OJF27.NYB", "TTFZ26.NYM", "TTFF27.NYM", "BZF27.NYM", "NGZ25.NYM", "CLZ25.NYM", "GCZ25.CMX", "HEZ25.CME"]
for c in cands:
    try:
        h, info = m.yahoo(c, "10y", fut=True)
        ds = sorted(h)
        out[c] = {"n": len(ds), "first": ds[0] if ds else None, "last": ds[-1] if ds else None,
                  "sample": [(d, h[d]) for d in ds[:3]] + [(d, h[d]) for d in ds[-3:]], "info": info,
                  "h": h}
    except Exception as e:
        out[c] = {"err": str(e)}
    time.sleep(0.3)
for s in syms:
    try:
        h, info = m.yahoo(s, "10y")
        out[s]["h10"] = h
    except Exception as e:
        out[s]["err10"] = str(e)
json.dump(out, open("probe_out/probe.json", "w"))
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("h", "h10")} for k, v in out.items()}, indent=0)[:6000])
