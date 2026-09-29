-- SQL dialect: DuckDB v1.5.5
-- Run from the project root. Source workbooks live in data/ (see src/make_sample_data.py).
SELECT version() AS duckdb_version;
-- =========================================================
-- Player-day and monthly aggregation
-- =========================================================

INSTALL excel;
LOAD excel;

-- =========================================================
-- 1. Load Datasets
-- =========================================================

-- 1. Country Reference

CREATE OR REPLACE TABLE stg_country_reference AS
SELECT
    CAST(CountryCode AS INTEGER) AS CountryCode,
    TRIM(CAST(Country AS VARCHAR)) AS Country
FROM read_xlsx(
    'data/Country Reference Table.xlsx',
    sheet = 'Sheet1',
    header = true
);


-- 2. Demographics

CREATE OR REPLACE TABLE stg_demographics AS
SELECT
    CAST(UserID AS INTEGER)       AS UserID,
    CAST(DateOfBirth AS DATE)     AS DateOfBirth,
    CAST(Gender AS VARCHAR)       AS Gender,
    CAST(CountryCode AS INTEGER)  AS CountryCode
FROM read_xlsx(
    'data/Demographics.xlsx',
    sheet = 'Demographics',
    header = true
);


-- 3. Games

CREATE OR REPLACE TABLE stg_games AS
SELECT
    CAST(UserID AS INTEGER)          AS UserID,
    CAST("Date" AS DATE)             AS "Date",
    CAST(CashGames AS INTEGER)       AS CashGames,
    CAST(Odds AS DOUBLE)             AS Odds,
    CAST(Wagers AS DECIMAL(18, 5))   AS Wagers,
    CAST(Winnings AS DECIMAL(18, 5)) AS Winnings
FROM read_xlsx(
    'data/Games.xlsx',
    sheet = 'Games',
    header = true
);


-- 4. Tournaments

CREATE OR REPLACE TABLE stg_tournaments AS
SELECT
    CAST(UserID AS INTEGER)          AS UserID,
    CAST("Date" AS DATE)             AS "Date",
    CAST(Tournaments AS INTEGER)     AS Tournaments,
    CAST(Odds AS DOUBLE)             AS Odds,
    CAST(Wagers AS DECIMAL(18, 5))   AS Wagers,
    CAST(Winnings AS DECIMAL(18, 5)) AS Winnings
FROM read_xlsx(
    'data/Tournaments.xlsx',
    sheet = 'Tournaments',
    header = true
);


-- 5. Successful Deposits

CREATE OR REPLACE TABLE stg_deposits_successful AS
SELECT
    CAST(UserID AS INTEGER)         AS UserID,
    CAST(DepositID AS BIGINT)       AS DepositID,
    CAST("Date" AS DATE)            AS "Date",
    CAST("Time" AS TIME)            AS "Time",
    CAST(PayMeth AS VARCHAR)        AS PayMeth,
    CAST(PayMethCat AS VARCHAR)     AS PayMethCat,
    CAST(Amount AS DECIMAL(18, 5))  AS Amount,
    CAST(Status AS VARCHAR)         AS Status
FROM read_xlsx(
    'data/Deposits.xlsx',
    sheet = 'SuccessfulDeposits',
    header = true
);


-- 6. Failed Deposits

CREATE OR REPLACE TABLE stg_deposits_failed AS
SELECT
    CAST(UserID AS INTEGER)         AS UserID,
    CAST(DepositID AS BIGINT)       AS DepositID,
    CAST("Date" AS DATE)            AS "Date",
    CAST("Time" AS TIME)            AS "Time",
    CAST(PayMeth AS VARCHAR)        AS PayMeth,
    CAST(PayMethCat AS VARCHAR)     AS PayMethCat,
    CAST(Amount AS DECIMAL(18, 5))  AS Amount,
    CAST(Status AS VARCHAR)         AS Status
FROM read_xlsx(
    'data/Deposits.xlsx',
    sheet = 'FailedDeposits',
    header = true
);


-- 7. Successful Withdrawals

CREATE OR REPLACE TABLE stg_withdrawals_successful AS
SELECT
    CAST(UserID AS INTEGER)         AS UserID,
    CAST(WithdrawalID AS BIGINT)    AS WithdrawalID,
    CAST("Date" AS DATE)            AS "Date",
    CAST("Time" AS TIME)            AS "Time",
    CAST(PayMeth AS VARCHAR)        AS PayMeth,
    CAST(PayMethCat AS VARCHAR)     AS PayMethCat,
    CAST(Amount AS DECIMAL(18, 5))  AS Amount,
    CAST(Status AS VARCHAR)         AS Status
