"""US repo / funding-market data for the dashboard's Repo page -> docs/repo.js

Everything is free and public, no keys:
  NY Fed markets API   SOFR, TGCR, BGCR, EFFR, OBFR with 1/25/75/99th
                       percentiles and volumes; ON RRP results (amount, rate,
                       counterparties); repo operations (the Standing Repo
                       Facility); SOMA Treasury holdings by CUSIP
  Fed H.4.1 release    reserve balances (Wednesday level and week average),
                       weekly, from the release pages themselves
  Treasury fiscaldata  TGA closing balance (Daily Treasury Statement), every
                       auction (sizes, Fed add-ons, Treasury's estimate of the
                       publicly held amount maturing), debt outstanding by
                       CUSIP (for coupon interest)
  TreasuryDirect       auctions announced but not yet held
  OFR                  DTCC GCF repo rate on Treasuries; DVP repo rate
  DBnomics (BEA)       nominal GDP, for reserves as a share of GDP

FRED is not used: it refuses connections from GitHub's servers.

IORB is the top of the fed funds target range less 10bp, the rule in force
since the Fed's December 2024 technical adjustment.

Net issuance (the Wrightson "Treasury issuance less interest" basis), per
settlement date, in $bn:
    + public offering amounts settling (Fed add-ons are not in the offering)
    - publicly held securities maturing (outstanding less SOMA holdings)
    - coupon interest paid to the public
Announced auctions use their announced sizes; later ones repeat the latest
size of the same security on its usual calendar. Treasury changes bill sizes
week to week, so the projection drifts the further out it goes.

python repo.py               normal run (skips if it ran in the last 3 hours)
python repo.py --force       run regardless
python repo.py --dump DIR    save every raw download to DIR
python repo.py --cache DIR   read raw downloads from DIR instead of the web
"""
import html, json, os, re, subprocess, sys, time, hashlib
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "repo.json")
OUT = os.path.join(HERE, "docs", "repo.js")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
HISTORY_DAYS = 400          # a little over a year on the charts
AHEAD_DAYS = 125           # issuance projection: three full calendar months ahead
# Twice a day, India time: 19:00, after the New York Fed publishes the previous
# day's rates (8am New York), and 23:45, after Treasury's auction announcements
# (11am New York) and the day's auction results, so new bill sizes replace the
# estimates the same evening.
RUN_SLOTS_IST = [(19, 0), (23, 45)]
IST = timezone(timedelta(hours=5, minutes=30))
VERSION = 8                 # bump when the output changes: forces a run straight away
H41_PER_RUN = int(os.environ.get("REPO_H41_MAX", "60"))   # weekly H.4.1 pages per run while backfilling

health = {"errors": [], "requests": 0}
MODE = {"dump": None, "cache": None}


def get(url, accept="application/json"):
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    if MODE["cache"]:
        p = os.path.join(MODE["cache"], key)
        if not os.path.exists(p):
            raise IOError("not in cache: " + url)
        return open(p, encoding="utf-8").read()
    health["requests"] += 1
    last = ""
    for attempt in range(3):
        p = subprocess.run(["curl", "-sS", "-L", "-m", "90", "--compressed", "-A", UA,
                            "-H", "Accept: " + accept, "-w", "\n@@%{http_code}", url],
                           capture_output=True)
        out = p.stdout.decode("utf-8", "replace")
        body, _, code = out.rpartition("\n@@")
        if code == "200":
            if MODE["dump"]:
                os.makedirs(MODE["dump"], exist_ok=True)
                open(os.path.join(MODE["dump"], key), "w", encoding="utf-8").write(body)
                with open(os.path.join(MODE["dump"], "INDEX.txt"), "a") as f:
                    f.write(key + " " + url + "\n")
            return body
        last = f"HTTP {code or 'error'} {p.stderr.decode()[:100]}".strip()
        if code == "404":
            break
        time.sleep(2 + attempt * 3)
    raise IOError(last)


def jget(url):
    return json.loads(get(url))


def note(msg):
    health["errors"].append(str(msg)[:240])


def num(v):
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f


def d2s(d):
    return d.isoformat()


def s2d(s):
    return date.fromisoformat(str(s)[:10])


# ------------------------------------------------------------- calendar
def holidays(y):
    """Federal Reserve holidays: no Treasury settlement."""
    def nth(month, weekday, n):
        d = date(y, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)

    def last(month, weekday):
        d = date(y, month + 1, 1) - timedelta(days=1) if month < 12 else date(y, 12, 31)
        return d - timedelta(days=(d.weekday() - weekday) % 7)

    def obs(d):                       # Saturday -> none for the Fed; Sunday -> Monday
        return d + timedelta(days=1) if d.weekday() == 6 else d
    return {obs(date(y, 1, 1)), nth(1, 0, 3), nth(2, 0, 3), last(5, 0),
            obs(date(y, 6, 19)), obs(date(y, 7, 4)), nth(9, 0, 1), nth(10, 0, 2),
            obs(date(y, 11, 11)), nth(11, 3, 4), obs(date(y, 12, 25))}


_HOL = {}


def is_bd(d):
    if d.weekday() >= 5:
        return False
    if d.year not in _HOL:
        _HOL[d.year] = holidays(d.year)
    return d not in _HOL[d.year]


def next_bd(d):
    while not is_bd(d):
        d += timedelta(days=1)
    return d


