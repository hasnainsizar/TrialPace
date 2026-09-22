# trialpace

Enrollment pace forecasts for structural heart device trials, built from public ClinicalTrials.gov data.

trialpace pulls interventional trials since 2010 for transcatheter aortic, mitral, and tricuspid valve therapy, narrows them to industry-sponsored device trials, works out how long comparable completed trials took, and estimates when each active trial will reach its enrollment target. The output is a set of CSV tables ready for Power BI and a formatted Excel workbook.

This project uses only the public ClinicalTrials.gov API. It is not affiliated with, endorsed by, or informed by Edwards Lifesciences, Medtronic, Boston Scientific, Abbott, or any other company named in the data.

## Why enrollment pace matters

A device trial cannot report results until it has enrolled enough patients. For a company like Edwards or Medtronic, the enrollment period decides when a new valve can be submitted for approval, when it reaches the market, and how long a competitor's head start lasts. Sponsors post a planned primary completion date on ClinicalTrials.gov, but those dates are often optimistic. Comparing the posted date to what similar trials actually achieved gives an outside view of which trials are on schedule and which are likely to slip.

## What it produces

- A SQLite database with a dated snapshot of every trial, every listed site, and every data quality problem, so running the tool on different days builds a history.
- A stale flag on every trial whose registry record was last updated more than 12 months before the snapshot (threshold in config.yaml). Stale records may show a status or posted date that is no longer true.
- Six CSV tables in a star schema for Power BI, with DAX measures and a step by step build guide for a four page report.
- An Excel workbook with the forecast, sites, benchmark rates, data quality issues, and method notes.
- METHOD.md, regenerated on every run, describing the forecast and the backtest results.

## How to run it

Python 3.11 or later.

```
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
trialpace run-all
```

`run-all` does five steps in order. Each is also its own command:

| Command | What it does |
|---|---|
| `trialpace fetch` | Pulls studies from the API and caches raw JSON under `data/raw/YYYY-MM-DD/`. Reruns on the same day skip queries already cached. |
| `trialpace load` | Parses the cached JSON, applies the scope filters, and writes that day's snapshot to `data/trialpace.db`. Rerunning replaces the snapshot rather than duplicating it. |
| `trialpace forecast` | Builds the benchmark set, picks the model with the best backtest, and forecasts every active trial. |
| `trialpace backtest` | Cross-validates all three models over the benchmark set, reports accuracy, and writes METHOD.md. |
| `trialpace export` | Writes `data/powerbi/*.csv` and `data/excel/trialpace_export.xlsx`. |

All commands accept `--date YYYY-MM-DD` to work on a snapshot other than today and `--config` to point at a different config file. Search terms, scope filters, product names, sponsor name mappings, thresholds, and paths all live in `config.yaml`.

## Which trials are included

The API search is deliberately broad. Three filters then narrow it, in this order, and each one logs what it removed:

1. At least one intervention of type DEVICE.
2. A transcatheter term (TAVR, TAVI, transcatheter) or a known valve product name in the title or intervention names.
3. Lead sponsor class INDUSTRY. Set `scope.industry_only: false` in config.yaml to keep academic trials too.

The counts per step are printed by `load`, shown in METHOD.md, and listed at the top of the Excel Data Quality sheet.

Tests run without network access:

```
pytest
```

## How the forecast works

Completed trials with at least 5 listed sites form a benchmark set. Three simple models are compared by leave-one-out cross-validation, where each benchmark trial is predicted from a model fitted on all the others:

- **Per-site rate.** Patients per site per month by valve type and trial size. Months to target = target / (sites x rate).
- **Log-linear regression.** Duration as a function of target enrollment, site count, and valve type.
- **Naive baseline.** The typical duration of completed trials with the same valve type, ignoring target and sites.

Whichever model has the lowest median error across those predictions is used for the forecast outputs. Each active trial gets an early, median, and late date. The median date is compared to the sponsor's posted primary completion date, and the trial gets one of these labels:

- **Past posted date.** The sponsor's own date has already gone by, but the trial is still listed as active. Checked first.
- **Past forecast.** The model's median estimate has already gone by. The trial is slower than comparable completed trials.
- **On track, At risk, Likely late.** How far the median forecast lands after the posted date, using the day thresholds in config.yaml.
- **No posted date.** Nothing to compare against.

METHOD.md has the details and the current counts.

## Results from the 2026-09-21 snapshot

The search returned 1,444 unique trials. The scope filters removed 729 with no device intervention, 269 with no transcatheter term, and 154 with a non-industry sponsor, leaving 292.

| Sponsor | Trials in scope |
|---|---|
| Edwards Lifesciences | 47 |
| Abbott | 25 |
| Medtronic | 22 |
| Boston Scientific | 14 |
| Other | 184 |
| Total | 292 |

Other is mostly smaller device makers, many of them in China and Europe.

Forecasts were produced for 117 active trials. 67 are Past posted date: the sponsor's own primary completion date has gone by while the trial is still listed as active. Most of these are Active not recruiting trials in long follow-up whose records have not been updated. Another 25 are Past forecast, 20 On track, 5 At risk, and none Likely late. 39 of the 117 are flagged stale because their registry record was last updated more than 12 months before the snapshot, so their status and posted date may be out of date. The stale share is 43% in the Other group against 24% for Edwards and 25% for Abbott.

The benchmark set has 54 completed trials. Under leave-one-out cross-validation the log-linear regression had the lowest median error at 37%, against 42% for the naive valve-type median and 58% for the per-site rate, so the regression is used for the outputs. The margin over the naive baseline is modest. Completed aortic trials took a median of 21 months from start to primary completion, mitral trials 35 months, and tricuspid trials 27 months.

## What this can't tell you

- **When enrollment actually finished.** ClinicalTrials.gov reports primary completion, which includes follow-up after the last patient enrolled. Trials with long follow-up look slower than they enrolled.
- **How many sites are really open.** The site count is whatever is listed today. Listed sites include closed and never-activated ones, and some sponsors list sites late or not at all.
- **Why a trial is slow.** Pauses, protocol amendments, competing trials, and supply issues do not show up in the registry.
- **Anything about unregistered or non-public activity.** Company internal projections, site activation plans, and screening logs are not public.
- **A precise date.** The honest output is the range. The median is a reference point for comparison against the posted date, not a prediction to plan around.
- **Much beyond the typical duration.** With 54 benchmark trials, the best model is only a few points better than "trials of this valve type usually take about this long". Treat the trial-specific adjustment for target and site count as a nudge, not a projection.
- **Whether the sponsor's date is wrong.** A trial labelled Likely late is one whose posted date is more ambitious than the benchmark pace. Sponsors sometimes know things the registry does not.
- **Whether a record is current.** The registry only shows what the sponsor last posted. Trials flagged stale have not been updated in over a year, so their status and posted date should be read with that in mind.

## Layout

```
config.yaml            search terms, sponsor mappings, thresholds, paths
trialpace/             package: api, parse, scope, db, forecast, predictors, backtest, exports, cli
tests/                 pytest suite with fixture JSON
powerbi/measures.dax   DAX measures for the report
powerbi/BUILD_GUIDE.md how to build the Power BI report
data/raw/              cached API responses by day (not committed)
data/trialpace.db      SQLite database (not committed)
data/powerbi/          star schema CSVs
data/excel/            Excel workbook
METHOD.md              forecast method and backtest results, generated
DECISIONS.md           choices made where the brief left room
```
