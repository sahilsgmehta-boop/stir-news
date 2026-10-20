"""Temporary probe: how MSPD writes interest pay dates. Removed after use."""
import json, collections, sys
sys.path.insert(0, ".")
import repo
rd, ms = repo.mspd()
fmt = collections.Counter()
ex = {}
raw = repo.fd_all("/v1/debt/mspd/mspd_table_3_market", f"filter=record_date:eq:{rd}")
for r in raw:
    for i in (1, 2, 3, 4):
        p = r.get(f"interest_pay_date_{i}")
        if p:
            import re
            k = re.sub(r"\d", "9", p)
            fmt[k] += 1
            ex.setdefault(k, (p, r.get("security_class1_desc"), r.get("security_class2_desc"), r.get("interest_rate_pct")))
cls = collections.Counter(s["cls"] for s in ms.values())
nopay = collections.Counter(s["cls"] for s in ms.values() if not s["pays"])
sample = [r for r in raw if (r.get("security_class1_desc") or "").startswith("Bond")][:3]
with open("docs/probe_mspd.txt", "w") as f:
    f.write(f"record {rd}\nformats {dict(fmt)}\nexamples {ex}\nclasses {dict(cls)}\nno pays {dict(nopay)}\n")
    f.write(json.dumps(sample, indent=1)[:4000])