FROM read_xlsx(
    'data/Withdrawals.xlsx',
    sheet = 'SuccessfulWithdrawals',
    header = true
);

-- 8. Failed Withdrawals

CREATE OR REPLACE TABLE stg_withdrawals_failed AS
SELECT
    CAST(UserID AS INTEGER)         AS UserID,
    CAST(WithdrawalID AS BIGINT)    AS WithdrawalID,
    CAST("Date" AS DATE)            AS "Date",
    CAST("Time" AS TIME)            AS "Time",
    CAST(PayMeth AS VARCHAR)        AS PayMeth,
    CAST(PayMethCat AS VARCHAR)     AS PayMethCat,
    CAST(Amount AS DECIMAL(18, 5))  AS Amount,
    CAST(Status AS VARCHAR)         AS Status
FROM read_xlsx(
    'data/Withdrawals.xlsx',
    sheet = 'FailedWithdrawals',
    header = true
);


-- =========================================================
-- 2. EDA
-- =========================================================
-- 1 Verify that all expected tables exist

SHOW TABLES;

-- 2. Initial Data Profiling
-- Review data types, missing values, value ranges,
-- and approximate uniqueness for all staging tables.

-- 2.1 Profile the Country Reference table
SUMMARIZE stg_country_reference;
-- only three rows, no need to EDA

-- 2.2 Profile the Demographics table

SUMMARIZE stg_demographics;

SELECT
    'stg_demographics' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT UserID) AS distinct_user_id,
    COUNT(DISTINCT CountryCode) AS distinct_country_code,
    MIN(DateOfBirth) AS min_date_of_birth,
    MAX(DateOfBirth) AS max_date_of_birth,
    SUM(CASE WHEN UserID IS NULL THEN 1 ELSE 0 END) AS null_user_id,
    SUM(CASE WHEN DateOfBirth IS NULL THEN 1 ELSE 0 END) AS null_date_of_birth,
    SUM(CASE WHEN Gender IS NULL THEN 1 ELSE 0 END) AS null_gender,
    SUM(CASE WHEN CountryCode IS NULL THEN 1 ELSE 0 END) AS null_country_code
FROM stg_demographics;

SELECT
    Gender,
    COUNT(*) AS row_count
FROM stg_demographics
GROUP BY Gender
ORDER BY row_count DESC, Gender;

SELECT
    EXTRACT(YEAR FROM DateOfBirth) AS birth_year,
    COUNT(*) AS row_count
FROM stg_demographics
GROUP BY 1
ORDER BY 1;


-- 2.3 Profile the Games table

SUMMARIZE stg_games;

SELECT
    'stg_games' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT UserID) AS distinct_user_id,
    MIN("Date") AS min_activity_date,
    MAX("Date") AS max_activity_date,
    SUM(CashGames) AS total_cash_games,
    SUM(Wagers) AS total_wagers,
    SUM(Winnings) AS total_winnings,
    AVG(Odds) AS avg_odds,
    SUM(CASE WHEN UserID IS NULL THEN 1 ELSE 0 END) AS null_user_id,
    SUM(CASE WHEN "Date" IS NULL THEN 1 ELSE 0 END) AS null_activity_date,
    SUM(CASE WHEN CashGames IS NULL THEN 1 ELSE 0 END) AS null_cash_games,
    SUM(CASE WHEN Odds IS NULL THEN 1 ELSE 0 END) AS null_odds
FROM stg_games;

SELECT
    UserID,
    COUNT(*) AS rows_per_user
FROM stg_games
GROUP BY UserID
ORDER BY rows_per_user DESC
LIMIT 10;

SELECT
    EXTRACT(YEAR FROM "Date") AS game_year,
    COUNT(*) AS row_count
FROM stg_games
GROUP BY 1
ORDER BY 1;


-- 2.4 Profile the Tournaments table

SUMMARIZE stg_tournaments;

