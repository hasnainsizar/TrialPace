# Power BI build guide

This guide builds a five page report in Power BI Desktop from the CSV files that `trialpace export` writes to `data/powerbi/`. It assumes no prior Power BI experience beyond opening the application.

## 1. Load the tables

1. Open Power BI Desktop. Choose Get data, then Text/CSV.
2. Load each of these six files. Accept the defaults, then click Transform Data before loading the last one so all six open in Power Query.
   - dim_trial.csv
   - dim_sponsor.csv
   - dim_date.csv
   - fact_site.csv
   - fact_forecast.csv
   - fact_benchmark.csv
3. In Power Query, fix the data types. Power BI guesses well for most columns. Check these:
   - dim_date[date]: Date
   - dim_trial: start_date, primary_completion_date, completion_date, last_update_date as Date. is_stale as Whole Number. sponsor_group, sponsor_name, mapped_via as Text.
   - fact_forecast: start_date, date_p25, date_median, date_p75, posted_primary_completion_date, last_update_posted as Date. gap_days and is_stale as Whole Number. months_p25, months_median, months_p75 as Decimal Number. model and basis as Text. Rows with the status "Primary completion reached" have blank forecast columns on purpose.
   - fact_benchmark: start_date, primary_completion_date as Date. rate_per_site_month and months as Decimal Number.
   - fact_site: snapshot_date as Date.
   - sponsor_key everywhere as Whole Number.
4. Close and Apply.

Column naming: `sponsor_group` is the parent company bucket (Edwards Lifesciences, Medtronic, Boston Scientific, Abbott, Other). `sponsor_name` is the lead sponsor name exactly as the registry lists it. `mapped_via` says why a name landed in its group: direct, affiliate, acquisition, or none. Use sponsor_group for slicers, legends, and comparisons. Use sponsor_name in tables and tooltips.

## 2. Relationships

Open Model view. Delete any relationships Power BI created on its own, then create these. All are one to many, single direction, from the dimension to the fact. The sponsor key is unchanged: dim_sponsor[sponsor_key] is still the key, only the label column was renamed to sponsor_group.

| From (one side) | To (many side) | Active |
|---|---|---|
| dim_sponsor[sponsor_key] | dim_trial[sponsor_key] | Yes |
| dim_sponsor[sponsor_key] | fact_forecast[sponsor_key] | Yes |
| dim_sponsor[sponsor_key] | fact_benchmark[sponsor_key] | Yes |
| dim_sponsor[sponsor_key] | fact_site[sponsor_key] | Yes |
| dim_trial[nct_id] | fact_forecast[nct_id] | Yes |
| dim_trial[nct_id] | fact_benchmark[nct_id] | Yes |
| dim_trial[nct_id] | fact_site[nct_id] | Yes |
| dim_date[date] | fact_forecast[posted_primary_completion_date] | Yes |
| dim_date[date] | fact_forecast[date_median] | No |
| dim_date[date] | fact_benchmark[primary_completion_date] | Yes |
| dim_date[date] | fact_site[snapshot_date] | Yes |

Mark dim_date as a date table: select it, then Table tools, Mark as date table, column `date`.

Note: fact_site has one row per site per snapshot. If you have run the tool on several days it contains history. The Total Sites measure counts only the latest snapshot. Sites In Snapshot respects whatever snapshot is on the visual.

## 3. Measures

Open `powerbi/measures.dax`. For each block, select the table named in the comment, choose New measure (or New column where the comment says calculated column), and paste the expression. Create the calculated column `Posted Months From Start` before the `Posted Months` measure.

Format Share Overdue, Share Behind Forecast, and Share Stale as percentages. Format Median Gap Days as a whole number. Format Median Rate Per Site Per Month with two decimals.

## 4. Status colours

Every visual that shows fact_forecast[status_label] should use the same colours. Set them once: select a visual with status_label as legend, open Format, Data colors, and assign:

| Status label | Colour | Hex |
|---|---|---|
| On track | Green | #C6EFCE |
| Behind forecast | Yellow | #FFEB9C |
| Overdue | Red | #FFC7CE |
| Primary completion reached | Gray | #D9D9D9 |

For tables, apply the same hex values as conditional formatting Rules on the status_label column (Background color, Rules, field value equals each label). These match the fills in the Excel export.

## 5. Slicers on every page

Add these three slicers to every page and sync them across pages (View, Sync slicers):

- dim_sponsor[sponsor_group]
- dim_trial[valve_type]
- fact_forecast[is_stale], rendered as a two-button tile slicer labelled Stale: 1 shows only trials whose record is more than a year old, 0 hides them.

## 6. Pages

### Page 1: Overview

Purpose: how many trials are running, how much enrollment is outstanding, and which sponsor groups are behind.

KPI cards across the top, one Card visual each:
- Active Trials
- Forecast Trials
- Total Target Enrollment
- Total Sites
- Share Overdue
- Share Behind Forecast
- Stale Active Trials

Add a Card showing fact_forecast[model] (set to First, filtered to model not equal to "none") so the page states which model produced the forecast. The model is chosen by the backtest and can change between snapshots.

Matrix, active trials by sponsor group and status:
- Rows: dim_sponsor[sponsor_group]
- Columns: fact_forecast[status_label]
- Values: Active Trials
Turn on row and column subtotals. Apply the status colours to the column headers via conditional formatting on status_label if desired.

