"""Temporary probe: coupon interest by payment day. Removed after use."""
import sys
from datetime import date
sys.path.insert(0, ".")
import repo
rd, ms = repo.mspd()
asof, soma = repo.soma_holdings()
st, un = date(2026, 10, 1), date(2027, 3, 1)
a = repo.interest_by_date(ms, soma, 4.0, st, un)
b = repo.interest_by_date(ms, {}, 4.0, st, un)
lines = [f"mspd {rd} soma {asof} n_ms {len(ms)} n_soma {len(soma)} soma_total {sum(soma.values())/1e9:.0f}bn ms_total {sum(s['out'] for s in ms.values())/1e9:.0f}bn"]
for d in sorted(set(a) | set(b)):
    lines.append(f"{d} public {a.get(d,0)/1e9:.2f} all {b.get(d,0)/1e9:.2f}")
big = sorted(((s["out"], c, s["cls"], s["rate"], s["pays"], s["maturity"]) for c, s in ms.items() if "11/15" in s["pays"]), reverse=True)[:15]
for x in big:
    lines.append(f"{x[1]} {x[2]} {x[3]} {x[4]} {x[5]} out {x[0]/1e9:.1f}bn soma {soma.get(x[1],0)/1e9:.1f}bn")
open("docs/probe_mspd.txt", "w").write("\n".join(lines))