# ------------------------------------------------------------- NY Fed
NYF = "https://markets.newyorkfed.org/api"


def nyfed_rates(start, end):
    out = {}
    for kind, name in (("secured", "sofr"), ("secured", "tgcr"), ("secured", "bgcr"),
                       ("unsecured", "effr"), ("unsecured", "obfr")):
        try:
            d = jget(f"{NYF}/rates/{kind}/{name}/search.json?startDate={start}&endDate={end}")
            for r in d.get("refRates", []):
                day = r.get("effectiveDate")
                if not day:
                    continue
                row = out.setdefault(day, {})
                row[name] = num(r.get("percentRate"))
                for p in ("1", "25", "75", "99"):
                    v = num(r.get("percentPercentile" + p))
                    if v is not None:
                        row[f"{name}_p{p}"] = v
                v = num(r.get("volumeInBillions"))
                if v is not None:
                    row[name + "_vol"] = v
                if name == "effr":
                    lo, hi = num(r.get("targetRateFrom")), num(r.get("targetRateTo"))
                    if lo is not None and hi is not None:
                        row["tlo"], row["thi"] = lo, hi
        except Exception as e:  # noqa: BLE001
            note(f"NY Fed {name.upper()}: {e}")
    return out


def nyfed_ops(daily):
    # ON RRP: one operation a day
    try:
        d = jget(f"{NYF}/rp/reverserepo/all/results/last/330.json")
        for op in d.get("repo", {}).get("operations", []):
            if op.get("term") != "Overnight":
                continue
            day = op.get("operationDate")
            row = daily.setdefault(day, {})
            row["rrp_amt"] = round((num(op.get("totalAmtAccepted")) or 0) / 1e9, 3)
            row["rrp_cpty"] = num(op.get("acceptedCpty"))
            for det in op.get("details", []):
                r = num(det.get("percentAwardRate")) or num(det.get("percentOfferingRate"))
                if r is not None:
                    row["rrp_rate"] = r
    except Exception as e:  # noqa: BLE001
        note(f"NY Fed reverse repo: {e}")
    # repo operations - the Standing Repo Facility (morning and afternoon)
    try:
        d = jget(f"{NYF}/rp/repo/all/results/last/700.json")
        for op in d.get("repo", {}).get("operations", []):
            day = op.get("operationDate")
            row = daily.setdefault(day, {})
            row["srf_amt"] = round(row.get("srf_amt", 0) + (num(op.get("totalAmtAccepted")) or 0) / 1e9, 3)
            for det in op.get("details", []):
                r = num(det.get("percentOfferingRate"))
                if r is not None and det.get("securityType") == "Treasury":
                    row["srf_rate"] = r
    except Exception as e:  # noqa: BLE001
        note(f"NY Fed repo operations: {e}")


def soma_holdings():
    """SOMA par by CUSIP, $ - as of the latest Wednesday."""
    d = jget(f"{NYF}/soma/asofdates/list.json")
    dates = sorted(d.get("soma", {}).get("asOfDates", []))
    if not dates:
        raise IOError("no SOMA dates")
    asof = dates[-1]
    h = jget(f"{NYF}/soma/tsy/get/asof/{asof}.json")
    out = {}
    for x in h.get("soma", {}).get("holdings", []):
        c = x.get("cusip")
        v = num(x.get("parValue"))
        if c and v:
            out[c] = v
    return asof, out


# ------------------------------------------------------------- Treasury
FD = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"


def fd_all(path, params):
    rows, page = [], 1
    while True:
        url = f"{FD}{path}?{params}&page%5Bnumber%5D={page}&page%5Bsize%5D=10000"
        d = jget(url)
        rows += d.get("data", [])
        tp = int((d.get("meta") or {}).get("total-pages") or 1)
        if page >= tp:
            return rows
        page += 1


def tga(start):
    rows = fd_all("/v1/accounting/dts/operating_cash_balance",
                  f"filter=record_date:gte:{start}&fields=record_date,account_type,"
                  "open_today_bal,close_today_bal&sort=record_date")
    out = {}
    for r in rows:
        at = (r.get("account_type") or "").lower()
        if "closing balance" in at and ("tga" in at or "general account" in at):
            v = num(r.get("open_today_bal"))
            if v is None:
                v = num(r.get("close_today_bal"))
            if v is not None:
                out[r["record_date"]] = round(v / 1000, 3)       # millions -> billions
    return out


AUCTION_FIELDS = ("cusip,security_type,security_term,original_security_term,auction_date,"
                  "issue_date,maturity_date,offering_amt,total_accepted,soma_accepted,"
                  "reopening,cash_management_bill_cmb,est_pub_held_mat_by_type_amt,"
                  "int_rate,inflation_index_security,floating_rate,spread,high_investment_rate")


def auctions(since):
    rows = fd_all("/v1/accounting/od/auctions_query",
                  f"filter=maturity_date:gte:{since}&fields={AUCTION_FIELDS}&sort=issue_date")
    out = []
    for r in rows:
        try:
            out.append({
                "cusip": r["cusip"], "type": r.get("security_type") or "",
                "term": r.get("security_term") or "",
                "oterm": r.get("original_security_term") or r.get("security_term") or "",
                "auction": r.get("auction_date"), "issue": r.get("issue_date"),
                "maturity": r.get("maturity_date"),
                "offer": num(r.get("offering_amt")), "accepted": num(r.get("total_accepted")),
                "soma": num(r.get("soma_accepted")) or 0.0,
                "reopen": (r.get("reopening") or "").lower() == "yes",
                "cmb": (r.get("cash_management_bill_cmb") or "").lower() == "yes",
                "pubmat": num(r.get("est_pub_held_mat_by_type_amt")),
                "rate": num(r.get("int_rate")),
                "tips": (r.get("inflation_index_security") or "").lower() == "yes",
                "frn": (r.get("floating_rate") or "").lower() == "yes",
                "spread": num(r.get("spread")),
                "hir": num(r.get("high_investment_rate")),
            })
        except KeyError:
            continue
    return out


