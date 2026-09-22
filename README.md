# Follow the Money: 2026 midterm spending tracker

A static page that shows where House and Senate general-election outside money is going, which party it helps, and whether each party is on offense or defense. It's built entirely from FEC filings and refreshed by GitHub Actions. Nobody runs it by hand.

## How it runs

`.github/workflows/refresh.yml` fires at :07 and :37 past each hour. `ftm/cadence.py` decides whether a given firing does any work, using the dates in `ftm/config.json` → `schedule`:

| Period | Cadence |
|---|---|
| Now to Oct 14 | Hourly |
| Oct 15 to Nov 3 | Every 30 min |
| Nov 4 to Dec 10 | Daily at 11:07 UTC |
| After Dec 10 | Frozen as a record (a manual run still works) |

Each working run: tests, then `python -m ftm.run`, then a commit of `site/` and `state/` if anything changed, then a Netlify deploy. A failed check exits non-zero before anything in `site/data` is written, so the last good data stays live and GitHub emails the failure. A daily `site/data/heartbeat.txt` commit keeps scheduled workflows from being disabled for inactivity.

## Data layers

| Layer | Source | Key needed | Refresh |
|---|---|---|---|
| 24/48-hour IE notices (backbone) | FEC bulk `independent_expenditure_2026.csv` | no | FEC updates daily at ~10 UTC; the whole cycle is rebuilt from scratch every run |
| Candidates, committees | FEC bulk `cn26.zip`, `cm26.zip` | no | every run |
| Seat holders | congress-legislators `legislators-current.json` | no | every run |
| Intraday notices and F3X items | OpenFEC `/schedules/schedule_e/efile/` (last 3 days) | **yes** | every run |
| Periodic-report Schedule E | OpenFEC `/schedules/schedule_e/` (`is_notice=false`) | **yes** | backfill resumes across runs, then nightly; cached in `state/` |
| Party coordinated (Schedule F) | OpenFEC `/schedules/schedule_f/` | **yes** | nightly; cached in `state/` |
| Primary calendar (efile general vs. primary) | OpenFEC `/election-dates/` | **yes** | nightly |

Without `FEC_API_KEY` the tracker still works, but only from the daily bulk notices. The page says so.

## Rules

- **Party helped:** support a Dem or oppose a Rep counts as pro-Dem, and the reverse as pro-Rep. Primaries, runoffs, other-cycle candidates (e.g. 2024 leftovers) and third-party candidates are dropped.
- **Committee class:** FEC type X/Y = party, O/U/V/W = super PAC, else other.
- **Dedupe:**
  1. A filing named as `prev_file_num` or `amends` is dropped wholesale.
  2. The same committee+file+transaction from two sources is kept once.
  3. A notice that matches a periodic item on committee, candidate, dissemination date, amount and payee is dropped in favor of the periodic copy.
- **Offense:** dollars helping a party in a seat the other party holds now. Seats flagged *holder uncertain* are excluded. That flag is set when redistricting moved the member (they filed in another district, or an FEC "incumbent" holds a different seat).
- **Guards:**
  - Single items ≥ $5M (House) or ≥ $25M (Senate) are held until processed data confirms them. This filing cycle already includes several $1B–$9B junk rows.
  - A blank candidate ID is recovered only on a unique last-name match within the race.
  - The build fails if more than 2% of dollars are unmatched or if the bulk file looks truncated.
  - Dissemination dates after today are pinned to today.
- **Alerts:** first $100K, first party-committee dollar and first $1M per race and party. They're dated by the data (`crossed_on`) and stamped with the run that first saw them (`detected_at`).

## Local

```bash
python3 -m unittest -v
python3 -m ftm.run            # writes site/data, state/, build/ftm.sqlite
python3 -m http.server 8765 --directory site
```

Standard library only; no dependencies.

## One-time setup (repo secrets / variables)

- `FEC_API_KEY` (secret): free from https://api.data.gov/signup/
- `NETLIFY_AUTH_TOKEN` (secret): Netlify → User settings → Applications → Personal access tokens
- `NETLIFY_SITE_ID` (variable): already set
