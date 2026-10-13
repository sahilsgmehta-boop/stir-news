# stir-news

Central bank commentary for the STIR dashboard. Every 30 minutes GitHub runs
`collect.py`, which reads public news and central bank feeds, keeps what is about
the Fed, ECB, BoE, BoC and SNB, merges repeats, and publishes `docs/cb.js` on
GitHub Pages. The dashboard loads that file.

Nothing here needs your computer, Excel, or a password.

## Files

| File | What it is |
|---|---|
| `collect.py` | The collector. The `SOURCES` list near the top is where feeds are added or removed. |
| `.github/workflows/collect.yml` | The 30-minute schedule. |
| `docs/cb.js` | The output the dashboard reads. Written by the robot. |
| `docs/health.json` | Which sources worked on the last run, and how many items each gave. |
| `data/store.json` | Rolling 45-day history, so items survive feeds that only keep a few hours. |

## Is it working?

Open `https://<your-username>.github.io/stir-news/health.json`. Every source shows
`"ok": true` or an error. A source that keeps failing can simply be deleted from
`SOURCES` in `collect.py`.

The dashboard also warns on the page if the feed is more than three hours old.

## Hawk / dove labels

Not yet. The `tone` field is in place and empty; once the feed has proven itself
a labelling step will be added that fills it in, and the dashboard already shows
a speaker's lean once their comments carry labels.