def upcoming():
    d = jget("https://www.treasurydirect.gov/TA_WS/securities/upcoming?format=json")
    out = []
    for r in d:
        out.append({
            "cusip": r.get("cusip"), "type": r.get("securityType") or "",
            "term": r.get("securityTerm") or "",
            "oterm": r.get("originalSecurityTerm") or r.get("securityTerm") or "",
            "auction": (r.get("auctionDate") or "")[:10], "issue": (r.get("issueDate") or "")[:10],
            "maturity": (r.get("maturityDate") or r.get("maturingDate") or "")[:10],
            "offer": num(r.get("offeringAmount")), "accepted": None, "soma": 0.0,
            "reopen": (r.get("reopening") or "").lower() == "yes",
            "cmb": (r.get("cashManagementBillCMB") or "").lower() == "yes" or r.get("type") == "CMB",
            # TreasuryDirect calls Treasury's estimate of the publicly held amount maturing
            # "privateHoldings" (checked 26 Oct 2026 against the auction announcements)
            "pubmat": num(r.get("privateHoldings")) or num(r.get("estimatedAmountOfPubliclyHeldMaturingSecuritiesByType")),
            "rate": num(r.get("interestRate")),
            "tips": "yes" in ((r.get("tips") or "") + (r.get("inflationIndexSecurity") or "")).lower(),
            "frn": (r.get("floatingRate") or "").lower() == "yes",
            "spread": num(r.get("spread")), "hir": None, "announced": True,
        })
    return out


def td_recent(days=30):
    """Auctions of the last `days` days from TreasuryDirect, with results. Treasury's
    results database (auctions_query) lags by about a week and can miss cash management
    bills altogether - the $25bn 10-day CMB of 26 Oct 2026 was absent from it - while
    TreasuryDirect has them on auction day."""
    d = jget(f"https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&days={days}")
    out = []
    for r in d:
        if not r.get("cusip") or not r.get("issueDate"):
            continue
        out.append({
            "cusip": r["cusip"], "type": r.get("securityType") or "",
            "term": r.get("securityTerm") or "",
            "oterm": r.get("originalSecurityTerm") or r.get("securityTerm") or "",
            "auction": (r.get("auctionDate") or "")[:10], "issue": r["issueDate"][:10],
            "maturity": (r.get("maturityDate") or "")[:10],
            "offer": num(r.get("offeringAmount")), "accepted": num(r.get("grandTotalParAwarded")),
            "soma": num(r.get("somaNoncompetitiveParAwarded")) or 0.0,
            "reopen": (r.get("reopening") or "").lower() == "yes",
            "cmb": r.get("type") == "CMB" or (r.get("cashManagementBillCMB") or "").lower() == "yes",
            "pubmat": num(r.get("privateHoldings")),
            "rate": num(r.get("interestRate")),
            "tips": (r.get("inflationProtected") or r.get("tips") or "").lower() == "yes",
            "frn": (r.get("floatingRate") or "").lower() == "yes",
            "spread": num(r.get("spread")), "hir": num(r.get("highInvestmentRate")),
        })
    return out


def merge_recent(hist, recent):
    """Fill results the Treasury database doesn't have yet, and add auctions it lacks."""
    by = {(a["cusip"], a["issue"]): a for a in hist}
    added = filled = 0
    for r in recent:
        h = by.get((r["cusip"], r["issue"]))
        if h is None:
            hist.append(r)
            by[(r["cusip"], r["issue"])] = r
            added += 1
            continue
        if not h.get("accepted") and r.get("accepted"):
            h["accepted"], h["soma"] = r["accepted"], r["soma"]
            filled += 1
        if not h.get("pubmat") and r.get("pubmat"):
            h["pubmat"] = r["pubmat"]
        if r.get("cmb"):
            h["cmb"] = True
    hist.sort(key=lambda a: a["issue"] or "")
    return added, filled


def mspd():
    """Marketable debt outstanding by CUSIP at the latest month end."""
    d = jget(f"{FD}/v1/debt/mspd/mspd_table_3_market?sort=-record_date&page%5Bsize%5D=1")
    rd = d["data"][0]["record_date"]
    rows = fd_all("/v1/debt/mspd/mspd_table_3_market", f"filter=record_date:eq:{rd}")
    out = {}
    for r in rows:
        c = r.get("security_class2_desc") or ""
        if not re.match(r"^[0-9A-Z]{9}$", c):
            continue
        cls = (r.get("security_class1_desc") or "")
        pays = [r.get(f"interest_pay_date_{i}") for i in (1, 2, 3, 4)]
        # a CUSIP can appear on more than one line (reopenings are listed under the
        # original issue, with the amounts on only one of them). Keeping whichever
        # line came last threw away the 10-year notes' amounts - every one of them
        # read as zero - so the big 15 Feb/May/Aug/Nov coupon days were badly short.
        amt = (num(r.get("outstanding_amt")) or 0) * 1e6
        if c in out and out[c]["out"] >= amt:
            continue
        out[c] = {"cls": cls, "rate": num(r.get("interest_rate_pct")),
                  "out": (num(r.get("outstanding_amt")) or 0) * 1e6,
                  "infl": (num(r.get("inflation_adj_amt")) or 0) * 1e6,
                  "maturity": r.get("maturity_date"),
                  "pays": [p for p in pays if p and re.match(r"^\d\d/\d\d$", p)]}
    return rd, out


