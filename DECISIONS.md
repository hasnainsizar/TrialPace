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
- **Sponsor grouping is two-stage.** Direct groups match when the lead sponsor name starts with a configured prefix (edwards, medtronic, boston scientific, abbott) and get `mapped_via = direct`. A parent map is then checked anywhere in the name for affiliates and acquisitions. Prefix matching for the direct stage stops the affiliate rule from being swallowed by the direct rule, since "JC Medical, Inc., an affiliate of Edwards Lifesciences LLC" contains "edwards" but does not start with it. Names matching nothing go to Other with `mapped_via = none`. The original name is kept in `lead_sponsor_raw` and exported as `sponsor_name`; the grouped name is `sponsor_group`.
- **Names mapped in the 2026-09-21 snapshot:**

  | Registry name | Sponsor group | Mapped via |
  |---|---|---|
  | Edwards Lifesciences | Edwards Lifesciences | direct |
  | JC Medical, Inc., an affiliate of Edwards Lifesciences LLC | Edwards Lifesciences | affiliate |
  | Medtronic Cardiovascular | Medtronic | direct |
  | Medtronic Cardiac Rhythm and Heart Failure | Medtronic | direct |
  | Boston Scientific Corporation | Boston Scientific | direct |
  | Symetis SA | Boston Scientific | acquisition (2017) |
  | Abbott Medical Devices | Abbott | direct |

  The St. Jude Medical to Abbott rule (acquisition, 2017) is configured but matched no in-scope trial in this snapshot.

## Scope filters

- **Filters run at load, after parsing and before storage.** Only in-scope trials go into the `trials` and `sites` tables. Removed trials are recorded in `scope_exclusions` with the filter that removed them, and the per-step counts go in `filter_log`, so the narrowing is auditable without keeping every out-of-scope site.
- **Order is device, then transcatheter term, then industry.** A trial that fails several filters is counted against the first one. The counts therefore describe the funnel, not independent effects.
- **Device means any intervention of type DEVICE.** Trials that combine a device with a drug or procedure arm are kept.
- **Transcatheter terms and product names are one list for matching.** The generic terms (TAVR, TAVI, transcatheter) catch most trials; the product list catches trials titled only with a brand. Matching is case-insensitive substring, so short names like Lotus or Tiara could in principle match unrelated text. None did in the first run.
- **Industry filter uses the registry's lead sponsor class.** Trials where a company is a collaborator but a hospital is the lead sponsor are excluded. The flag `scope.industry_only` turns this off.
- **Changing the API field list invalidates the day's cache.** The manifest records the fields used; a mismatch triggers a refetch of that query. Needed because the scope filters required two fields the first version did not pull.

## Stale records

- **Stale is computed at load time and stored on the trial row.** The snapshot date is known then, and every downstream table (forecasts, dim_trial, Excel) inherits the flag without recomputing it. The cutoff is snapshot date minus `stale_after_months` x `days_per_month` days.
- **Twelve months is the default** because ClinicalTrials.gov asks sponsors to verify records at least once a year.
- **A missing last update date leaves the flag blank** rather than marking the trial stale. In practice the registry always supplies the date.
- **Stale trials are still forecast.** The flag is a caution on the status label, not an exclusion.
- **The original sponsor name travels as `sponsor_name`.** In dim_trial it sits next to the sponsor group; in the Excel sheets it is inserted after the sponsor column by joining on NCT ID, so the forecast and benchmark tables in SQLite stay narrow.
- **Schema changes rebuild the database.** The SQLite file is gitignored and fully derived from the cached raw JSON, so when the schema changes the file is deleted and `load` recreates it.

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
- **Four status labels.** Primary completion reached, Overdue, Behind forecast, On track. An earlier version had seven (separate At risk and Likely late bands, a Past forecast label, and a No posted date label); they were collapsed because the finer bands rested on a 90 and 365 day split that the backtest error could not support.
- **Status thresholds:** gap up to 90 days is On track, beyond that Behind forecast. A negative gap (forecast earlier than posted) is On track.
- **Overdue is checked before anything else.** If the sponsor's posted date is already behind the snapshot date and the trial is still active, comparing a forecast to that date is meaningless. The label says the record or the plan is out of date. A median forecast already behind the snapshot is checked second and is Behind forecast: an active trial whose estimate has passed was previously labelled On track whenever its posted date was also late, which hid the fact that the estimate had failed. Both checks use strict "before the snapshot date", so a date equal to the snapshot is not past. Gap days are still stored.
- **No posted date is On track.** With only four labels, a forecast trial without a posted date has nothing showing a delay, so it is On track unless its median estimate has already passed. None occur in the current snapshot.
- **Active trials with an ACTUAL primary completion date are not forecast.** The registry marks the date type ACTUAL once the milestone has happened, so the milestone has already happened regardless of the overall status still saying active. These trials get the label Primary completion reached, blank forecast columns, and `model = none`, and they never count as Overdue or Behind forecast. They stay in fact_forecast so the Active Trials count and the status matrix still show every active trial. Those meeting the benchmark rules join the benchmark set; the count that came from active statuses is reported in the CLI and METHOD.md.
- **Active not recruiting trials with an ESTIMATED primary completion date are still forecast.** Most have probably finished enrolling too, but the registry does not say so, and the forecast then serves as a check on the posted date.

