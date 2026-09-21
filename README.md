# trialpace

Enrollment pace forecasts for structural heart device trials, built from public ClinicalTrials.gov data.

trialpace pulls every interventional trial since 2010 for transcatheter aortic, mitral, and tricuspid valve therapy, works out how fast comparable completed trials enrolled, and estimates when each active trial will reach its enrollment target. The output is a set of CSV tables ready for Power BI and a formatted Excel workbook.

This project uses only the public ClinicalTrials.gov API. It is not affiliated with, endorsed by, or informed by Edwards Lifesciences, Medtronic, Boston Scientific, Abbott, or any other company named in the data.

## Why enrollment pace matters

A device trial cannot report results until it has enrolled enough patients. For a company like Edwards or Medtronic, the enrollment period decides when a new valve can be submitted for approval, when it reaches the market, and how long a competitor's head start lasts. Sponsors post a planned primary completion date on ClinicalTrials.gov, but those dates are often optimistic. Comparing the posted date to what similar trials actually achieved gives an outside view of which trials are on schedule and which are likely to slip.

## What it produces

- A SQLite database with a dated snapshot of every trial, every listed site, and every data quality problem, so running the tool on different days builds a history.
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
| `trialpace load` | Parses the cached JSON into that day's snapshot in `data/trialpace.db`. Rerunning replaces the snapshot rather than duplicating it. |
| `trialpace forecast` | Builds benchmark rates from completed trials and forecasts every active trial. |
| `trialpace backtest` | Holds out 20% of benchmark trials, predicts them, reports accuracy, and writes METHOD.md. |
| `trialpace export` | Writes `data/powerbi/*.csv` and `data/excel/trialpace_export.xlsx`. |

All commands accept `--date YYYY-MM-DD` to work on a snapshot other than today and `--config` to point at a different config file. Search terms, sponsor name mappings, thresholds, and paths all live in `config.yaml`.

Tests run without network access:

```
pytest
```

## How the forecast works

In one paragraph: completed trials give an enrollment rate in patients per site per month. Rates are grouped by valve type and trial size. For each active trial, months to target = target enrollment / (listed sites x benchmark rate). Using the fast, median, and slow benchmark rates gives an early, median, and late date. The median date is compared to the sponsor's posted primary completion date, and the trial is labelled On track, At risk, or Likely late. METHOD.md has the details and the current numbers.

## Results from the first run (2026-09-21 snapshot)

Trials pulled after deduplication:

| Sponsor | Trials |
|---|---|
| Edwards Lifesciences | 73 |
| Abbott | 33 |
| Medtronic | 25 |
| Boston Scientific | 16 |
| Other | 1,297 |
| Total | 1,444 |

Most trials are run by hospitals and universities rather than device companies. That is expected: the search catches investigator led trials of drugs, imaging, and procedures in valve patients, not just device pivotal trials.

Forecasts were produced for 359 active trials. 206 are On track, 22 At risk, and 131 Likely late. Every active trial from a named device company came out On track except one Abbott trial marked At risk. The Likely late group is almost entirely investigator led trials that list one or two sites against large targets.

The benchmark set has 469 completed trials with a median rate of about 1.1 patients per listed site per month. On the holdout backtest the median forecast was off by 68% at the median trial and the actual completion fell inside the P25 to P75 range for 52% of trials. MAPE was 247%, inflated by a few short trials.

## What this can't tell you

- **When enrollment actually finished.** ClinicalTrials.gov reports primary completion, which includes follow-up after the last patient enrolled. Trials with long follow-up look slower than they enrolled.
- **How many sites are really open.** The site count is whatever is listed today. Many single-center listings are incomplete, and listed sites include closed and never-activated ones. More than half of benchmark trials list exactly one site.
- **Why a trial is slow.** Pauses, protocol amendments, competing trials, and supply issues do not show up in the registry.
- **Anything about unregistered or non-public activity.** Company internal projections, site activation plans, and screening logs are not public.
- **A precise date.** The honest output is the range. The median is a reference point for comparison against the posted date, not a prediction to plan around.
- **Whether the sponsor's date is wrong.** A trial labelled Likely late is one whose posted date is more ambitious than the benchmark pace. Sponsors sometimes know things the registry does not.

## Layout

```
config.yaml            search terms, sponsor mappings, thresholds, paths
trialpace/             package: api, parse, db, forecast, backtest, exports, cli
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