# ------------------------------------------------------------- others
def ofr(mnemonic, start):
    d = jget(f"https://data.financialresearch.gov/v1/series/timeseries?mnemonic={mnemonic}"
             f"&start_date={start}")
    return {r[0]: r[1] for r in d if isinstance(r, list) and len(r) == 2 and r[1] is not None}


FEEDS = [("Liberty Street Economics", "https://libertystreeteconomics.newyorkfed.org/feed/"),
         ("NY Fed Teller Window", "https://tellerwindow.newyorkfed.org/feed/"),
         ("Federal Reserve speeches", "https://www.federalreserve.gov/feeds/speeches.xml"),
         ("Federal Reserve FEDS notes", "https://www.federalreserve.gov/feeds/feds_notes.xml")]
FEED_WORDS = re.compile(r"\brepo|\breserves\b|money market|funding market|liquidity|balance sheet|"
                        r"\bSOFR\b|Treasury market|\bT-bills?\b|standing repo|overnight rate|"
                        r"plumbing|\bSOMA\b|ample", re.I)


STRONG_WORDS = re.compile(r"\brepo\b|repurchase agreement|\bSOFR\b|money market fund|standing repo|"
                          r"ample reserves|reserve balances", re.I)


def research_feed():
    """Recent Fed research and speeches that touch funding markets."""
    items = []
    for name, url in FEEDS:
        try:
            xml = get(url, "application/rss+xml, application/xml, text/xml")
        except Exception as e:  # noqa: BLE001
            note(f"{name} feed: {e}")
            continue
        for it in re.findall(r"<item\b.*?</item>", xml, re.S)[:40]:
            def tag(t):
                m = re.search(r"<" + t + r"[^>]*>(.*?)</" + t + ">", it, re.S)
                v = m.group(1) if m else ""
                v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", v, flags=re.S)
                return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(v)))).strip()
            title, link, desc, pub = tag("title"), tag("link"), tag("description"), tag("pubDate")
            if not title or not (FEED_WORDS.search(title) or STRONG_WORDS.search(desc[:400])):
                continue
            try:
                d = datetime.strptime(pub[:16].strip(), "%a, %d %b %Y").date()
            except ValueError:
                d = None
            items.append({"date": d2s(d) if d else "", "source": name, "title": title,
                          "url": link, "summary": desc[:260]})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:14]


def gdp():
    d = jget("https://api.db.nomics.world/v22/series/BEA/NIPA-T10105/A191RC-Q?observations=1")
    s = d["series"]["docs"][0]
    out = {}
    for p, v in zip(s["period"], s["value"]):
        m = re.match(r"(\d{4})-Q([1-4])", p)
        if m and isinstance(v, (int, float)):
            out[f"{m.group(1)}-Q{m.group(2)}"] = round(v / 1000, 1)     # $m SAAR -> $bn
    return out


def h41_parse(html):
    """Reserve balances (Wednesday level, week average) and total factors
    supplying reserve funds from an H.4.1 release page. $bn."""
    t = re.search(r"H\.4\.1\s*-\s*([A-Z][a-z]+ \d{1,2}, \d{4})", html)
    if not t:
        return None
    rel = datetime.strptime(t.group(1), "%B %d, %Y").date()
    wed = rel - timedelta(days=(rel.weekday() - 2) % 7)

    def row(label):
        m = re.search(r'id="(t\d+r\d+)c1"[^>]*>(?:(?!</td>).)*?' + re.escape(label), html, re.S)
        if not m:
            return None
        rid = m.group(1)
        vals = []
        for c in (2, 3, 4, 5):
            cm = re.search(r'id="' + rid + f'c{c}"[^>]*>(.*?)</td>', html, re.S)
            if not cm:
                vals.append(None)
                continue
            txt = re.sub(r"<[^>]+>", "", cm.group(1)).replace("&#xa0;", "").replace("&nbsp;", "")
            txt = re.sub(r"\s+", "", txt)
            neg = txt.startswith("-")
            v = num(txt.lstrip("+-"))
            vals.append(None if v is None else (-v if neg else v))
        return vals
    res = row("Reserve balances with Federal Reserve Banks")
    sup = row("Total factors supplying reserve funds")
    if not res or res[0] is None:
        return None
    return {"wed": d2s(wed), "res_avg": round(res[0] / 1000, 1),
            "res_wed": round(res[3] / 1000, 1) if res[3] is not None else None,
            "supply_wed": round(sup[3] / 1000, 1) if sup and sup[3] is not None else None}


