# Decisions

Choices made where the brief left room for interpretation, and why.

## Data pull

- **One API query per search item.** Each condition and each term is fetched separately and cached under its own folder. Results are deduplicated by NCT ID at load time. This makes the cache easy to inspect and lets a single failed query be retried without refetching the rest.
- **Study type and start date go in `filter.advanced`.** The v2 API expresses these as `AREA[StudyType]INTERVENTIONAL AND AREA[StartDate]RANGE[2010-01-01,MAX]`.
- **Cache marker is a manifest file.** A query is treated as complete for the day when `manifest.json` exists in its folder. A partial download (no manifest) is refetched from page one.
- **Page size 200.** Large enough to keep request counts low, well under the API's cap.

## Parsing

- **Partial dates snap to the first of the period.** Most registry dates are month precision (`2015-01`). They become the first of the month. Year-only dates become January 1. This is not recorded as a data quality issue because it would affect nearly every trial; it is described in METHOD.md instead.
- **Data quality records missing fields, not partial ones.** A field is flagged when it is absent, empty, or unparseable. Missing facility or country on individual sites is flagged per site.
- **Studies with no NCT ID are skipped and counted.** There is no way to store or dedupe them.
- **Valve type comes from keyword matching** on title, conditions, and interventions, with tricuspid checked before mitral before aortic so that a mitral trial mentioning prior TAVR is classed as mitral. Trials matching nothing are "other". The keywords live in config.yaml.
- **St. Jude Medical maps to Abbott.** Abbott acquired St. Jude in 2017 and the older mitral and tricuspid trials still carry the St. Jude name. The original name is kept in `lead_sponsor_raw`.

## Storage

- **Snapshot date defaults to today** for every command. `--date` overrides it so an older raw folder can be reloaded.
- **Derived tables are also keyed by snapshot date.** Benchmarks, rates, forecasts, and backtest results are stored per snapshot and replaced on rerun, same as the trial and site tables.
- **Forecast exclusions are stored.** Every active trial that could not be forecast has a reason row in `forecast_exclusions` so the count of forecast trials can be reconciled with the count of active trials.

## Forecast

- **Site count is the number of listed locations, whatever their status.** The registry does not reliably report when sites opened or closed.
- **Benchmark trials shorter than 3 months are excluded.** Set by `min_months`. A trial with a primary completion date under three months after its start is almost always a registry data artifact rather than a real enrollment period. This removed 12 trials in the first run.
- **Active trials whose median forecast exceeds 240 months are excluded** with a reason. Set by `max_horizon_months`. These are trials with a large target and one or two listed sites, where the real site list is clearly not on the registry. Before this cap a handful of trials had forecast dates in the 2400s and made the calendar table useless.
- **Segments are valve type by size band.** Size bands are small (up to 100), medium (up to 500), large (above). A segment needs 5 benchmark trials to get its own rate; otherwise the overall rate is used. The rate source is recorded on every forecast row.
- **Fallback goes straight to the overall rate.** No intermediate fallback to valve type alone. Simpler to explain, and with the current data 9 of 10 possible segments already qualify.
- **P25 date uses the P75 rate.** Faster rates give earlier dates, so the optimistic end of the date range comes from the fast end of the rate distribution.
- **Status thresholds:** gap up to 90 days is On track, up to 365 days is At risk, beyond that Likely late. A negative gap (forecast earlier than posted) is On track.
- **Active not recruiting trials are forecast** as the brief specified, even though most have finished enrolling. METHOD.md explains how to read them.

## Backtest

- **Holdout is 20% with a fixed seed of 42.** Rates are rebuilt from the other 80% so the holdout is not scored against rates that included it.
- **Error is measured in months, not days.** MAPE on duration. Both MAPE and median absolute percentage error are reported, because a few very short benchmark trials dominate the mean.
- **METHOD.md is generated.** The `backtest` command renders it from `trialpace/method_template.md` so the numbers in it always match the database. Editing the prose means editing the template.

## Outputs

- **dim_date spans every date in the exported tables.** Forecast P75 dates for slow trials push it several decades out. It is a plain calendar, so the row count is harmless in Power BI.
- **Empty tables still get a CSV with headers** so Power BI relationships do not break, and the command prints a note saying the table is empty. Excel sheets that would be empty get a single explanatory row instead of a blank grid.
- **The Excel Benchmark Rates sheet has two blocks:** the segment rate table at the top and the per-trial benchmark detail below it.
- **No .env file.** The ClinicalTrials.gov API needs no key, so there are no secrets to hold.
