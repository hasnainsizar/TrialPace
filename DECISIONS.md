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

## Scope filters

- **Filters run at load, after parsing and before storage.** Only in-scope trials go into the `trials` and `sites` tables. Removed trials are recorded in `scope_exclusions` with the filter that removed them, and the per-step counts go in `filter_log`, so the narrowing is auditable without keeping every out-of-scope site.
- **Order is device, then transcatheter term, then industry.** A trial that fails several filters is counted against the first one. The counts therefore describe the funnel, not independent effects.
- **Device means any intervention of type DEVICE.** Trials that combine a device with a drug or procedure arm are kept.
- **Transcatheter terms and product names are one list for matching.** The generic terms (TAVR, TAVI, transcatheter) catch most trials; the product list catches trials titled only with a brand. Matching is case-insensitive substring, so short names like Lotus or Tiara could in principle match unrelated text. None did in the first run.
- **Industry filter uses the registry's lead sponsor class.** Trials where a company is a collaborator but a hospital is the lead sponsor are excluded. The flag `scope.industry_only` turns this off.
- **Changing the API field list invalidates the day's cache.** The manifest records the fields used; a mismatch triggers a refetch of that query. Needed because the scope filters required two fields the first version did not pull.

## Storage

- **Snapshot date defaults to today** for every command. `--date` overrides it so an older raw folder can be reloaded.
- **Derived tables are also keyed by snapshot date.** Benchmarks, rates, forecasts, and backtest results are stored per snapshot and replaced on rerun, same as the trial and site tables.
- **Forecast exclusions are stored.** Every active trial that could not be forecast has a reason row in `forecast_exclusions` so the count of forecast trials can be reconciled with the count of active trials.

## Forecast

- **Site count is the number of listed locations, whatever their status.** The registry does not reliably report when sites opened or closed.
- **Benchmark trials shorter than 3 months are excluded.** Set by `min_months`. A trial with a primary completion date under three months after its start is almost always a registry data artifact rather than a real enrollment period.
- **Benchmark trials need at least 5 listed sites.** Set by `min_benchmark_sites`. Single-site listings made the per-site rate meaningless. This is the largest single filter on the benchmark set: 27 of 81 candidates in the 2026-09-21 snapshot.
- **Active trials whose median forecast exceeds 240 months are excluded** with a reason. Set by `max_horizon_months`. Kept as a safety net. It is checked under every model and the counts are stored in `horizon_checks`; with the naive model selected it removes nothing, and the per-site rate model would still remove 20 trials.
- **Segments are valve type by size band.** Size bands are small (up to 100), medium (up to 500), large (above). A segment needs 5 benchmark trials to get its own rate; otherwise the overall rate is used. The rate source is recorded on every forecast row.
- **Fallback goes straight to the overall rate.** No intermediate fallback to valve type alone. Simpler to explain, and with the current data 9 of 10 possible segments already qualify.
- **P25 date uses the P75 rate.** Faster rates give earlier dates, so the optimistic end of the date range comes from the fast end of the rate distribution.
- **Status thresholds:** gap up to 90 days is On track, up to 365 days is At risk, beyond that Likely late. A negative gap (forecast earlier than posted) is On track.
- **Active not recruiting trials are forecast** as the brief specified, even though most have finished enrolling. METHOD.md explains how to read them.

## Models and selection

- **Three models, one shared split.** The per-site rate, a log-linear regression, and a naive valve-type median are all fitted on the same training rows and scored on the same holdout rows, so the comparison is fair.
- **Regression is plain least squares with numpy.** No scikit-learn dependency. Valve type enters as indicator columns with the alphabetically first type as the reference. The P25 and P75 come from the empirical residual quantiles, which keeps the range explainable.
- **Regression needs 20 benchmark rows to fit.** Set by `min_regression_rows`. Below that it reports "could not be fitted" rather than producing a degenerate fit.
- **Selection uses median absolute percentage error.** MAPE was ruled out because a few short trials dominate it. Ties go to the naive baseline. `forecast.model` can force a model.
- **The horizon cap applies to whichever model is selected**, and the count under each model is reported so the safety net stays visible even when the selected model cannot trip it.
- **Seed sensitivity is reported, not used for selection.** The brief asked for one fixed seed. With 11 holdout trials the ranking moves with the seed, so `backtest` also reruns the split with seeds 0 to 9 and reports how often each model wins. That number goes in METHOD.md so the reader can judge how settled the choice is.
- **The forecast command runs the comparison itself** so that it can pick a model without depending on `backtest` having run first. `backtest` repeats the same deterministic comparison, stores it, and renders METHOD.md.

## Backtest

- **Holdout is 20% with a fixed seed of 42.** Rates are rebuilt from the other 80% so the holdout is not scored against rates that included it.
- **Error is measured in months, not days.** Both MAPE and median absolute percentage error are reported, because a few very short benchmark trials dominate the mean.
- **A holdout under 20 trials is flagged as thin** in the CLI output and METHOD.md. Set by `min_holdout_for_confidence`.
- **METHOD.md is generated.** The `backtest` command renders it from `trialpace/method_template.md` so the numbers in it always match the database. Editing the prose means editing the template.

## Outputs

- **dim_date spans every date in the exported tables.** Forecast P75 dates for slow trials push it several decades out. It is a plain calendar, so the row count is harmless in Power BI.
- **Empty tables still get a CSV with headers** so Power BI relationships do not break, and the command prints a note saying the table is empty. Excel sheets that would be empty get a single explanatory row instead of a blank grid.
- **The Excel Benchmark Rates sheet has two blocks:** the segment rate table at the top and the per-trial benchmark detail below it. The Data Quality sheet likewise has the scope filter funnel at the top and the missing-field issues below it.
- **fact_forecast carries `model` and `basis` columns** so a report can show which model produced each row and which segment or fallback it used.
- **No .env file.** The ClinicalTrials.gov API needs no key, so there are no secrets to hold.
