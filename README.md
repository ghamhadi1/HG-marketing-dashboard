# HG – Marketing Performance Dashboard (Project 1)

**Live dashboard:** https://ghamhadi1.github.io/HG-marketing-dashboard/

A one-page dashboard that tells the agency owner which lead sources deserve next month's budget. Data comes from the GoHighLevel sandbox through its API.

## How it works

```
GoHighLevel API ──> fetch_data.py ──> build_data.py ──> site/index.html ──> GitHub Pages (live link)
   (read-only)      downloads raw      cleans, counts,     one self-contained
                    records            builds the page     page, no key inside
```

1. **`fetch_data.py`** calls three GoHighLevel endpoints (read-only, nothing in the sandbox is created or changed):
   - `GET /opportunities/pipelines` – the pipelines and their stage names
   - `GET /opportunities/search` – every deal in "Sales Pipeline"
   - `POST /contacts/search` – every contact in the location
2. **`build_data.py`** decides which records belong to the agency, removes the bad ones, counts everything per source and writes the numbers into `dashboard_template.html` to produce `site/index.html`.
3. **`.github/workflows/refresh.yml`** runs both scripts on GitHub's servers every day at 03:00 UTC (and on demand) and publishes `site/` to GitHub Pages.

The API key lives only in GitHub's encrypted Secrets (hosted) or in a `.env` file one folder above this one (local). The published page contains only finished totals: no key, no location ID, no contact names, emails or phone numbers.

## Decisions (one line each)

**Scope – which records are the agency's**
- Only the pipeline named "Sales Pipeline": it is the only one of the 5 pipelines with exactly 8 stages; the others belong to other students.
- Only contacts tagged `dash-project`: all 321 share that tag, the same import date (4 Sep 2026) and the same data shape; the other 48 contacts are other students' tests.
- 32 deals in the same pipeline were excluded: their contacts are tagged `demo-data`/`sandbox`, were created on a different day (1 Sep), and all sit in Disqualified with contradicting statuses (4 say "won").

**Cleaning – what was removed (shown to the owner at the bottom of the page)**
- 15 internal leads removed: tagged `internal`, all from Website Form, none has a deal; keeping them would inflate the website's lead count by 52%.
- 12 duplicates removed: same name + same company, email ending in `.2`, created minutes after the original, no deal; the original is kept.
- Duplicates are matched on name+company OR email (ignoring `.2` / `+tag` suffixes); the copy that owns a deal wins, otherwise the oldest.
- The duplicate's source is ignored: 11 of 12 copies carried a different source than the original and would have credited the wrong channel.
- Missing sources: none found in the agency's records, but the code puts any future one in an "Unknown source" bar rather than dropping it.

**Suspicious values – kept as records, held out of revenue**
- 6 deals are recorded at $145,000 while every other deal is $1,500–$12,000; anything above 5× the median deal is treated as a typing mistake.
- Only 2 of those 6 are Closed, so only those 2 affect revenue (Facebook Ad, Instagram Ad); the page lists them for the owner to confirm.
- Those deals still count as leads and as sales (the sale happened); only the amount is held back.
- 1 Closed deal has $0 (Webinar): counted as a sale, adds $0, listed for the owner to fill in.
- A source is never put in "Pull back" while it has an amount waiting to be confirmed (Facebook Ad).

**Metrics**
- Lead volume = cleaned contacts, not deals: 90 real leads never got a deal, and they still cost money to acquire.
- Those 90 appear as "Not in the pipeline yet", so each stacked bar adds up to that source's lead count (consistency rule).
- The build stops with an error instead of publishing if any source's stages do not add up to its lead count.
- The stage of a deal is trusted, not its status field: two Disqualified deals still say "open".
- Revenue = deals in the Closed stage only; amounts on open or lost deals are hopes, not money.
- GHL only stores a deal's current stage, so conversion uses "reached this step or beyond": Leads → Opted in → Qualified → Call booked → Call happened → Sale closed.
- "Call happened" = Closed + Follow Up + Lost; Cancelled, No Show and still-upcoming calls are not counted.
- No dates are used: every record carries the same import date, so a monthly trend would be invented.
- No blended totals anywhere in the charts; the only overall numbers are record counts in the "what was left out" section.

**Budget advice**
- No ad spend exists, so sources are ranked by confirmed revenue per lead.
- "Put more in" = at least 25% above the median source and at least 2 sales; "Pull back" = 40% or more below the median; otherwise "Keep the same".
- The page says plainly that sales counts are small (1–5 per source) so the advice is a direction, not proof.

**Charts**
- Volume: horizontal bar chart, one colour, sorted, so nine source names stay readable.
- Pipeline: stacked bar per source, all the same width, so sources of different sizes can be compared stage by stage.
- Conversion: one small funnel per source, sorted best first; a single funnel would have been a blended number.
- Revenue: bar chart sorted high to low, with the number of sales next to each bar.
- Every chart has a "See the numbers" table underneath; hovering a bar shows its value.
- Colours come from a colour-blind-safe palette; the page follows the viewer's light/dark setting.

**Tech and hosting**
- Plain Python (no packages) + one HTML file (no libraries): nothing to install, nothing to break.
- Scheduled daily refresh instead of live: the owner looks once a week, a pre-built page loads instantly, and the key never needs to be near a browser.
- GitHub Pages + GitHub Actions: free, gives a public link, stores the key encrypted, and has a "Run workflow" button for a manual refresh.
- "Updated" on the page is the time the records were downloaded, not the time the page was built, so stale data cannot look fresh.
- Raw downloads are saved outside this folder so they cannot be uploaded by accident.

## Run it on your own computer

```
python fetch_data.py
python build_data.py
```
Then open `site/index.html`. Needs a `.env` file one folder above with `GHL_API_KEY=` and `GHL_LOCATION_ID=`.

## Put it online (one time, about 10 minutes)

1. Create a free account on github.com, then **New repository** → name `HG-marketing-dashboard` → **Public** → Create.
2. **Add file → Upload files** → drag in `fetch_data.py`, `build_data.py`, `dashboard_template.html`, `README.md` → Commit.
3. **Add file → Create new file** → name it `.github/workflows/refresh.yml` → paste the content of that file → Commit.
4. **Settings → Secrets and variables → Actions → New repository secret**: add `GHL_API_KEY` and `GHL_LOCATION_ID`.
5. **Settings → Pages → Source: GitHub Actions**.
6. **Actions → Refresh dashboard → Run workflow**. After about a minute the link appears at Settings → Pages.
