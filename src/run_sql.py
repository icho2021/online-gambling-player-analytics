import re
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = PROJECT_ROOT / "sql" / "player_day_and_monthly.sql"
Q1_OUTPUT_XLSX = PROJECT_ROOT / "output" / "player_day.xlsx"
Q1_OUTPUT_CSV = PROJECT_ROOT / "output" / "player_day.csv"
Q2_OUTPUT_XLSX = PROJECT_ROOT / "output" / "monthly_by_game_type.xlsx"
Q2_OUTPUT_CSV = PROJECT_ROOT / "output" / "monthly_by_game_type.csv"
# Use a separate runtime database to avoid lock conflicts with DBeaver or another DuckDB process
# that may already be holding the original file open.
DB_PATH = PROJECT_ROOT / "output" / "player_analytics.duckdb"


(PROJECT_ROOT / "output").mkdir(exist_ok=True)


def sanitize_sql(sql_text: str) -> str:
    """Remove the xlsx export block so the SQL can run in environments without the xlsx extension."""
    cleaned = re.sub(
        r"(?is)\n\s*INSTALL\s+xlsx\s*;\s*LOAD\s+xlsx\s*;.*$",
        "",
        sql_text,
    )
    return cleaned.strip() + "\n"


def normalize_date_columns(df: pd.DataFrame, date_columns: list[str]) -> pd.DataFrame:
    normalized = df.copy()
    for column in date_columns:
        if column in normalized.columns:
            normalized[column] = pd.to_datetime(normalized[column], errors="raise").dt.date
    return normalized


def export_excel_with_date_format(
    df: pd.DataFrame,
    output_path: Path,
    date_columns: list[str],
) -> None:
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
        worksheet = writer.sheets["Sheet1"]
        for column in date_columns:
            if column not in df.columns:
                continue
            col_idx = df.columns.get_loc(column) + 1
            for row in range(2, len(df) + 2):
                worksheet.cell(row=row, column=col_idx).number_format = "yyyy-mm-dd"


def main() -> None:
    sql_text = SQL_PATH.read_text(encoding="utf-8")
    sql_text = sanitize_sql(sql_text)

    con = duckdb.connect(database=str(DB_PATH))

    try:
        con.execute(sql_text)

        q1_df = con.execute(
            """
            SELECT
                UserID,
                ActivityDate,
                Gender,
                Age,
                Country,
                CountryCode,
                CashGames,
                CashGameWagers,
                CashGameWinnings,
                CashGameAvgOdds,
                Tournaments,
                TournamentWagers,
                TournamentWinnings,
                TournamentAvgOdds,
                DepositAmount,
                DepositFailedAmount,
                DepositSuccessCount,
                DepositFailedCount,
                WithdrawalAmount,
                WithdrawalFailedAmount,
                WithdrawalSuccessCount,
                WithdrawalFailedCount
            FROM q1_player_day
            ORDER BY ActivityDate, UserID
            """
        ).fetchdf()

        q2_df = con.execute(
            """
            SELECT *
            FROM q2_player_month
            ORDER BY MonthDate
            """
        ).fetchdf()

        q1_df = normalize_date_columns(q1_df, ["ActivityDate"])
        q2_df = normalize_date_columns(q2_df, ["MonthDate"])

        export_excel_with_date_format(q1_df, Q1_OUTPUT_XLSX, ["ActivityDate"])
        q1_df.to_csv(Q1_OUTPUT_CSV, index=False)
        export_excel_with_date_format(q2_df, Q2_OUTPUT_XLSX, ["MonthDate"])
        q2_df.to_csv(Q2_OUTPUT_CSV, index=False)

        print(f"Saved Q1 Excel: {Q1_OUTPUT_XLSX}")
        print(f"Saved Q1 CSV: {Q1_OUTPUT_CSV}")
        print(f"Saved Q2 Excel: {Q2_OUTPUT_XLSX}")
        print(f"Saved Q2 CSV: {Q2_OUTPUT_CSV}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
