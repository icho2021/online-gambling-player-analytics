# Player Analytics on Online Gambling Activity

A 48-hour analytics exercise, rebuilt here as a runnable case study: take six
workbooks of raw player activity, model them, answer three analytical questions
in SQL and Python, segment the players, and design the dashboard that sits on
top.

The original source data is not redistributed. `src/make_sample_data.py`
generates synthetic workbooks with the same sheet names, columns and types, so
every script below runs end to end on a clean clone.

## The data

Six workbooks, one row per event:

| Table | Grain | Columns |
| --- | --- | --- |
| Demographics | one player | UserID, DateOfBirth, Gender, CountryCode |
| Country reference | one country | CountryCode, Country |
| Games | one player-day of cash games | UserID, Date, CashGames, Odds, Wagers, Winnings |
| Tournaments | one player-day of tournaments | UserID, Date, Tournaments, Odds, Wagers, Winnings |
| Deposits | one deposit attempt | UserID, DepositID, Date, Time, PayMeth, PayMethCat, Amount, Status |
| Withdrawals | one withdrawal attempt | UserID, WithdrawalID, Date, Time, PayMeth, PayMethCat, Amount, Status |

Deposits and withdrawals arrive split across separate successful and failed
sheets, so failed attempts have to be carried through rather than dropped: a
high failure rate is itself a signal.

Data model: [`docs/er_diagram.md`](docs/er_diagram.md).

## What it does

**1. Combine everything into one player-day table.** Five sources at three
different grains. Play activity is already daily, transactions are timestamped
and need aggregating, demographics are static. The join has to keep a player-day
that has a deposit but no play, and one that has play but no deposit.

**2. Aggregate to month by game type.** Player volume, total wagers, total
winnings and average odds, cash games against tournaments. Average odds is
averaged per player-day first and then across the month, because averaging
across raw rows weights heavy players more than the question intends.

**3. Build an anti-money-laundering review file.** A player-level workbook with
locked columns, dropdown validation on Review Status and Decision, and a free
text comment field. The script then reads a returned workbook back, validates
what the reviewer entered against the allowed values, and exports a CSV replica.
The point is that the reviewer's decision is captured in a structured,
checkable form rather than in an email.

**4. Segment the players.** Two approaches kept side by side: KMeans on
standardised behavioural features, and an RFM score. Value segments are Low,
Medium, High and Premium; risk segments are Low, Medium and High, rule-based on
behavioural indicators.

KMeans is implemented directly in numpy, including k-means++ initialisation,
rather than called from a library. K is set to four because four tiers are
actionable, not because a silhouette score picked it. Keeping the RFM result
beside it matters: the two methods disagree on some players, and the
disagreement is information about where the boundary is soft.

**5. Design the dashboard.** Five pages, from an executive overview to value and
risk segmentation to an explicit insights page.
See [`docs/dashboard_design.md`](docs/dashboard_design.md).

## Run it

```bash
pip install -r requirements.txt
python -m src.make_sample_data    # synthetic source workbooks -> data/
python src/run_sql.py             # player-day and monthly tables -> output/
python src/build_aml_review.py    # AML review workbook + validation -> output/
python src/segment_players.py     # value and risk segments -> output/
```

Sample outputs from a synthetic run are committed under `output/` for the small
files. The large intermediate tables and the DuckDB file are rebuilt rather than
tracked.

## Notes on judgment

**Risk labels are for prioritising review, not for accusing anyone.** A high
risk segment means a person should look, not that misconduct occurred. The AML
workbook is built the same way: it routes a case to a reviewer and records the
reviewer's decision.

**Net Gaming is not labelled Gross Gaming Revenue.** Wagers minus winnings is
defensible as a number, but the business term carries a specific regulatory
definition and is not used here without confirmation.

**Failed transactions are kept.** They are loaded from their own sheets and
carried into the player-day table, because failure rate feeds the risk
indicators.

## Stack

Python, DuckDB, pandas, numpy, openpyxl, Power BI for the dashboard. No modelling library: the clustering is written out.
