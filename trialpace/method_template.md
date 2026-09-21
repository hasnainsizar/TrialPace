# Method

Last generated from the {snapshot} snapshot by the `backtest` command. Numbers below change when the data changes.

## What the forecast does

The question is: given how fast similar trials have enrolled in the past, when will an active trial reach its enrollment target?

1. **Benchmark set.** Completed trials that report an ACTUAL enrollment count, a start date, and an ACTUAL primary completion date, with at least one listed site and a duration of at least {min_months} months.
2. **Rate per benchmark trial.** Enrollment rate = actual enrollment / number of listed sites / months from start to primary completion. The unit is patients per site per month.
3. **Segments.** Benchmark trials are grouped by valve type (aortic, mitral, tricuspid, other) and trial size band ({size_bands}). Each segment with at least {min_segment_count} trials gets its own P25, median, and P75 rate. Smaller segments fall back to the overall rate across all benchmark trials.
4. **Forecast per active trial.** For each recruiting or active-not-recruiting trial: months to target = target enrollment / (site count x segment rate). The P75 rate gives the early date, the median rate gives the median date, and the P25 rate gives the late date. Each is added to the trial's start date. The result is always a range, never a single date. Trials whose median forecast runs past {max_horizon_months} months from start are excluded and listed with a reason, because that pattern almost always means a large target with an incomplete site list.
5. **Status label.** Gap = median forecast date minus the sponsor's posted primary completion date. Up to {on_track_days} days is On track, up to {at_risk_days} days is At risk, beyond that is Likely late. A negative gap means the forecast is ahead of the posted date. Trials with no posted date get their own label.

## Benchmark rates in this snapshot

Patients per site per month.

{rates_table}

## What the forecast ignores

- **Sites open at different times.** The site count is the number listed today. Early in a trial, far fewer sites are usually active, so the real per-site rate over the whole trial is lower than the peak rate.
- **Enrollment pauses.** Regulatory holds, protocol amendments, supply issues, and seasonal slowdowns are invisible in the registry.
- **Protocol changes.** Targets and completion dates get revised. The forecast uses whatever is posted now.
- **Site count is a snapshot.** Sites listed on ClinicalTrials.gov include closed, withdrawn, and never-activated sites, and some sponsors list sites late or not at all. In this snapshot {single_site_pct}% of benchmark trials list exactly one site, so the per-site rate is really a per-listed-site rate.
- **Primary completion is not enrollment completion.** The benchmark rate uses primary completion as the end point because the registry does not report the date enrollment closed. Trials with long follow-up before the primary endpoint will look slower than they enrolled.
- **Month-precision dates.** Most registry dates carry only year and month. They are treated as the first of the month.
- **Active not recruiting trials.** These trials have usually finished enrolling. Their forecast shows what the benchmark rate would have predicted, which is useful as a check but not as a forecast of remaining work.

## Backtest

{holdout_pct}% of the benchmark trials are held out at random with a fixed seed. Rates are rebuilt from the remaining trials, then each held-out trial's duration is predicted from its start date, site count, and actual enrollment. The prediction is compared to the actual months from start to primary completion.

{backtest}

MAPE is pulled up by a few short trials that the rate predicts as long. The median absolute percentage error is the more representative number. Treat the P25 to P75 range as the honest output and the median as a reference point, not a commitment.
