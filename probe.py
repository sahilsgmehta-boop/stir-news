"""Test run: can GitHub reach the non-US exchanges' open interest pages?
Saves each response (trimmed) to probe/ plus a summary, so it can be read
from the repo. Temporary - delete once the sources are settled."""
import os, re, subprocess, json, time
from urllib.parse import urljoin

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
URLS = json.load(open("probe_urls.json"))
os.makedirs("probe", exist_ok=True)
KEY = re.compile(r"open.?interest|statistic|report|csv|xls|download|volume|settle", re.I)

def get(url, data=None, HDRS=()):
    cmd = ["curl", "-sS", "-L", "-m", "60", "--http1.1", "--compressed", "-A", UA,
           "-H", "Accept: text/html,application/json,*/*;q=0.8",
           "-H", "Accept-Language: en-GB,en;q=0.9",
           "-w", "\n@@STATUS %{http_code} %{content_type}", url]
    if data:
        cmd[1:1] = ["--data", data]
    for h in HDRS:
        cmd[1:1] = ["-H", h]
    p = subprocess.run(cmd, capture_output=True)
    out = p.stdout.decode("utf-8", "replace")
    body, _, st = out.rpartition("\n@@STATUS ")
    st = st.strip()
    if not st or st.startswith("000"):
        st = (st + " curl-error " + p.stderr.decode()[:200]).strip()
    return st, body

summary = []
for name, item in URLS.items():
    url = item if isinstance(item, str) else item["url"]
    data = None if isinstance(item, str) else item.get("data")
    hd = () if isinstance(item, str) else item.get("headers", ())
    st, body = get(url, data, hd)
    links = sorted({urljoin(url, h) for h in re.findall(r'href=["\']([^"\'#]+)', body)
                    })[:2000]
    with open(f"probe/{name}.txt", "w") as f:
        f.write(f"URL {url}\nSTATUS {st}\nBYTES {len(body)}\n\n--- LINKS ---\n")
        f.write("\n".join(links))
        f.write("\n\n--- BODY  ---\n" + body[:3000000])
    oi = len(re.findall(r"open.?interest", body, re.I))
    summary.append(f"{name:28s} {st:40s} {len(body):>8d} bytes  'open interest' x{oi}")
    time.sleep(2)
open("probe/SUMMARY.txt", "w").write("\n".join(summary) + "\n")
print("\n".join(summary))