Table, active trial detail:
- dim_trial[nct_id], dim_trial[title], dim_sponsor[sponsor_group], dim_trial[sponsor_name], fact_forecast[overall_status], fact_forecast[target_enrollment], fact_forecast[site_count], fact_forecast[date_median], fact_forecast[posted_primary_completion_date], fact_forecast[gap_days], fact_forecast[status_label], fact_forecast[is_stale]
Apply the status colour rules from section 4 to status_label. Apply a grey font colour rule on is_stale = 1 so stale records read as less certain. Add dim_trial[mapped_via] to the tooltip.

### Page 2: Forecast vs posted date

Purpose: for each forecast trial, show the forecast range next to the sponsor's posted primary completion date.

Power BI does not ship a native range bar visual, so the chart uses months from start on a shared axis and error bars for the range.

1. Add a Clustered column chart.
   - X axis: dim_trial[nct_id]
   - Y axis: Forecast Months Median, then Posted Months as a second series
   - Visual filter: fact_forecast[status_label] is not "Primary completion reached", so trials without a forecast do not appear as empty columns.
2. Open the Analytics pane for the visual, choose Error bars, enable them for Forecast Months Median, set Type to By field, Lower bound Forecast Months P25, Upper bound Forecast Months P75.
3. Sort the axis by Forecast Months Median descending so the slowest trials come first.
4. Add a Top N filter on nct_id (say top 40 by Forecast Months Median) so the chart is readable, and tell the reader in the page title that it is filtered.
5. Put dim_trial[sponsor_name] and fact_forecast[status_label] in the tooltip.

Reading it: the column with the error bar is the forecast, the bar is the P25 to P75 range, and the adjacent column is the sponsor's posted date. When the posted column sits below the P25 end of the bar, the sponsor's date looks optimistic against the benchmark. Trials labelled Overdue have a posted column shorter than the time already elapsed.

If a date axis is required, install the Gantt custom visual from AppSource and map Task to nct_id, Start Date to date_p25, End Date to date_p75, and use posted_primary_completion_date as a milestone.

Add a table beneath the chart with nct_id, sponsor_name, date_p25, date_median, date_p75, posted_primary_completion_date, gap_days, status_label, with the status colour rules applied.

### Page 3: Site footprint

Purpose: where trials are recruiting, filterable by sponsor group.

1. Add a Map visual (or Azure Map).
   - Location: fact_site[country] for a world view. For a US view, add a second map with fact_site[state] and set Country to "United States" in the visual filter.
   - Bubble size: Sites In Snapshot
   - Legend: dim_sponsor[sponsor_group]
2. Set the Data category on fact_site[country] to Country and fact_site[state] to State or Province (Column tools, Data category) so the map geocodes correctly.
3. Add a table: fact_site[country], fact_site[state], Sites In Snapshot, sorted descending.
4. Add a slicer on fact_site[snapshot_date] if more than one snapshot exists, defaulting to the latest.
5. Add a card for Countries.

### Page 4: Sponsor comparison

Purpose: does Edwards enroll faster or slower per site than competitors, and how many trials does each group run.

1. Clustered bar chart: X axis dim_sponsor[sponsor_group], Y axis Median Rate Per Site Per Month. Add Rate P25 and Rate P75 as error bar bounds the same way as on page 2.
2. Clustered column chart: X axis dim_sponsor[sponsor_group], Y axis Benchmark Trials and Active Trials.
3. Matrix: rows dim_sponsor[sponsor_group], columns dim_trial[valve_type], values Trials In Snapshot.
4. Cards: Edwards Trials, Competitor Trials.
5. Table of dim_trial[sponsor_name] with dim_trial[mapped_via] and Trials In Snapshot, sorted descending. Filtered to sponsor_group = "Other" it shows which smaller companies make up the Other group; unfiltered it shows which names were folded into each group and why (direct, affiliate, acquisition).
6. Add a text box under the rate chart stating the benchmark count for each group. Named groups have far fewer benchmark trials than Other, so their quantiles rest on small numbers. The per-site rate is a descriptive comparison here even when the forecast on pages 1 and 2 uses a different model.

### Page 5: Record freshness

Purpose: which records on the registry can be trusted as current.

1. Clustered bar chart: X axis dim_sponsor[sponsor_group], Y axis Trials Overdue and Stale Active Trials as two series. Sort by Trials Overdue descending.
2. Cards: Trials Overdue, Share Overdue, Stale Active Trials, Share Stale.
3. Table of overdue trials. Visual filter: fact_forecast[status_label] = "Overdue". Columns:
   - dim_trial[nct_id]
   - dim_sponsor[sponsor_group]
   - dim_trial[sponsor_name]
   - fact_forecast[overall_status]
   - fact_forecast[posted_primary_completion_date]
   - fact_forecast[last_update_posted]
   - fact_forecast[is_stale]
   Sort by posted_primary_completion_date ascending so the oldest missed dates come first. Apply the grey font rule on is_stale = 1.
4. A second matrix: rows dim_sponsor[sponsor_group], values Active Trials, Stale Active Trials, Share Stale, Trials Overdue, Share Overdue.
5. Text box: "An overdue trial is still listed as active although the sponsor's own primary completion date has gone by. A stale trial has not been updated on the registry for over a year. Both mean the status shown may not be the status today."

## 7. Refresh

After a new `trialpace run-all`, open the report and click Refresh. The CSV paths are fixed, so the tables reload without further steps. If you move the folder, update the source path under Transform data, Data source settings.