def h41(store, today):
    have = store.setdefault("h41", {})
    try:
        r = h41_parse(get("https://www.federalreserve.gov/releases/h41/current/default.htm",
                          "text/html"))
        if r:
            have[r["wed"]] = r
    except Exception as e:  # noqa: BLE001
        note(f"H.4.1 current: {e}")
    tried = 0
    start = today - timedelta(days=HISTORY_DAYS)
    wed = today - timedelta(days=(today.weekday() - 2) % 7)
    while wed >= start and tried < H41_PER_RUN:
        if d2s(wed) not in have and d2s(wed) not in store.setdefault("h41_missing", {}):
            for lag in (1, 2):                  # released Thursday, Friday after a holiday
                rel = wed + timedelta(days=lag)
                if rel > today:
                    continue
                tried += 1
                try:
                    r = h41_parse(get(f"https://www.federalreserve.gov/releases/h41/"
                                      f"{rel.strftime('%Y%m%d')}/", "text/html"))
                except Exception:  # noqa: BLE001
                    r = None
                if r and r["wed"] == d2s(wed):
                    have[r["wed"]] = r
                    break
            else:
                if wed < today - timedelta(days=10):
                    store["h41_missing"][d2s(wed)] = 1
        wed -= timedelta(days=7)


# ------------------------------------------------------------- issuance
def sec_key(a):
    """Which recurring security an auction belongs to."""
    t = a["type"].lower()
    if t == "bill" or a["type"] == "CMB":
        return "BILL " + a["term"] if not a["cmb"] else None
    kind = "TIPS" if a["tips"] else ("FRN" if a["frn"] else a["type"])
    return f"{kind} {a['oterm']}"


def month_end(y, m):
    return date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def next_year_slot(d0, mat):
    """Where last year's coupon settlement falls this year. Coupons settle on
    their maturity day of the month (the 15th, or month end) moved to the next
    business day, so the rule is applied afresh rather than copying a date that
    was itself shifted by a weekend (15 Nov 2025 was a Saturday)."""
    y = d0.year + 1
    # which nominal day produced last year's date?
    for back in range(0, 5):
        n = d0 - timedelta(days=back)
        if n.month != d0.month and back:
            # e.g. 2 Nov settling a 31 Oct month-end issue. Not only month-end maturities:
            # the 20-year bond (maturing on the 15th) settled 1 Dec 2025 because 30 Nov was
            # a Sunday, and belongs on 30 Nov 2026, not 1 Dec
            if n == month_end(n.year, n.month):
                return next_bd(month_end(y, n.month))
            break
        if n.day == mat.day or (mat.day >= 28 and n == month_end(n.year, n.month)):
            if next_bd(n) == d0:
                if mat.day >= 28 and n == month_end(n.year, n.month):
                    return next_bd(month_end(y, n.month))
                return next_bd(date(y, n.month, min(n.day, month_end(y, n.month).day)))
    try:
        return next_bd(d0.replace(year=y))
    except ValueError:
        return next_bd(d0 + timedelta(days=365))


