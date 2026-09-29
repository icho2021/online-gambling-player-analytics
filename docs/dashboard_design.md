# Dashboard design

Power BI design rationale for the player performance, behaviour and
segmentation dashboard. This is the specification; the findings themselves are
validated in the report, not asserted here.

**Design intent.** Make financial performance, player behaviour, value
segmentation and risk segmentation understandable at a glance, while keeping
enough detail underneath for someone to investigate a specific case.

## 1. Who it is for

Business, finance, player operations and risk stakeholders. It has to support
both a two-minute executive read and a guided exploration, without needing a
separate written report alongside it.

It should answer:

- How are wagering, winnings, deposits, withdrawals, player volume and net
  gaming moving over time?
- Who are the players, and how does activity differ by demographics, game type
  and behaviour?
- What do the value and risk segments actually mean in business outcomes?

## 2. Principles

| Principle | How it shows up |
| --- | --- |
| Insight first | Each page opens with one analytical question and a short takeaway area, not a wall of charts |
| Self-service | Date, game type, country, gender, value segment and risk segment filters stay consistent across every page |
| Traceable metrics | Every KPI definition and segment rule is documented, and every statement is reproducible from the model |
| Progressive detail | Executive KPIs lead to trends, then segments, then player-level drill-through where it is justified |
| Responsible interpretation | Risk indicators prioritise review. They are not presented as proof of misconduct |

## 3. Pages

**Page 1, Executive overview.** Is performance growing, flat or weakening? KPI
cards for active players, total wagers, total winnings, net gaming, deposits,
withdrawals and average wager per active player. Monthly trend for wagers,
winnings and net gaming. Cash games against tournaments. Contribution by country
and value segment. Two or three takeaway cards that hold under the current
filters.

**Page 2, Financial performance.** What is driving the result, and is it volume
or mix? Trend and variance by month and game type. The wager-to-winnings
relationship and net gaming contribution by game type, country and segment.
Deposit and withdrawal behaviour including successful and failed counts.
Tooltips carry player volume, average odds, average wager and the
withdrawal-to-deposit ratio.

**Page 3, Player profiles and behaviour.** Who participates, and how does
engagement differ? Distribution by age band, gender and country. Frequency,
recency, cash-game and tournament activity, wagers, winnings, deposits,
withdrawals. Drill-through to a single player only where it adds investigative
value and stays appropriately scoped.

**Page 4, Value and risk segmentation.** Turns the segmentation output into a
business-facing view instead of leaving it as a table. Value distribution across
Low, Medium, High and Premium. Risk distribution across Low, Medium and High. A
value by risk matrix showing player counts and financial contribution at each
intersection. Segment profiles built from age, recency, frequency, wager amount,
winning amount, deposits, withdrawals, failed transaction rate, and country and
gender mix. A methodology note comparing the KMeans result against the RFM
score, with the production view labelled consistently.

**Page 5, Key insights and actions.** Three to five findings, each stated as
observation, then business significance, then suggested next action, with one
supporting visual beside it and the filter context preserved.

## 4. Metric framework

| Metric | Definition | Source |
| --- | --- | --- |
| Active players | Distinct UserID in the selected period | Player-day table |
| Total wagers | Cash game wagers + tournament wagers | Player-day table |
| Total winnings | Cash game winnings + tournament winnings | Player-day table |
| Net gaming | Total wagers − total winnings | Player-day and segment outputs |
| Deposit amount | Sum of successful deposits in the period | Player-day table |
| Withdrawal amount | Sum of successful withdrawals in the period | Player-day table |
| Average wager per player | Total wagers ÷ distinct active players | Calculated measure |
| Failed transaction rate | Failed deposits and withdrawals over total attempts | Player-day and segment outputs |
| Value segment | Selected segmentation label, KMeans and RFM kept distinguishable | Segment output |
| Risk segment | Rule-based label from behavioural indicators | Segment output |

**One naming caution.** Net gaming is not labelled Gross Gaming Revenue. Wagers
minus winnings is a defensible calculation, but GGR is a regulated term with a
specific definition, and the business term should not be borrowed until that
definition is confirmed.

## 5. Model

A star schema, with one deliberate constraint: pre-aggregated monthly values are
not connected to player-level tables in a way that lets them double count.

| Object | Grain | Content |
| --- | --- | --- |
| FactPlayerActivity | One player per activity date | Game activity, wagers, winnings, deposits, withdrawals, transaction counts |
| FactMonthlyGameType | One month per game type | Player volume, wagers, winnings, average odds |
| DimPlayer | One player | Demographics, country, value segment, risk segment |
| DimDate | One date | Calendar attributes for time intelligence |
| DimGameType | One game type | Cash games, tournaments |