SELECT
    'stg_tournaments' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT UserID) AS distinct_user_id,
    MIN("Date") AS min_activity_date,
    MAX("Date") AS max_activity_date,
    SUM(Tournaments) AS total_tournaments,
    SUM(Wagers) AS total_wagers,
    SUM(Winnings) AS total_winnings,
    AVG(Odds) AS avg_odds,
    SUM(CASE WHEN UserID IS NULL THEN 1 ELSE 0 END) AS null_user_id,
    SUM(CASE WHEN "Date" IS NULL THEN 1 ELSE 0 END) AS null_activity_date,
    SUM(CASE WHEN Tournaments IS NULL THEN 1 ELSE 0 END) AS null_tournaments,
    SUM(CASE WHEN Odds IS NULL THEN 1 ELSE 0 END) AS null_odds
FROM stg_tournaments;

SELECT
    UserID,
    COUNT(*) AS rows_per_user
FROM stg_tournaments
GROUP BY UserID
ORDER BY rows_per_user DESC
LIMIT 10;

SELECT
    EXTRACT(YEAR FROM "Date") AS tournament_year,
    COUNT(*) AS row_count
FROM stg_tournaments
GROUP BY 1
ORDER BY 1;


-- 2.5 Profile the Successful Deposits table

SUMMARIZE stg_deposits_successful;

SELECT
    'stg_deposits_successful' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT UserID) AS distinct_user_id,
    COUNT(DISTINCT DepositID) AS distinct_deposit_id,
    MIN("Date") AS min_activity_date,
    MAX("Date") AS max_activity_date,
    SUM(Amount) AS total_amount,
    AVG(Amount) AS avg_amount,
    SUM(CASE WHEN UserID IS NULL THEN 1 ELSE 0 END) AS null_user_id,
    SUM(CASE WHEN DepositID IS NULL THEN 1 ELSE 0 END) AS null_deposit_id,
    SUM(CASE WHEN Amount IS NULL THEN 1 ELSE 0 END) AS null_amount,
    SUM(CASE WHEN PayMethCat IS NULL THEN 1 ELSE 0 END) AS null_paymethcat
FROM stg_deposits_successful;

SELECT
    PayMethCat,
    COUNT(*) AS row_count,
    ROUND(SUM(Amount), 2) AS total_amount
FROM stg_deposits_successful
GROUP BY PayMethCat
ORDER BY total_amount DESC, row_count DESC;

SELECT
    EXTRACT(YEAR FROM "Date") AS deposit_year,
    COUNT(*) AS row_count
FROM stg_deposits_successful
GROUP BY 1
ORDER BY 1;


-- 2.6 Profile the Failed Deposits table

SUMMARIZE stg_deposits_failed;

SELECT
    'stg_deposits_failed' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT UserID) AS distinct_user_id,
    COUNT(DISTINCT DepositID) AS distinct_deposit_id,
    MIN("Date") AS min_activity_date,
    MAX("Date") AS max_activity_date,
    SUM(Amount) AS total_amount,
    AVG(Amount) AS avg_amount,
    SUM(CASE WHEN UserID IS NULL THEN 1 ELSE 0 END) AS null_user_id,
    SUM(CASE WHEN DepositID IS NULL THEN 1 ELSE 0 END) AS null_deposit_id,
    SUM(CASE WHEN Amount IS NULL THEN 1 ELSE 0 END) AS null_amount,
    SUM(CASE WHEN PayMethCat IS NULL THEN 1 ELSE 0 END) AS null_paymethcat
FROM stg_deposits_failed;

SELECT
    PayMethCat,
    COUNT(*) AS row_count,
    ROUND(SUM(Amount), 2) AS total_amount
FROM stg_deposits_failed
GROUP BY PayMethCat
ORDER BY total_amount DESC, row_count DESC;

SELECT
    EXTRACT(YEAR FROM "Date") AS failed_deposit_year,
    COUNT(*) AS row_count
FROM stg_deposits_failed
GROUP BY 1
ORDER BY 1;


-- 2.7 Profile the Successful Withdrawals table

SUMMARIZE stg_withdrawals_successful;

SELECT
    'stg_withdrawals_successful' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT UserID) AS distinct_user_id,
    COUNT(DISTINCT WithdrawalID) AS distinct_withdrawal_id,
    MIN("Date") AS min_activity_date,
    MAX("Date") AS max_activity_date,
    SUM(Amount) AS total_amount,
    AVG(Amount) AS avg_amount,
    SUM(CASE WHEN UserID IS NULL THEN 1 ELSE 0 END) AS null_user_id,
    SUM(CASE WHEN WithdrawalID IS NULL THEN 1 ELSE 0 END) AS null_withdrawal_id,
    SUM(CASE WHEN Amount IS NULL THEN 1 ELSE 0 END) AS null_amount,
    SUM(CASE WHEN PayMethCat IS NULL THEN 1 ELSE 0 END) AS null_paymethcat
