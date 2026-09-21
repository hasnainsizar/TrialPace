# Power BI build guide

This guide builds a four page report in Power BI Desktop from the CSV files that `trialpace export` writes to `data/powerbi/`. It assumes no prior Power BI experience beyond opening the application.

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
   - dim_trial: start_date, primary_completion_date, completion_date, last_update_date as Date
   - fact_forecast: start_date, date_p25, date_median, date_p75, posted_primary_completion_date as Date. gap_days as Whole Number. months_p25, months_median, months_p75 as Decimal Number.
   - fact_benchmark: start_date, primary_completion_date as Date. rate_per_site_month and months as Decimal Number.
   - fact_site: snapshot_date as Date.
   - sponsor_key everywhere as Whole Number.
4. Close and Apply.

## 2. Relationships

Open Model view. Delete any relationships Power BI created on its own, then create these. All are one to many, single direction, from the dimension to the fact.

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

Format Share Likely Late as a percentage. Format Median Gap Days as a whole number. Format Median Rate Per Site Per Month with two decimals.

## 4. Pages

Add a slicer for dim_sponsor[sponsor] to every page. Optionally add a slicer for dim_trial[valve_type].

### Page 1: Overview

Purpose: how many trials are running, how much enrollment is outstanding, and which sponsors are behind.

KPI cards across the top, one Card visual each:
- Active Trials
- Total Target Enrollment
- Total Sites
- Share Likely Late
- Median Gap Days

Table visual, active trials by sponsor and status:
- Rows: dim_sponsor[sponsor]
- Columns: fact_forecast[status_label]
- Values: Active Trials
Use a Matrix visual for this so status becomes columns. Turn on row and column subtotals.

Second table, active trial detail:
- dim_trial[nct_id], dim_trial[title], dim_sponsor[sponsor], fact_forecast[overall_status], fact_forecast[target_enrollment], fact_forecast[site_count], fact_forecast[date_median], fact_forecast[posted_primary_completion_date], fact_forecast[gap_days], fact_forecast[status_label]
Apply conditional formatting on status_label with Rules: "On track" green, "At risk" amber, "Likely late" red.

### Page 2: Forecast vs posted date

Purpose: for each active trial, show the forecast range next to the sponsor's posted primary completion date.

Power BI does not ship a native range bar visual, so the chart uses months from start on a shared axis and error bars for the range.

1. Add a Clustered column chart.
   - X axis: dim_trial[nct_id]
   - Y axis: Forecast Months Median, then Posted Months as a second series
2. Open the Analytics pane for the visual, choose Error bars, enable them for Forecast Months Median, set Type to By field, Lower bound Forecast Months P25, Upper bound Forecast Months P75.
3. Sort the axis by Forecast Months Median descending so the slowest trials come first.
4. Add a Top N filter on nct_id (say top 40 by Forecast Months Median) so the chart is readable, and tell the reader in the page title that it is filtered.

Reading it: the column with the error bar is the forecast, the bar is the P25 to P75 range, and the adjacent column is the sponsor's posted date. When the posted column sits below the P25 end of the bar, the sponsor's date looks optimistic against the benchmark.

If a date axis is required, install the Gantt custom visual from AppSource and map Task to nct_id, Start Date to date_p25, End Date to date_p75, and use posted_primary_completion_date as a milestone.

Add a table beneath the chart with nct_id, title, date_p25, date_median, date_p75, posted_primary_completion_date, gap_days, status_label.

### Page 3: Site footprint

Purpose: where trials are recruiting, filterable by sponsor.

1. Add a Map visual (or Azure Map).
   - Location: fact_site[country] for a world view. For a US view, add a second map with fact_site[state] and set Country to "United States" in the visual filter.
   - Bubble size: Sites In Snapshot
   - Legend: dim_sponsor[sponsor]
2. Set the Data category on fact_site[country] to Country and fact_site[state] to State or Province (Column tools, Data category) so the map geocodes correctly.
3. Add a table: fact_site[country], fact_site[state], Sites In Snapshot, sorted descending.
4. Add a slicer on fact_site[snapshot_date] if more than one snapshot exists, defaulting to the latest.
5. Add a card for Countries.

### Page 4: Sponsor comparison

Purpose: does Edwards enroll faster or slower per site than competitors, and how many trials does each run.

1. Clustered bar chart: X axis dim_sponsor[sponsor], Y axis Median Rate Per Site Per Month. Add Rate P25 and Rate P75 as error bar bounds the same way as on page 2.
2. Clustered column chart: X axis dim_sponsor[sponsor], Y axis Benchmark Trials and Active Trials.
3. Matrix: rows dim_sponsor[sponsor], columns dim_trial[valve_type], values Trials In Snapshot.
4. Cards: Edwards Trials, Competitor Trials.
5. Add a text box under the rate chart stating the benchmark count for each sponsor. Named sponsors have far fewer benchmark trials than Other, so their quantiles rest on small numbers.

## 5. Refresh

After a new `trialpace run-all`, open the report and click Refresh. The CSV paths are fixed, so the tables reload without further steps. If you move the folder, update the source path under Transform data, Data source settings.
