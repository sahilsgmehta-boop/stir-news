"""Past high-impact events for the dashboard's Event reaction page.

TradingView's public calendar, the same feed as calendar_feed.py, fetched
month by month for the last ~11 months: high-importance releases plus every
central-bank rate decision, with actual, forecast and previous so the page can
show the surprise. Rebuilt at most once a day. Never fails the run.
"""
import json, os, sys, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calendar_feed as cf  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "events_past.js")
BACK_DAYS = 335


def keep(e):
    t = (e.get("title") or "").lower()
    if e.get("allday"):
        return False
    if "rate decision" in t or "interest rate decision" in t or "deposit facility rate" in t or "bank rate" in t:
        return True
    return e.get("imp") == 1


def main():
    now = datetime.now(timezone.utc)
    # a fresh checkout resets file times, so the age comes from the "built" stamp inside
    if os.path.exists(OUT) and "--force" not in sys.argv:
        try:
            txt = open(OUT).read(200)
            b = datetime.strptime(txt.split('"built":"')[1][:20], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - b < timedelta(hours=20):
                print("events_past: fresh, skipped"); return
        except Exception:  # noqa: BLE001
            pass
    start = now - timedelta(days=BACK_DAYS)
    out, errs, a = {}, [], start
    while a < now:
        b = min(a + timedelta(days=30), now + timedelta(days=1))
        try:
            for e in cf.tradingview(a, b):
                if keep(e):
                    out[e["id"]] = e
        except Exception as ex:  # noqa: BLE001
            errs.append(f"{a:%Y-%m-%d}: {ex}"[:160])
        a = b
        time.sleep(1.5)
    if not out:
        print("events_past: nothing fetched; keeping the old file", errs); return
    ev = sorted(out.values(), key=lambda e: e["t"])
    payload = {"built": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "from": start.strftime("%Y-%m-%d"), "events": ev, "errors": errs}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("window.PAST_EVENTS = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n")
    print(f"events_past: {len(ev)} events, errors: {errs or 'none'}")


if __name__ == "__main__":
    import io, contextlib, traceback
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            main()
    except Exception:  # noqa: BLE001
        buf.write(traceback.format_exc())
    print(buf.getvalue())
    # a short status note next to the output, so a failure can be seen without the run log
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "events_past_status.txt"), "w") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ ") + buf.getvalue()[-1500:])
    except Exception:  # noqa: BLE001
        pass
    sys.exit(0)