FROM stg_withdrawals_successful;

SELECT
    PayMethCat,
    COUNT(*) AS row_count,
    ROUND(SUM(Amount), 2) AS total_amount
FROM stg_withdrawals_successful
GROUP BY PayMethCat
ORDER BY total_amount DESC, row_count DESC;

SELECT
    EXTRACT(YEAR FROM "Date") AS withdrawal_year,
    COUNT(*) AS row_count
FROM stg_withdrawals_successful
GROUP BY 1
ORDER BY 1;


-- 2.8 Profile the Failed Withdrawals table

SUMMARIZE stg_withdrawals_failed;

SELECT
    'stg_withdrawals_failed' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT UserID) AS distinct_user_id,
    COUNT(DISTINCT WithdrawalID) AS distinct_withdrawal_id,
    MIN("Date") AS min_activity_date,
    MAX("Date") AS max_activity_date,
    SUM(Amount) AS total_amount,
    AVG(Amount) AS avg_amount,
    SUM(CASE WHEN UserID IS NULL THEN 1 ELSE 0 END) AS null_user_id,
    SUM(CASE WHEN WithdrawalID IS NULL THEN 1 ELSE 0 END) AS null_withdrawal_id,
    SUM(CASE WHEN Amount IS NULL THEN 1 ELSE 0 END) AS null_amount,
    SUM(CASE WHEN PayMethCat IS NULL THEN 1 ELSE 0 END) AS null_paymethcat
FROM stg_withdrawals_failed;

SELECT
    PayMethCat,
    COUNT(*) AS row_count,
    ROUND(SUM(Amount), 2) AS total_amount
FROM stg_withdrawals_failed
GROUP BY PayMethCat
ORDER BY total_amount DESC, row_count DESC;

SELECT
    EXTRACT(YEAR FROM "Date") AS failed_withdrawal_year,
    COUNT(*) AS row_count
FROM stg_withdrawals_failed
GROUP BY 1
ORDER BY 1;

-- =========================================================
-- 3. Table Join
-- Q1.	Combine all datasets into 1 table at a player by day level.
-- ER Diagram
-- =========================================================

-- 3.1 demographics + country
CREATE OR REPLACE TEMP TABLE player_dimension AS
SELECT
    d.UserID,
    d.DateOfBirth,
    d.Gender,
    d.CountryCode,
    TRIM(c.Country) AS Country
FROM stg_demographics d
LEFT JOIN stg_country_reference c
    ON d.CountryCode = c.CountryCode;

SELECT *
FROM player_dimension
LIMIT 10;

-- 3.2 games
CREATE OR REPLACE TEMP TABLE game_daily AS
SELECT
    UserID,
    CAST("Date" AS DATE) AS ActivityDate,
    SUM(CashGames) AS CashGames,
    SUM(Wagers) AS CashGameWagers,
    SUM(Winnings) AS CashGameWinnings,
    AVG(Odds) AS CashGameAvgOdds
FROM stg_games
GROUP BY UserID, CAST("Date" AS DATE);

SELECT *
FROM game_daily
LIMIT 10;

-- 3.3 tournaments
CREATE OR REPLACE TEMP TABLE tournament_daily AS
SELECT
    UserID,
    CAST("Date" AS DATE) AS ActivityDate,
    SUM(Tournaments) AS Tournaments,
    SUM(Wagers) AS TournamentWagers,
    SUM(Winnings) AS TournamentWinnings,
    AVG(Odds) AS TournamentAvgOdds
FROM stg_tournaments
GROUP BY UserID, CAST("Date" AS DATE);

SELECT *
FROM tournament_daily
LIMIT 10;

-- 3.4 four transaction tables
CREATE OR REPLACE TEMP TABLE transaction_detail AS
SELECT
    UserID,
    CAST("Date" AS DATE) AS ActivityDate,
    DepositID AS TransactionID,
    "Time",
    PayMeth,
    PayMethCat,
    Amount,
    Status,
    'Deposit_Success' AS source_table,
    'Deposit' AS transaction_type
FROM stg_deposits_successful

UNION ALL

