# Method

Last generated from the {snapshot} snapshot by the `backtest` command. Numbers below change when the data changes.

## What the forecast does

The question is: given how long comparable completed trials took, when will an active trial reach its enrollment target?

## Trial scope

The API search is broad on purpose (any interventional trial since 2010 matching the valve conditions or transcatheter terms). Scope filters then narrow it to industry device trials. Each step and what it removed:

{filter_table}

## Benchmark set

Trials in scope that report an ACTUAL enrollment count, a start date, an ACTUAL primary completion date, at least {min_benchmark_sites} listed sites, and a duration of at least {min_months} months. Candidates are completed trials plus active trials whose primary completion date is already ACTUAL, since those have finished enrolling even though the registry still lists them as active.

{benchmark_table}

## Models

Three models are fitted on the benchmark set and compared by leave-one-out cross-validation.

1. **Per-site rate.** Rate = actual enrollment / listed sites / months from start to primary completion, in patients per site per month. Benchmark trials are grouped by valve type (aortic, mitral, tricuspid, other) and size band ({size_bands}). Each segment with at least {min_segment_count} trials gets its own P25, median, and P75 rate; smaller segments fall back to the overall rate. Months to target = target enrollment / (site count x rate). The P75 rate gives the early date and the P25 rate the late date.
2. **Log-linear regression.** Ordinary least squares of log(months) on log(target enrollment), log(site count), and valve type indicators. The median forecast is the fitted value plus the median training residual; the P25 and P75 add the 25th and 75th percentile residuals. This lets duration scale with target and sites without assuming the two cancel exactly.
3. **Naive baseline.** The P25, median, and P75 duration of completed trials with the same valve type, ignoring target and sites. Valve types with fewer than {min_segment_count} trials use the overall distribution.

For every model, each duration is added to the trial's start date, and the result is always a range, never a single date. Trials whose median forecast runs past {max_horizon_months} months from start are excluded and listed with a reason. {horizon_text}

**Status label.** Active trials whose primary completion date is ACTUAL have finished enrolling: they get the label Finished enrolling, no forecast, and stay out of the other counts. For the rest, two checks come first. If the sponsor's posted primary completion date is already behind the snapshot date, the trial is Overdue. Otherwise, if the model's median date is already behind the snapshot date, the trial is Behind forecast. Only then is the gap used: gap = median forecast date minus the posted date. Up to {on_track_days} days is On track, beyond that is Behind forecast. A negative gap means the forecast is ahead of the posted date. Trials with no posted date are On track because nothing shows a delay.

## Status labels in this snapshot

{labels_table}

## Per-site rates in this snapshot

Patients per site per month, from the benchmark set.

{rates_table}

## Duration by valve type

Months from start to primary completion in the benchmark set. This is what the naive baseline predicts.

{durations_table}

## Backtest and model choice

Leave-one-out cross-validation: each of the {benchmark_count} benchmark trials is held out in turn, every model is fitted on the other trials, and the held-out trial's months from start to primary completion is predicted. Every trial is scored exactly once per model, so there is no random split and no seed.

{comparison_table}

{holdout_note}

{choice}

Median absolute percentage error is the more representative number; MAPE is pulled up by a few short trials. Coverage is the share of trials whose actual duration fell inside the model's P25 to P75 range. A well calibrated range would cover about 50%.

## Stale records

A trial is flagged stale when its last update was posted more than {stale_after_months} months before the snapshot date. Sponsors are expected to update their registry entries at least yearly, so a stale record may show a status or posted completion date that no longer reflects the trial. A stale trial marked Recruiting may have finished enrolling or stopped; a stale posted date may already have been missed or moved. The forecast still runs on stale trials, but their status label deserves less weight. {stale_text}

## What the forecast ignores

- **Sites open at different times.** The site count is the number listed today. Early in a trial, far fewer sites are usually active, so the real per-site rate over the whole trial is lower than the peak rate.
- **Enrollment pauses.** Regulatory holds, protocol amendments, supply issues, and seasonal slowdowns are invisible in the registry.
- **Protocol changes.** Targets and completion dates get revised. The forecast uses whatever is posted now.
- **Site count is a snapshot.** Sites listed on ClinicalTrials.gov include closed, withdrawn, and never-activated sites, and some sponsors list sites late or not at all. In this snapshot {single_site_pct}% of benchmark trials list exactly one site.
- **Primary completion is not enrollment completion.** The benchmark duration runs to primary completion because the registry does not report when enrollment closed. Trials with long follow-up before the primary endpoint look slower than they enrolled.
- **Month-precision dates.** Most registry dates carry only year and month. They are treated as the first of the month.
- **Active not recruiting trials.** These trials have usually finished enrolling. Their forecast shows what the model would have predicted, which is useful as a check but not as a forecast of remaining work.