## Models and selection

- **Three models, one cross-validation.** The per-site rate, a log-linear regression, and a naive valve-type median are scored on the same leave-one-out folds, so the comparison is fair.
- **Regression is plain least squares with numpy.** No scikit-learn dependency. Valve type enters as indicator columns with the alphabetically first type as the reference. The P25 and P75 come from the empirical residual quantiles, which keeps the range explainable.
- **Regression needs 20 benchmark rows to fit.** Set by `min_regression_rows`. Below that it reports "could not be fitted" rather than producing a degenerate fit.
- **Selection uses median absolute percentage error.** MAPE was ruled out because a few short trials dominate it. Ties go to the naive baseline. `forecast.model` can force a model.
- **The horizon cap applies to whichever model is selected**, and the count under each model is reported so the safety net stays visible even when the selected model cannot trip it.
- **The forecast command runs the comparison itself** so that it can pick a model without depending on `backtest` having run first. `backtest` repeats the same deterministic comparison, stores it, and renders METHOD.md.

## Backtest

- **Leave-one-out cross-validation replaced the single holdout split.** The first version held out 20% of benchmarks with a fixed seed. After the scope filters that left 11 holdout trials, and a seed sensitivity check showed the model ranking changed with the seed. Leave-one-out scores every benchmark trial exactly once per model, uses all 54 trials, and has no seed, so the seed sensitivity check was removed as redundant. The cost is one fit per trial per model, which is negligible at this size.
- **Error is measured in months, not days.** Both MAPE and median absolute percentage error are reported, because a few very short benchmark trials dominate the mean.
- **A benchmark set under 30 trials is flagged as thin** in the CLI output and METHOD.md. Set by `min_benchmarks_for_confidence`. Cross-validation uses every trial, but a handful of unusual ones can still move the ranking.
- **METHOD.md is generated.** The `backtest` command renders it from `trialpace/method_template.md` so the numbers in it always match the database. Editing the prose means editing the template.

## Outputs

- **dim_date spans every date in the exported tables.** Forecast P75 dates for slow trials push it several decades out. It is a plain calendar, so the row count is harmless in Power BI.
- **Empty tables still get a CSV with headers** so Power BI relationships do not break, and the command prints a note saying the table is empty. Excel sheets that would be empty get a single explanatory row instead of a blank grid.
- **The Excel Benchmark Rates sheet has two blocks:** the segment rate table at the top and the per-trial benchmark detail below it. The Data Quality sheet likewise has the scope filter funnel at the top and the missing-field issues below it.
- **fact_forecast carries `model` and `basis` columns** so a report can show which model produced each row and which segment or fallback it used.
- **No .env file.** The ClinicalTrials.gov API needs no key, so there are no secrets to hold.