SELECT
    UserID,
    CAST("Date" AS DATE) AS ActivityDate,
    DepositID AS TransactionID,
    "Time",
    PayMeth,
    PayMethCat,
    Amount,
    Status,
    'Deposit_Failed' AS source_table,
    'Deposit' AS transaction_type
FROM stg_deposits_failed

UNION ALL

SELECT
    UserID,
    CAST("Date" AS DATE) AS ActivityDate,
    WithdrawalID AS TransactionID,
    "Time",
    PayMeth,
    PayMethCat,
    Amount,
    Status,
    'Withdrawal_Success' AS source_table,
    'Withdrawal' AS transaction_type
FROM stg_withdrawals_successful

UNION ALL

SELECT
    UserID,
    CAST("Date" AS DATE) AS ActivityDate,
    WithdrawalID AS TransactionID,
    "Time",
    PayMeth,
    PayMethCat,
    Amount,
    Status,
    'Withdrawal_Failed' AS source_table,
    'Withdrawal' AS transaction_type
FROM stg_withdrawals_failed;

CREATE OR REPLACE TEMP TABLE transaction_daily AS
SELECT
    UserID,
    ActivityDate,
    COUNT(*) AS TransactionCount,
    SUM(CASE WHEN transaction_type = 'Deposit' AND Status = 'S' THEN Amount ELSE 0 END) AS DepositAmount,
    SUM(CASE WHEN transaction_type = 'Deposit' AND Status = 'F' THEN Amount ELSE 0 END) AS DepositFailedAmount,
    SUM(CASE WHEN transaction_type = 'Deposit' AND Status = 'S' THEN 1 ELSE 0 END) AS DepositSuccessCount,
    SUM(CASE WHEN transaction_type = 'Deposit' AND Status = 'F' THEN 1 ELSE 0 END) AS DepositFailedCount,
    SUM(CASE WHEN transaction_type = 'Withdrawal' AND Status = 'S' THEN Amount ELSE 0 END) AS WithdrawalAmount,
    SUM(CASE WHEN transaction_type = 'Withdrawal' AND Status = 'F' THEN Amount ELSE 0 END) AS WithdrawalFailedAmount,
    SUM(CASE WHEN transaction_type = 'Withdrawal' AND Status = 'S' THEN 1 ELSE 0 END) AS WithdrawalSuccessCount,
    SUM(CASE WHEN transaction_type = 'Withdrawal' AND Status = 'F' THEN 1 ELSE 0 END) AS WithdrawalFailedCount
FROM transaction_detail
GROUP BY UserID, ActivityDate;

SELECT *
FROM transaction_daily
LIMIT 10;

-- 3.5 all activity dates
-- DISTINCT UserID, Date -> player_day_spine
CREATE OR REPLACE TEMP TABLE player_day_spine AS
SELECT DISTINCT UserID, ActivityDate
FROM (
    SELECT UserID, CAST("Date" AS DATE) AS ActivityDate FROM stg_games
    UNION ALL
    SELECT UserID, CAST("Date" AS DATE) AS ActivityDate FROM stg_tournaments
    UNION ALL
    SELECT UserID, CAST("Date" AS DATE) AS ActivityDate FROM stg_deposits_successful
    UNION ALL
    SELECT UserID, CAST("Date" AS DATE) AS ActivityDate FROM stg_deposits_failed
    UNION ALL
    SELECT UserID, CAST("Date" AS DATE) AS ActivityDate FROM stg_withdrawals_successful
    UNION ALL
    SELECT UserID, CAST("Date" AS DATE) AS ActivityDate FROM stg_withdrawals_failed
) src;

SELECT *
FROM player_day_spine
LIMIT 10;