def project(hist, ann, today, until):
    """Auctions not yet announced, settling between today and `until`."""
    known = hist + ann
    by = {}
    for a in known:
        k = sec_key(a)
        if k and a["issue"] and a["offer"]:
            by.setdefault(k, []).append(a)
    for k in by:
        by[k].sort(key=lambda a: a["issue"])
    proj = []
    for k, xs in by.items():
        lastx = xs[-1]
        li = s2d(lastx["issue"])
        if li < today - timedelta(days=60):
            continue                            # discontinued
        if k.startswith("BILL"):
            if len(xs) < 2:
                continue
            gaps = sorted((s2d(xs[i]["issue"]) - s2d(xs[i - 1]["issue"])).days
                          for i in range(max(1, len(xs) - 6), len(xs)))
            step = 28 if gaps[len(gaps) // 2] >= 21 else 7
            tenor = (s2d(lastx["maturity"]) - li).days
            nominal = li                        # the regular weekday, before holiday shifts
            if li.weekday() not in (1, 3) and len(xs) > 2:
                nominal = li - timedelta(days=1)
            n = 1
            while True:
                nd = nominal + timedelta(days=step * n)
                if nd > until:
                    break
                iss = next_bd(nd)
                if iss > s2d(lastx["issue"]):
                    proj.append({"key": k, "type": "Bill", "issue": d2s(iss),
                                 # bills mature on the regular weekday even when a
                                 # holiday pushed the issue back a day
                                 "maturity": d2s(next_bd(nd + timedelta(days=tenor))),
                                 "offer": lastx["offer"], "projected": True})
                n += 1
        else:
            # coupons: last year's calendar, latest size of the same kind
            size_new = next((a["offer"] for a in reversed(xs) if not a["reopen"]), lastx["offer"])
            size_re = next((a["offer"] for a in reversed(xs) if a["reopen"]), size_new)
            # Treasury sometimes moves a reopening off month end: from June 2026 the 20-year
            # reopenings settled two or three days after the auction (22 Jun, 24 Jul, 18 Sep,
            # 23 Oct) where they used to settle at month end. When the latest two reopenings
            # both settled well before their month end, a projected reopening settles two
            # business days after last year's auction week, not on last year's settlement day.
            recent_re = [s2d(b["issue"]) for b in xs if b["reopen"]][-2:]
            mid_month = len(recent_re) == 2 and all((month_end(x.year, x.month) - x).days >= 4
                                                    for x in recent_re)
            for a in xs:
                d0 = s2d(a["issue"])
                iss = next_year_slot(d0, s2d(a["maturity"]))
                at_month_end = (month_end(d0.year, d0.month) - d0).days <= 1 or d0.day <= 3
                if mid_month and a["reopen"] and a.get("auction") and at_month_end:
                    iss = s2d(a["auction"]) + timedelta(days=364)    # same weekday next year
                    for _ in range(2):
                        iss = next_bd(iss + timedelta(days=1))
                if not (today < iss <= until) or iss <= s2d(lastx["issue"]):
                    continue
                ref = size_re if a["reopen"] else size_new
                if any(abs((s2d(b["issue"]) - iss).days) <= 10 and (not ref or not b.get("offer") or b["offer"] >= 0.6 * ref)
                       for b in xs if b.get("announced")):
                    continue
                # already auctioned this year near that date: Treasury moved it. In 2026 the
                # 20-year reopening settled 23 Oct and the 5-year TIPS 30 Oct, where last
                # year's calendar said 2 Nov - both were counted twice until 26 Oct 2026
                if any(abs((s2d(b["issue"]) - iss).days) <= 12 and bool(b["reopen"]) == bool(a["reopen"])
                       for b in xs):
                    continue
                try:
                    mat = s2d(a["maturity"]).replace(year=s2d(a["maturity"]).year + 1)
                except ValueError:
                    mat = s2d(a["maturity"]) + timedelta(days=365)
                proj.append({"key": k, "type": a["type"], "issue": d2s(iss),
                             "maturity": d2s(mat), "offer": size_re if a["reopen"] else size_new,
                             "projected": True, "reopen": a["reopen"]})
    return proj


def interest_by_date(ms, soma, frn_rate, start, until):
    """Coupon interest paid to the public, $, by payment date."""
    out = {}
    for c, s in ms.items():
        cls = s["cls"].lower()
        if not s["pays"] or s["rate"] is None and "floating" not in cls:
            continue
        if "bill" in cls:
            continue
        par = max(s["out"] - soma.get(c, 0.0), 0.0)
        if par <= 0:
            continue
        if "floating" in cls:
            per = par * (frn_rate or 0) / 100 / 4
        elif "inflation" in cls:
            # the inflation uplift is on the whole issue; only the public's share counts
            per = par * (1 + s["infl"] / s["out"]) * s["rate"] / 100 / 2
        else:
            per = par * s["rate"] / 100 / len(s["pays"]) if len(s["pays"]) > 2 else par * s["rate"] / 100 / 2
        try:
            mat = s2d(s["maturity"])
        except Exception:  # noqa: BLE001
            mat = None
        for y in range(start.year, until.year + 1):
            for p in s["pays"]:
                mm, dd = int(p[:2]), int(p[3:])
                try:
                    d = date(y, mm, dd)
                except ValueError:              # e.g. 02/29 in a non-leap year
                    d = date(y, mm, 28)
                # month-end payers pay on the last day of short months too
                if dd >= 28 and mat is not None and mat.day >= 28:
                    nx = date(y + (mm == 12), mm % 12 + 1, 1)
                    d = nx - timedelta(days=1)
                if mat is not None and d > mat:
                    continue
                pd = next_bd(d)
                if start <= pd <= until:
                    out[d2s(pd)] = out.get(d2s(pd), 0.0) + per
    return out


def fix_flags(hist, ann):
    """TreasuryDirect's list of announced auctions sometimes drops the TIPS flag, so
    an October 5-year TIPS ($26bn, settling 30 Oct) arrived as a plain "Note
    5-Year". Taken as the nominal 5-year, it then stood in for the real one ($70bn,
    settling 2 Nov), which went missing from the projection. An announced coupon is
    marked TIPS when the auction history has TIPS of that term at about its size and
    the nominal series of that term is far bigger."""
    for a in ann:
        if a.get("tips") or a.get("frn") or (a["type"] or "").lower() == "bill" or not a.get("offer"):
            continue
        same = [h for h in hist if h["oterm"] == a["oterm"] and h.get("offer")]
        tips = [h["offer"] for h in same if h["tips"]][-4:]
        nom = [h["offer"] for h in same if not h["tips"] and not h["frn"]][-4:]
        if tips and nom:
            t, n = sum(tips) / len(tips), sum(nom) / len(nom)
            if abs(a["offer"] - t) <= 0.35 * t and a["offer"] < 0.6 * n:
                a["tips"] = True
    return ann


def issuance(hist, ann, ms, soma, today, mspd_date=None):
    ann = fix_flags(hist, ann)
    start = today - timedelta(days=HISTORY_DAYS)
    until = today + timedelta(days=AHEAD_DAYS)
    announced_cusips = {(a["cusip"], a["issue"]) for a in ann}
    hist = [a for a in hist if (a["cusip"], a["issue"]) not in announced_cusips]
    ann_future = [a for a in ann if a["issue"] and s2d(a["issue"]) >= today]
    hist_future = [a for a in hist if a["issue"] and s2d(a["issue"]) >= today]  # auctioned, not settled
    proj = project(hist, ann, today, until)
    days = {}

    def add(day, k, v):
        r = days.setdefault(day, {"bills": 0.0, "bills_mat": 0.0, "cpn": 0.0, "cpn_mat": 0.0,
                                  "interest": 0.0, "status": "actual"})
        r[k] += v
        return r

    # gross public issuance
    for a in hist + ann_future + proj:
        if not a.get("issue") or not a.get("offer"):
            continue
        d = s2d(a["issue"])
        if not (start <= d <= until):
            continue
        bill = a["type"].lower() in ("bill", "cmb")
        r = add(a["issue"], "bills" if bill else "cpn", a["offer"])
        if a.get("projected"):
            r["status"] = "projected"
        elif d >= today and r["status"] != "projected":
            r["status"] = "announced"

    # maturities: outstanding less SOMA, by CUSIP
    # Treasury's results data lags by about a week: an auction that has settled can still
    # have no accepted amount (the 6-week bill of 22 Oct 2026 went missing from 3 Dec's
    # maturities that way, overstating that day by $95bn). Until the result arrives, the
    # offered amount stands in - the same basis the issuance side already uses.
    outst = {}
    for a in hist:
        amt = a["accepted"] or a.get("offer")
        if amt:
            outst.setdefault(a["cusip"], {"amt": 0.0, "maturity": a["maturity"],
                                          "bill": a["type"].lower() in ("bill", "cmb"),
                                          "soma_at_auction": 0.0})
            outst[a["cusip"]]["amt"] += amt
            outst[a["cusip"]]["soma_at_auction"] += a["soma"] or 0.0
    for c, o in outst.items():
        d = s2d(o["maturity"])
        if not (start <= d <= until):
            continue
        # bills: every auction of the CUSIP (a 13-week reopens a 26-week). Coupons:
        # the month-end debt statement (net of buybacks) plus reopenings since
        amt = o["amt"]
        if not o["bill"] and c in ms and ms[c]["out"] and mspd_date:
            amt = ms[c]["out"] + sum(a["accepted"] or 0 for a in hist
                                     if a["cusip"] == c and a["issue"] > mspd_date)
        held = soma.get(c, o["soma_at_auction"]) if d >= today - timedelta(days=7) else o["soma_at_auction"]
        add(d2s(next_bd(d)), "bills_mat" if o["bill"] else "cpn_mat", max(amt - held, 0.0))
    # announced and projected issues add to what matures later; an announced
    # reopening's earlier tranches are already counted under its CUSIP above
    for a in proj + ann_future:
        if a.get("maturity") and a.get("offer") and s2d(a["maturity"]) <= until:
            bill = a["type"].lower() in ("bill", "cmb")
            add(d2s(next_bd(s2d(a["maturity"]))), "bills_mat" if bill else "cpn_mat", a["offer"])

    # Treasury's own estimate of the publicly held amount maturing replaces
    # ours wherever an auction states it (it knows the Fed's holdings that day)
    stated = {}
    for a in hist + ann_future:
        if a.get("pubmat") and a.get("issue"):
            bill = a["type"].lower() in ("bill", "cmb")
            k = (a["issue"], "bills_mat" if bill else "cpn_mat")
            stated[k] = max(stated.get(k, 0.0), a["pubmat"])
    for (day, k), v in stated.items():
        if day in days and start <= s2d(day) <= until:
            days[day][k] = v

    # coupon interest to the public
    frn = next((a["hir"] for a in reversed(hist) if a["term"] == "13-Week" and a["hir"]), 4.0)
    frn_spread = next((a["spread"] for a in reversed(hist) if a["frn"] and a["spread"] is not None), 0.1)
    for day, v in interest_by_date(ms, soma, frn + (frn_spread or 0), start, until).items():
        add(day, "interest", v)

    rows = []
    for day in sorted(days):
        r = days[day]
        if s2d(day) >= today and r["status"] == "actual":
            r["status"] = "projected" if any(p["issue"] == day for p in proj) else "announced"
        net = r["bills"] - r["bills_mat"] + r["cpn"] - r["cpn_mat"] - r["interest"]
        rows.append([day, round((r["bills"] - r["bills_mat"]) / 1e9, 2),
                     round((r["cpn"] - r["cpn_mat"]) / 1e9, 2), round(-r["interest"] / 1e9, 2),
                     round(net / 1e9, 2), {"actual": "A", "announced": "N"}.get(r["status"], "P"),
                     round(r["bills"] / 1e9, 1), round(r["bills_mat"] / 1e9, 1),
                     round(r["cpn"] / 1e9, 1), round(r["cpn_mat"] / 1e9, 1)])
    return {"cols": ["date", "bills_net", "coupons_net", "interest", "net", "status",
                     "bills_gross", "bills_maturing", "coupons_gross", "coupons_maturing"],
            "rows": rows,
            "announced": [[a["issue"], ("TIPS" if a["tips"] else "FRN" if a["frn"] else a["type"]),
                           a["term"], round(a["offer"] / 1e9, 1)]
                          for a in sorted(ann_future + hist_future, key=lambda a: a["issue"])
                          if a.get("offer")],
            "projected": [[p["issue"], p["key"], round(p["offer"] / 1e9, 1)]
                          for p in sorted(proj, key=lambda p: p["issue"])]}


# ------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    if "--dump" in args:
        MODE["dump"] = args[args.index("--dump") + 1]
    if "--cache" in args:
        MODE["cache"] = args[args.index("--cache") + 1]
    now = datetime.now(timezone.utc)
    today = now.date()
    if "--today" in args:
        today = s2d(args[args.index("--today") + 1])
    try:
        store = json.load(open(STORE))
    except Exception:  # noqa: BLE001
        store = {}
    if not ("--force" in args or MODE["dump"] or MODE["cache"]):
        last = store.get("built")
        ist = now.astimezone(IST)
        last_ist = (datetime.fromisoformat(last.replace("Z", "+00:00")).astimezone(IST)
                    if last else None)
        # the latest slot that has already passed, today or yesterday
        slots = [ist.replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(days=back)
                 for back in (0, 1) for h, m in RUN_SLOTS_IST]
        passed = max(t for t in slots if t <= ist)
        due = last_ist is None or last_ist < passed
        if last and store.get("version") == VERSION and not due:
            print("repo: already updated since the last slot (19:00 and 23:45 IST), skipping")
            return
    start = d2s(today - timedelta(days=HISTORY_DAYS))

    daily = nyfed_rates(start, d2s(today))
    nyfed_ops(daily)
    try:
        for k, v in tga(start).items():
            daily.setdefault(k, {})["tga"] = v
    except Exception as e:  # noqa: BLE001
        note(f"TGA: {e}")
    for mn, key in (("REPO-GCF_AR_T-P", "gcf"), ("REPO-DVP_AR_OO-P", "dvp")):
        try:
            for k, v in ofr(mn, start).items():
                daily.setdefault(k, {})[key] = v
        except Exception as e:  # noqa: BLE001
            note(f"OFR {mn}: {e}")
    for k, row in daily.items():
        if "thi" in row:
            row["iorb"] = round(row["thi"] - 0.10, 2)
    # carry the policy rates over days EFFR has not printed yet
    keep = {}
    for k in sorted(daily):
        for f in ("tlo", "thi", "iorb", "rrp_rate"):
            if f in daily[k]:
                keep[f] = daily[k][f]
            elif f in keep and ("sofr" in daily[k] or "tga" in daily[k]):
                daily[k][f] = keep[f]

    h41(store, today)
    try:
        g = gdp()
    except Exception as e:  # noqa: BLE001
        note(f"GDP: {e}")
        g = store.get("gdp", {})
    store["gdp"] = g

    iss = None
    try:
        hist = auctions(start)
        try:
            added, filled = merge_recent(hist, td_recent())
            print(f"repo: TreasuryDirect added {added} auctions, filled {filled} results")
        except Exception as e:  # noqa: BLE001
            note(f"TreasuryDirect auctioned: {e}")
        try:
            ann = upcoming()
        except Exception as e:  # noqa: BLE001
            note(f"TreasuryDirect upcoming: {e}")
            ann = []
        try:
            soma_asof, soma = soma_holdings()
        except Exception as e:  # noqa: BLE001
            note(f"SOMA: {e}")
            soma_asof, soma = None, {}
        try:
            ms_date, ms = mspd()
        except Exception as e:  # noqa: BLE001
            note(f"MSPD: {e}")
            ms_date, ms = None, {}
        iss = issuance(hist, ann, ms, soma, today, ms_date)
        iss["soma_asof"], iss["mspd_asof"] = soma_asof, ms_date
    except Exception as e:  # noqa: BLE001
        note(f"issuance: {e}")
        iss = store.get("issuance")
    store["issuance"] = iss

    fields = ["sofr", "sofr_p1", "sofr_p25", "sofr_p75", "sofr_p99", "sofr_vol",
              "tgcr", "tgcr_p1", "tgcr_p25", "tgcr_p75", "tgcr_p99", "tgcr_vol",
              "bgcr", "bgcr_p1", "bgcr_p25", "bgcr_p75", "bgcr_p99", "bgcr_vol",
              "effr", "effr_p1", "effr_p25", "effr_p75", "effr_p99", "effr_vol",
              "obfr", "obfr_vol", "tlo", "thi", "iorb", "rrp_rate", "rrp_amt", "rrp_cpty",
              "srf_amt", "srf_rate", "tga", "gcf", "dvp"]
    days = sorted(k for k in daily if k >= start and k <= d2s(today) and is_bd(s2d(k)))
    # end on the last day anything was published (today's rates print tomorrow)
    while days and all(daily[days[-1]].get(f) is None for f in ("sofr", "effr", "tga", "rrp_amt")):
        days.pop()
    cols = {f: [daily[k].get(f) for k in days] for f in fields}
    weeks = sorted(store["h41"])
    weekly = {"dates": weeks,
              "res_wed": [store["h41"][w].get("res_wed") for w in weeks],
              "res_avg": [store["h41"][w].get("res_avg") for w in weeks],
              "supply_wed": [store["h41"][w].get("supply_wed") for w in weeks]}
    built = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    store["built"] = built
    store["version"] = VERSION
    try:
        views = json.load(open(os.path.join(HERE, "repo_views.json")))
    except Exception as e:  # noqa: BLE001
        note(f"views file: {e}")
        views = None
    try:
        feed = research_feed()
    except Exception as e:  # noqa: BLE001
        note(f"research feed: {e}")
        feed = []
    payload = {"built": built, "daily": {"dates": days, **cols}, "weekly": weekly,
               "gdp": g, "issuance": iss, "views": views, "feed": feed, "health": health}
    if not MODE["cache"]:
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        json.dump(store, open(STORE, "w"), separators=(",", ":"))
    out = OUT if not MODE["cache"] else os.path.join(MODE["cache"], "repo.js")
    with open(out, "w") as f:
        f.write("window.REPO = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(f"repo: {len(days)} days, {len(weeks)} weeks, "
          f"{len(iss['rows']) if iss else 0} issuance days, {health['requests']} requests, "
          f"errors: {health['errors'] or 'none'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("repo failed:", e, file=sys.stderr)
    sys.exit(0)
