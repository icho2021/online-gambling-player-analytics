#!/usr/bin/env python3
"""Generate a synthetic dataset with the same shape as the original source files.

The original exercise shipped six workbooks of player activity. Those files are
not redistributed here, so this script produces stand-ins with identical sheet
names, column names and types. The numbers are random; only the structure is
real, which is enough to run the SQL and the Python end to end.

    python -m src.make_sample_data
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260929)
START = date(2015, 2, 1)
DAYS = 365

COUNTRIES = [(1, "Canada"), (2, "US"), (3, "Europe")]
PAY_METHODS = [
    ("VISA", "EEA debit/credit card"),
    ("MASTERCARD", "EEA debit/credit card"),
    ("NETELLER", "E-wallet"),
    ("SKRILL", "E-wallet"),
    ("BANK TRANSFER", "Bank transfer"),
]


def demographics(n_players: int) -> pd.DataFrame:
    return pd.DataFrame({
        "UserID": np.arange(1, n_players + 1),
        "DateOfBirth": [
            pd.Timestamp(date(1950, 1, 1) + timedelta(days=int(d)))
            for d in RNG.integers(0, 55 * 365, n_players)
        ],
        "Gender": RNG.choice(["M", "F"], n_players, p=[0.78, 0.22]),
        "CountryCode": RNG.choice([c[0] for c in COUNTRIES], n_players, p=[0.55, 0.28, 0.17]),
    })


def _activity(n_players: int, rows: int, count_col: str) -> pd.DataFrame:
    """Daily play rows. A few heavy players generate most of the volume."""
    weights = RNG.pareto(1.4, n_players) + 1
    weights /= weights.sum()
    users = RNG.choice(np.arange(1, n_players + 1), rows, p=weights)
    offsets = RNG.integers(0, DAYS, rows)
    wagers = np.round(RNG.lognormal(1.2, 1.3, rows), 5)
    return pd.DataFrame({
        "UserID": users,
        "Date": [pd.Timestamp(START + timedelta(days=int(o))) for o in offsets],
        count_col: RNG.integers(1, 12, rows),
        "Odds": np.round(RNG.lognormal(1.0, 0.8, rows), 9),
        "Wagers": wagers,
        "Winnings": np.round(wagers * RNG.choice([0.0, 0.5, 0.95, 1.8], rows, p=[0.42, 0.2, 0.25, 0.13]), 5),
    })


def _money(n_players: int, rows: int, id_col: str, mean_log: float, success_rate: float) -> pd.DataFrame:
    users = RNG.integers(1, n_players + 1, rows)
    offsets = RNG.integers(0, DAYS, rows)
    methods = RNG.integers(0, len(PAY_METHODS), rows)
    return pd.DataFrame({
        "UserID": users,
        id_col: np.arange(1, rows + 1),
        "Date": [pd.Timestamp(START + timedelta(days=int(o))) for o in offsets],
        "Time": [time(int(h), int(m), int(s)) for h, m, s in
                 zip(RNG.integers(0, 24, rows), RNG.integers(0, 60, rows), RNG.integers(0, 60, rows))],
        "PayMeth": [PAY_METHODS[i][0] for i in methods],
        "PayMethCat": [PAY_METHODS[i][1] for i in methods],
        "Amount": np.round(RNG.lognormal(mean_log, 1.1, rows), 5),
        "Status": RNG.choice(["S", "F"], rows, p=[success_rate, 1 - success_rate]),
    })


def main() -> int:
    ap = argparse.ArgumentParser(description="Write synthetic source workbooks")
    ap.add_argument("--out", type=Path, default=Path("data"))
    ap.add_argument("--players", type=int, default=5000)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    n = args.players

    pd.DataFrame(COUNTRIES, columns=["CountryCode", "Country"]).to_excel(
        args.out / "Country Reference Table.xlsx", sheet_name="Sheet1", index=False)
    demographics(n).to_excel(args.out / "Demographics.xlsx", sheet_name="Demographics", index=False)
    _activity(n, 51_763, "CashGames").to_excel(args.out / "Games.xlsx", sheet_name="Games", index=False)
    _activity(n, 82_831, "Tournaments").to_excel(args.out / "Tournaments.xlsx", sheet_name="Tournaments", index=False)

    dep = _money(n, 295_088, "DepositID", 4.0, 0.758)
    with pd.ExcelWriter(args.out / "Deposits.xlsx") as w:
        dep[dep.Status == "F"].to_excel(w, sheet_name="FailedDeposits", index=False)
        dep[dep.Status == "S"].to_excel(w, sheet_name="SuccessfulDeposits", index=False)

    wdr = _money(n, 32_307, "WithdrawalID", 4.4, 0.532)
    with pd.ExcelWriter(args.out / "Withdrawals.xlsx") as w:
        wdr[wdr.Status == "F"].to_excel(w, sheet_name="FailedWithdrawals", index=False)
        wdr[wdr.Status == "S"].to_excel(w, sheet_name="SuccessfulWithdrawals", index=False)

    total = 51_763 + 82_831 + 295_088 + 32_307 + n + len(COUNTRIES)
    print(f"Wrote six workbooks to {args.out}/: {n:,} synthetic players, {total:,} rows.")
    print("Numbers are random. Only the structure matches the original source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
