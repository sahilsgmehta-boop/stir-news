import json, os, sys, time
sys.argv = ["x"]
import markets as m
os.makedirs("probe_out", exist_ok=True)
out = {}
cc = [("US", "US{t}Y"), ("DE", "DE{t}Y-DE"), ("GB", "GB{t}Y-GB"), ("JP", "JP{t}Y-JP"), ("FR", "FR{t}Y-FR"), ("IT", "IT{t}Y-IT"),
      ("ES", "ES{t}Y-ES"), ("CA", "CA{t}Y"), ("AU", "AU{t}Y-AU"), ("CH", "CH{t}Y-CH"), ("IN", "IN{t}Y-IN")]
syms = [p.format(t=t) for t in (2, 5, 10, 30) for _, p in cc]
q = m.cnbc_quotes(syms)
out["quotes"] = q
out["missing"] = [s for s in syms if s not in q]
ch = {}
for s in syms:
    if s in q:
        try:
            d = m.cnbc_chart(s, "1Y"); ch[s] = [len(d), min(d) if d else None, max(d) if d else None]
        except Exception as e:
            ch[s] = str(e)
        time.sleep(0.2)
out["charts"] = ch
for s in ["^KS11", "^BVSP"]:
    h, info = m.yahoo(s, "1y"); out[s] = {d: h[d] for d in sorted(h) if "2026-07-24" <= d <= "2026-08-06" or "2026-10-20" <= d <= "2026-10-30"}
json.dump(out, open("probe_out/probe.json", "w"))
print("missing", out["missing"])
