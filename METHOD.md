# Method

Last generated from the 2026-09-21 snapshot by the `backtest` command. Numbers below change when the data changes.

## What the forecast does

The question is: given how long comparable completed trials took, when will an active trial reach its enrollment target?

## Trial scope

The API search is broad on purpose (any interventional trial since 2010 matching the valve conditions or transcatheter terms). Scope filters then narrow it to industry device trials. Each step and what it removed:

| Step | Removed | Remaining |
|---|---|---|
| parsed | 0 | 1444 |
| no DEVICE intervention | 729 | 715 |
| no transcatheter term or product name in title or interventions | 269 | 446 |
| lead sponsor class is not INDUSTRY | 154 | 292 |

## Benchmark set

Completed trials in scope that report an ACTUAL enrollment count, a start date, an ACTUAL primary completion date, at least 5 listed sites, and a duration of at least 3.0 months.

| Reason | Trials removed |
|---|---|
| fewer than 5 sites listed | 27 |
| Kept as benchmarks | 54 |

## Models

Three models are fitted on the benchmark set and compared by leave-one-out cross-validation.

1. **Per-site rate.** Rate = actual enrollment / listed sites / months from start to primary completion, in patients per site per month. Benchmark trials are grouped by valve type (aortic, mitral, tricuspid, other) and size band (small (up to 100), medium (up to 500), large (above the previous band)). Each segment with at least 5 trials gets its own P25, median, and P75 rate; smaller segments fall back to the overall rate. Months to target = target enrollment / (site count x rate). The P75 rate gives the early date and the P25 rate the late date.
2. **Log-linear regression.** Ordinary least squares of log(months) on log(target enrollment), log(site count), and valve type indicators. The median forecast is the fitted value plus the median training residual; the P25 and P75 add the 25th and 75th percentile residuals. This lets duration scale with target and sites without assuming the two cancel exactly.
3. **Naive baseline.** The P25, median, and P75 duration of completed trials with the same valve type, ignoring target and sites. Valve types with fewer than 5 trials use the overall distribution.

For every model, each duration is added to the trial's start date, and the result is always a range, never a single date. Trials whose median forecast runs past 240 months from start are excluded and listed with a reason. In this snapshot, after the scope and benchmark filters, the horizon cap excluded 0 under the naive baseline model, 20 under the per-site rate model, 0 under the log-linear regression model.

**Status label.** Gap = median forecast date minus the sponsor's posted primary completion date. Up to 90 days is On track, up to 365 days is At risk, beyond that is Likely late. A negative gap means the forecast is ahead of the posted date. Trials with no posted date get their own label.

## Per-site rates in this snapshot

Patients per site per month, from the benchmark set.

| Valve type | Size band | Trials | P25 | Median | P75 | Source |
|---|---|---|---|---|---|---|
| all | all | 54 | 0.206 | 0.466 | 0.962 | overall |
| aortic | large | 9 | 0.634 | 0.986 | 1.003 | segment |
| aortic | medium | 14 | 0.431 | 0.713 | 1.113 | segment |
| aortic | small | 16 | 0.408 | 0.590 | 0.918 | segment |
| mitral | medium | 5 | 0.153 | 0.197 | 0.235 | segment |
| mitral | small | 5 | 0.031 | 0.046 | 0.096 | segment |
| tricuspid | small | 5 | 0.160 | 0.162 | 0.179 | segment |

## Duration by valve type

Months from start to primary completion in the benchmark set. This is what the naive baseline predicts.

| Valve type | Trials | P25 | Median | P75 |
|---|---|---|---|---|
| aortic | 39 | 13.1 | 20.6 | 32.3 |
| mitral | 10 | 30.6 | 35.2 | 53.5 |
| tricuspid | 5 | 16.5 | 27.1 | 27.4 |
| all | 54 | 16.1 | 22.5 | 35.7 |

## Backtest and model choice

Leave-one-out cross-validation: each of the 54 benchmark trials is held out in turn, every model is fitted on the other trials, and the held-out trial's months from start to primary completion is predicted. Every trial is scored exactly once per model, so there is no random split and no seed.

| Model | Trials scored | Median abs. % error | MAPE | Inside P25 to P75 | Selected |
|---|---|---|---|---|---|
| Per-site rate | 54 | 57.7% | 76.7% | 38.9% |  |
| Log-linear regression | 54 | 36.8% | 52.7% | 44.4% | yes |
| Naive baseline | 54 | 41.9% | 58.8% | 48.1% |  |

**Forecast outputs use the Log-linear regression model.** It had the lowest median absolute percentage error under leave-one-out cross-validation (36.8% against 41.9% for the naive baseline). Median error is the selection criterion because MAPE is dominated by a few short trials.

Median absolute percentage error is the more representative number; MAPE is pulled up by a few short trials. Coverage is the share of trials whose actual duration fell inside the model's P25 to P75 range. A well calibrated range would cover about 50%.

## What the forecast ignores

- **Sites open at different times.** The site count is the number listed today. Early in a trial, far fewer sites are usually active, so the real per-site rate over the whole trial is lower than the peak rate.
- **Enrollment pauses.** Regulatory holds, protocol amendments, supply issues, and seasonal slowdowns are invisible in the registry.
- **Protocol changes.** Targets and completion dates get revised. The forecast uses whatever is posted now.
- **Site count is a snapshot.** Sites listed on ClinicalTrials.gov include closed, withdrawn, and never-activated sites, and some sponsors list sites late or not at all. In this snapshot 0% of benchmark trials list exactly one site.
- **Primary completion is not enrollment completion.** The benchmark duration runs to primary completion because the registry does not report when enrollment closed. Trials with long follow-up before the primary endpoint look slower than they enrolled.
- **Month-precision dates.** Most registry dates carry only year and month. They are treated as the first of the month.
- **Active not recruiting trials.** These trials have usually finished enrolling. Their forecast shows what the model would have predicted, which is useful as a check but not as a forecast of remaining work.
