import subprocess, json, datetime, collections, shutil
r = subprocess.run(["python", "curves.py", "--full"], capture_output=True, text=True)
print(r.stdout[-2000:], r.stderr[-3000:])
s = open("docs/curves.js").read(); d = json.loads(s[s.index("{"):s.rstrip().rstrip(";").rindex("}")+1])
shutil.copy("docs/curves.js", "probe/curves.js")
print("sources", d.get("sources"))
for c, T in d["countries"].items():
    for t, S in T.items():
        D = [x for x in S["d"] if x >= "2025-10-19"]
        wk = collections.Counter(datetime.date.fromisoformat(x).weekday() >= 5 for x in D)
        print(c, t, "n1y", len(D), "weekend", wk[True], "last", list(zip(S["d"][-4:], S["v"][-4:])))
st = json.load(open("data/curves.json"))
print("closes sample", {k: sorted(v.items())[-3:] for k, v in list(st["closes"].items())[:3]})