-- 3.6 final player-day fact table
CREATE OR REPLACE TABLE q1_player_day AS
SELECT
    s.UserID,
    CAST(s.ActivityDate AS DATE) AS ActivityDate,
    p.Gender,
    CASE
        WHEN p.DateOfBirth IS NULL THEN NULL
        ELSE (
            DATE_DIFF('year', p.DateOfBirth, CAST(s.ActivityDate AS DATE))
            - CASE
                WHEN DATE_PART('month', CAST(s.ActivityDate AS DATE)) < DATE_PART('month', p.DateOfBirth)
                  OR (
                        DATE_PART('month', CAST(s.ActivityDate AS DATE)) = DATE_PART('month', p.DateOfBirth)
                        AND DATE_PART('day', CAST(s.ActivityDate AS DATE)) < DATE_PART('day', p.DateOfBirth)
                     )
                THEN 1
                ELSE 0
              END
        )
    END AS Age,
    p.Country,
    p.CountryCode,
    COALESCE(g.CashGames, 0) AS CashGames,
    COALESCE(g.CashGameWagers, 0) AS CashGameWagers,
    COALESCE(g.CashGameWinnings, 0) AS CashGameWinnings,
    CASE WHEN g.CashGameAvgOdds IS NULL THEN NULL ELSE g.CashGameAvgOdds END AS CashGameAvgOdds,
    COALESCE(t.Tournaments, 0) AS Tournaments,
    COALESCE(t.TournamentWagers, 0) AS TournamentWagers,
    COALESCE(t.TournamentWinnings, 0) AS TournamentWinnings,
    CASE WHEN t.TournamentAvgOdds IS NULL THEN NULL ELSE t.TournamentAvgOdds END AS TournamentAvgOdds,
    COALESCE(tr.DepositAmount, 0) AS DepositAmount,
    COALESCE(tr.DepositFailedAmount, 0) AS DepositFailedAmount,
    COALESCE(tr.DepositSuccessCount, 0) AS DepositSuccessCount,
    COALESCE(tr.DepositFailedCount, 0) AS DepositFailedCount,
    COALESCE(tr.WithdrawalAmount, 0) AS WithdrawalAmount,
    COALESCE(tr.WithdrawalFailedAmount, 0) AS WithdrawalFailedAmount,
    COALESCE(tr.WithdrawalSuccessCount, 0) AS WithdrawalSuccessCount,
    COALESCE(tr.WithdrawalFailedCount, 0) AS WithdrawalFailedCount
FROM player_day_spine s
LEFT JOIN player_dimension p
    ON p.UserID = s.UserID
LEFT JOIN game_daily g
    ON g.UserID = s.UserID
   AND g.ActivityDate = s.ActivityDate
LEFT JOIN tournament_daily t
    ON t.UserID = s.UserID
   AND t.ActivityDate = s.ActivityDate
LEFT JOIN transaction_daily tr
    ON tr.UserID = s.UserID
   AND tr.ActivityDate = s.ActivityDate;


SELECT *
FROM q1_player_day
LIMIT 10;

-- =========================================================
-- 4. Q2: Monthly Aggregation:
-- Create a table at YYYY-MM level, providing monthly
-- statistics on the volume of players, total wagers and winnings, 
-- and the average odds by game type. 
-- =========================================================

CREATE OR REPLACE TABLE q2_player_month AS
SELECT
    CAST(DATE_TRUNC('month', ActivityDate) AS DATE) AS MonthDate,
    'Cash Games' AS GameType,
    COUNT(DISTINCT CASE WHEN CashGames > 0 OR CashGameWagers > 0 OR CashGameWinnings > 0 THEN UserID END) AS PlayerVolume,
    SUM(CashGameWagers) AS TotalWagers,
    SUM(CashGameWinnings) AS TotalWinnings,
    AVG(CASE WHEN CashGameAvgOdds IS NOT NULL AND CashGameAvgOdds > 0 THEN CashGameAvgOdds END) AS AverageOdds
FROM q1_player_day
WHERE CashGames > 0 OR CashGameWagers > 0 OR CashGameWinnings > 0 OR CashGameAvgOdds IS NOT NULL
GROUP BY CAST(DATE_TRUNC('month', ActivityDate) AS DATE)

UNION ALL

SELECT
    CAST(DATE_TRUNC('month', ActivityDate) AS DATE) AS MonthDate,
    'Tournaments' AS GameType,
    COUNT(DISTINCT CASE WHEN Tournaments > 0 OR TournamentWagers > 0 OR TournamentWinnings > 0 THEN UserID END) AS PlayerVolume,
    SUM(TournamentWagers) AS TotalWagers,
    SUM(TournamentWinnings) AS TotalWinnings,
    AVG(CASE WHEN TournamentAvgOdds IS NOT NULL AND TournamentAvgOdds > 0 THEN TournamentAvgOdds END) AS AverageOdds
FROM q1_player_day
WHERE Tournaments > 0 OR TournamentWagers > 0 OR TournamentWinnings > 0 OR TournamentAvgOdds IS NOT NULL
GROUP BY CAST(DATE_TRUNC('month', ActivityDate) AS DATE)
ORDER BY MonthDate, GameType;

SELECT *
FROM q2_player_month
ORDER BY MonthDate;
