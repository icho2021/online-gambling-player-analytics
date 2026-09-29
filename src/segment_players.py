from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows


# =========================================================
# 4. Segmentation Workflow
# =========================================================
# Required Q4 output:
#   1. one player-level table containing both a Value Segment and a Risk
#      Segment for every player;
#   2. aggregate profiles that explain the demographics and behaviour of each
#      segment; and
#   3. enough diagnostics and methodology notes to reproduce and defend the
#      result.
#
# The workflow therefore places every player on two independent axes:
#
#   Value axis  -> how much the player is worth to the operator.
#                  PRIMARY SOLUTION: KMeans on standardised continuous LRFM+
#                  wallet features, with clusters ranked by net gaming revenue
#                  per player.
#                  VALIDATION BASELINE: rule-based RFM quintile scoring.
#                  A behavioural archetype label is kept alongside the value
#                  tier so the multi-dimensional cluster shape is not lost.
#
#   Risk axis   -> which players should receive higher review priority.
#                  Two rule-based scores (AML and Responsible Gambling) built
#                  from absolute triggers, not equal-sized buckets, so that
#                  "High Risk" stays a genuine tail rather than one third of
#                  the book.
#
# These are review indicators, not findings of money laundering, gambling
# harm, or legal non-compliance. The two axes are deliberately kept separate
# and then crossed in the Value x Risk action matrix.

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT
OUTPUT_XLSX = PROJECT_ROOT / "output" / "player_segments.xlsx"

VALUE_LABELS = ["Low Value", "Medium Value", "High Value", "Premium"]
RISK_LABELS = ["Low Risk", "Medium Risk", "High Risk"]
IGAMING_MIN_AGE = 19

# KMeans configuration. K is a business choice (four tiers are actionable for
# CRM); 4.9 reports the statistical diagnostics behind that choice.
KMEANS_K = 4
KMEANS_SEED = 42
KMEANS_N_INIT = 20
KMEANS_K_RANGE = range(2, 9)
SILHOUETTE_SAMPLE = 1500

# --- AML trigger thresholds (see 4.6) ---------------------------------------
AML_PASSTHROUGH_MIN_DEPOSIT = 5_000.0
AML_PASSTHROUGH_MAX_PLAYTHROUGH = 0.10
AML_PASSTHROUGH_MIN_WITHDRAWAL_RATIO = 0.80
AML_RATIO_MIN_DEPOSIT = 2_000.0
AML_RATIO_THRESHOLD = 1.50
AML_CARD_TESTING_MIN_FAILS = 10
AML_CARD_TESTING_MIN_RATE = 0.50
AML_LARGE_WITHDRAWAL_PCTL = 0.99

# --- Responsible Gambling trigger thresholds (see 4.6) ----------------------
RG_CHASING_MIN_DAYS = 10
RG_ESCALATION_RATIO = 2.00
RG_ESCALATION_MIN_TENURE_DAYS = 180
RG_LOSS_VELOCITY_PCTL = 0.95
RG_ABSOLUTE_LOSS_PCTL = 0.95
RG_SUSTAINED_STREAK_DAYS = 30

# --- Risk tier cut-offs on the flag point scores ----------------------------
RISK_HIGH_AML_POINTS = 3
RISK_HIGH_RG_POINTS = 4
RISK_MEDIUM_AML_POINTS = 1
RISK_MEDIUM_RG_POINTS = 2


# =========================================================
# 4.1 Load and prepare the Q1 result
# =========================================================

def resolve_q1_path(explicit_path: Path | None = None) -> Path:
    """Find the player-day table produced by the SQL step."""
    candidates = [
        explicit_path,
        PROJECT_ROOT / "output" / "player_day.xlsx",
        PROJECT_ROOT / "output" / "player_day.xlsx",
        Path.cwd() / "output" / "player_day.xlsx",
    ]
    checked: list[Path] = []
    for candidate in candidates:
        if candidate is None:
            continue
        candidate = candidate.expanduser().resolve()
        if candidate not in checked:
            checked.append(candidate)
        if candidate.exists():
            return candidate

    checked_text = "\n  - ".join(str(path) for path in checked)
    raise FileNotFoundError(
        "Could not locate output/player_day.xlsx. Use --input to provide its path. "
        f"Checked:\n  - {checked_text}"
    )

def load_q1_result(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing Q1 output: {path}")

    df = pd.read_excel(path)
    required_columns = [
        "UserID",
        "ActivityDate",
        "Gender",
        "Age",
        "Country",
        "CountryCode",
        "CashGames",
        "CashGameWagers",
        "CashGameWinnings",
        "CashGameAvgOdds",
        "Tournaments",
        "TournamentWagers",
        "TournamentWinnings",
        "DepositAmount",
        "DepositSuccessCount",
        "DepositFailedCount",
        "WithdrawalAmount",
        "WithdrawalSuccessCount",
        "WithdrawalFailedCount",
    ]
    missing = sorted(set(required_columns) - set(df.columns))
    if missing:
        raise ValueError(f"Q1 output is missing required columns: {missing}")

    if df.empty:
        raise ValueError("Q1 output contains no records.")

    df["ActivityDate"] = pd.to_datetime(df["ActivityDate"], errors="coerce")
    if df["ActivityDate"].isna().any():
        raise ValueError("Q1 output contains invalid ActivityDate values.")

    # AvgOdds is legitimately null on days with no play, so it is validated
    # separately from the columns that must always carry a value.
    numeric_columns = [
        "UserID",
        "Age",
        "CountryCode",
        "CashGames",
        "CashGameWagers",
        "CashGameWinnings",
        "Tournaments",
        "TournamentWagers",
        "TournamentWinnings",
        "DepositAmount",
        "DepositSuccessCount",
        "DepositFailedCount",
        "WithdrawalAmount",
        "WithdrawalSuccessCount",
        "WithdrawalFailedCount",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
        if df[column].isna().any():
            raise ValueError(f"Q1 output contains invalid numeric values in {column}.")

    df["CashGameAvgOdds"] = pd.to_numeric(df["CashGameAvgOdds"], errors="coerce")

    df["UserID"] = df["UserID"].astype("int64")
    df["Age"] = df["Age"].astype("int64")
    df["CountryCode"] = df["CountryCode"].astype("int64")

    df["Gender"] = df["Gender"].astype("string").str.strip()
    df["Country"] = df["Country"].astype("string").str.strip()

    if df.duplicated(["UserID", "ActivityDate"]).any():
        raise ValueError("Q1 output is not unique at player-by-day grain.")

    return df.sort_values(["UserID", "ActivityDate"]).reset_index(drop=True)


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    # A zero denominator means the ratio is undefined, not equal to the
    # numerator. Returning NaN keeps the dimensionality honest; every caller
    # decides explicitly how an undefined ratio should be treated.
    return numerator / denominator.replace(0, np.nan)


def signed_log1p(series: pd.Series) -> pd.Series:
    # Net gaming revenue is negative for the players who finished ahead, so the
    # plain log1p used for one-sided amounts is not applicable here.
    return np.sign(series) * np.log1p(np.abs(series))


def assign_age_band(series: pd.Series) -> pd.Series:
    """Create descriptive age bands without deleting or correcting source ages."""
    return pd.cut(
        series,
        bins=[-np.inf, 18, 24, 34, 44, 54, 64, np.inf],
        labels=["Under 19", "19-24", "25-34", "35-44", "45-54", "55-64", "65+"],
    )


# =========================================================
# 4.2 Player-level feature engineering
# =========================================================
# Two passes over the daily grain:
#   a) sequence features that only exist at day level (loss chasing, deposit
#      escalation, consecutive-day streaks). These are the responsible-gambling
#      markers of harm and cannot be recovered after aggregation.
#   b) the standard player-level roll-up.

def build_daily_sequence_features(working: pd.DataFrame) -> pd.DataFrame:
    grouped = working.groupby("UserID", sort=False)
    working = working.copy()
    working["PrevNetGaming"] = grouped["NetGaming"].shift(1)
    working["PrevDate"] = grouped["ActivityDate"].shift(1)
    working["GapDays"] = (working["ActivityDate"] - working["PrevDate"]).dt.days

    # Loss chasing: a deposit placed on the calendar day immediately after a
    # day on which the player lost money.
    working["ChaseFlag"] = (
        (working["PrevNetGaming"] > 0)
        & (working["GapDays"] <= 1)
        & (working["DepositAmount"] > 0)
    ).astype(int)

    # Consecutive active-day streaks. A gap of anything other than one day
    # (including the first record of a player, where GapDays is null) opens a
    # new run.
    working["StreakBreak"] = (working["GapDays"] != 1).astype(int)
    working["StreakID"] = working.groupby("UserID", sort=False)["StreakBreak"].cumsum()
    streaks = (
        working.groupby(["UserID", "StreakID"], sort=False)
        .size()
        .groupby("UserID")
        .max()
        .rename("MaxConsecutiveActiveDays")
    )

    # Deposit escalation: average daily deposit over the player's final 90 days
    # of activity against the average over everything before it.
    last_date = grouped["ActivityDate"].transform("max")
    working["DaysBeforeEnd"] = (last_date - working["ActivityDate"]).dt.days
    recent_mask = working["DaysBeforeEnd"] <= 89
    recent_avg = (
        working.loc[recent_mask].groupby("UserID")["DepositAmount"].mean().rename("RecentAvgDeposit")
    )
    earlier_avg = (
        working.loc[~recent_mask].groupby("UserID")["DepositAmount"].mean().rename("EarlierAvgDeposit")
    )

    sequence = (
        working.groupby("UserID", as_index=True)
        .agg(
            LossChasingDays=("ChaseFlag", "sum"),
            MaxDailyDeposit=("DepositAmount", "max"),
            MaxDailyLoss=("NetGaming", "max"),
        )
        .join([streaks, recent_avg, earlier_avg])
        .reset_index()
    )
    sequence["DepositEscalationRatio"] = safe_divide(
        sequence["RecentAvgDeposit"], sequence["EarlierAvgDeposit"]
    )
    # A player who had no earlier deposit baseline but starts depositing in the
    # final 90 days would otherwise receive NaN and silently miss the escalation
    # rule. Keep that case as an explicit, auditable indicator.
    sequence["RecentDepositWithoutEarlierBaseline"] = (
        (sequence["RecentAvgDeposit"].fillna(0) > 0)
        & (sequence["EarlierAvgDeposit"].fillna(0) == 0)
    ).astype(int)
    return sequence


def build_player_features(q1_df: pd.DataFrame) -> pd.DataFrame:
    dataset_max_date = q1_df["ActivityDate"].max()

    working = q1_df.copy()
    working["WagerAmount"] = working["CashGameWagers"] + working["TournamentWagers"]
    working["WinningAmount"] = working["CashGameWinnings"] + working["TournamentWinnings"]
    # NetGaming is positive when the operator wins, i.e. it is gross gaming
    # revenue. This, not turnover, is the monetary value of a player.
    working["NetGaming"] = working["WagerAmount"] - working["WinningAmount"]
    working["ActivityFlag"] = 1

    sequence = build_daily_sequence_features(working)

    player_df = (
        working.groupby("UserID", as_index=False)
        .agg(
            FirstActivityDate=("ActivityDate", "min"),
            LastActivityDate=("ActivityDate", "max"),
            ActivityDays=("ActivityFlag", "sum"),
            Gender=("Gender", "last"),
            Age=("Age", "last"),
            Country=("Country", "last"),
            CountryCode=("CountryCode", "last"),
            CashGames=("CashGames", "sum"),
            CashGameWagers=("CashGameWagers", "sum"),
            CashGameWinnings=("CashGameWinnings", "sum"),
            AvgCashOdds=("CashGameAvgOdds", "mean"),
            Tournaments=("Tournaments", "sum"),
            TournamentWagers=("TournamentWagers", "sum"),
            TournamentWinnings=("TournamentWinnings", "sum"),
            WagerAmount=("WagerAmount", "sum"),
            WinningAmount=("WinningAmount", "sum"),
            NetGaming=("NetGaming", "sum"),
            DepositAmount=("DepositAmount", "sum"),
            DepositSuccessCount=("DepositSuccessCount", "sum"),
            DepositFailedCount=("DepositFailedCount", "sum"),
            WithdrawalAmount=("WithdrawalAmount", "sum"),
            WithdrawalSuccessCount=("WithdrawalSuccessCount", "sum"),
            WithdrawalFailedCount=("WithdrawalFailedCount", "sum"),
        )
        .merge(sequence, on="UserID", how="left")
    )

    # --- Lifecycle -----------------------------------------------------------
    player_df["RecencyDays"] = (dataset_max_date - player_df["LastActivityDate"]).dt.days
    player_df["TenureDays"] = (
        player_df["LastActivityDate"] - player_df["FirstActivityDate"]
    ).dt.days
    player_df["Frequency"] = player_df["ActivityDays"].astype(int)
    player_df["ActivityRate"] = safe_divide(
        player_df["Frequency"], player_df["TenureDays"] + 1
    ).fillna(1.0)

    # Age is retained exactly as recorded. Values below the minimum legal age
    # for online gaming are surfaced for data-quality and eligibility review,
    # but are not removed and are not used by either model.
    player_df["AgeBand"] = assign_age_band(player_df["Age"])
    player_df["AgeEligibilityFlag"] = (
        player_df["Age"] < IGAMING_MIN_AGE
    ).astype(int)

    # --- Money flow ----------------------------------------------------------
    # Undefined ratios are filled only where zero is the correct business
    # reading; the "no deposit at all" case is carried as its own AML flag.
    player_df["WithdrawalToDeposit"] = safe_divide(
        player_df["WithdrawalAmount"], player_df["DepositAmount"]
    ).fillna(0.0)
    player_df["Playthrough"] = safe_divide(
        player_df["WagerAmount"], player_df["DepositAmount"]
    )
    player_df["DepositFailedRate"] = safe_divide(
        player_df["DepositFailedCount"],
        player_df["DepositSuccessCount"] + player_df["DepositFailedCount"],
    ).fillna(0.0)
    player_df["WithdrawalFailedRate"] = safe_divide(
        player_df["WithdrawalFailedCount"],
        player_df["WithdrawalSuccessCount"] + player_df["WithdrawalFailedCount"],
    ).fillna(0.0)
    total_attempts = (
        player_df["DepositSuccessCount"]
        + player_df["DepositFailedCount"]
        + player_df["WithdrawalSuccessCount"]
        + player_df["WithdrawalFailedCount"]
    )
    player_df["FailedTxnRate"] = safe_divide(
        player_df["DepositFailedCount"] + player_df["WithdrawalFailedCount"],
        total_attempts,
    ).fillna(0.0)

    # --- Play mix and intensity ---------------------------------------------
    player_df["CashGameShare"] = safe_divide(
        player_df["CashGameWagers"], player_df["WagerAmount"]
    ).fillna(0.0)
    player_df["TournamentShare"] = safe_divide(
        player_df["TournamentWagers"], player_df["WagerAmount"]
    ).fillna(0.0)
    player_df["WagerPerActiveDay"] = safe_divide(
        player_df["WagerAmount"], player_df["Frequency"]
    ).fillna(0.0)
    player_df["NetLossPerActiveDay"] = safe_divide(
        player_df["NetGaming"], player_df["Frequency"]
    ).fillna(0.0)

    player_df["MaxConsecutiveActiveDays"] = (
        player_df["MaxConsecutiveActiveDays"].fillna(1).astype(int)
    )
    player_df["LossChasingDays"] = player_df["LossChasingDays"].fillna(0).astype(int)

    return player_df


# =========================================================
# 4.3 Solution 1B — value validation baseline: RFM scorecard
# =========================================================
# This is NOT a second delivered segmentation. It is a transparent benchmark
# used to test whether the primary KMeans result ranks players in a broadly
# similar way. Monetary uses net gaming revenue rather than turnover, so both
# methods use the same business definition of value.

def quantile_score(series: pd.Series, bins: int = 5, reverse: bool = False) -> pd.Series:
    # Average ranks keep identical observed values in the same score. Using
    # method="first" would assign tied players to different quintiles merely
    # because of row order.
    percentile_rank = series.rank(method="average", pct=True)
    scored = np.ceil(percentile_rank * bins).clip(1, bins).astype(int)
    if reverse:
        scored = bins + 1 - scored
    return scored


def build_rfm_scores(player_df: pd.DataFrame) -> pd.DataFrame:
    rfm = player_df.copy()
    rfm["RecencyScore"] = quantile_score(rfm["RecencyDays"], bins=5, reverse=True)
    rfm["FrequencyScore"] = quantile_score(rfm["Frequency"], bins=5)
    rfm["MonetaryScore"] = quantile_score(rfm["NetGaming"], bins=5)
    rfm["RFMScore"] = (
        rfm["RecencyScore"] + rfm["FrequencyScore"] + rfm["MonetaryScore"]
    )

    def score_to_label(score: int) -> str:
        if score >= 13:
            return "Premium"
        if score >= 10:
            return "High Value"
        if score >= 7:
            return "Medium Value"
        return "Low Value"

    rfm["Value Segment (RFM Score)"] = rfm["RFMScore"].map(score_to_label)
    return rfm


# =========================================================
# 4.4 Solution 1A — primary value model: KMeans on continuous LRFM+
# =========================================================
# RFM is the feature framework; KMeans is the clustering algorithm. They are
# not competing concepts. The primary model uses continuous, transformed RFM
# features plus Deposit and Tenure, rather than clustering pre-bucketed scores.

KMEANS_FEATURES = ["Recency", "Frequency", "Monetary", "Deposit", "Tenure"]


def standardize_for_kmeans(player_df: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    # Five LRFM-style dimensions rather than three: adding wallet size and
    # lifecycle length is what makes the clustering multi-dimensional instead
    # of a relabelled RFM score.
    features = pd.DataFrame(
        {
            "Recency": np.log1p(player_df["RecencyDays"]),
            "Frequency": np.log1p(player_df["Frequency"]),
            "Monetary": signed_log1p(player_df["NetGaming"]),
            "Deposit": np.log1p(player_df["DepositAmount"]),
            "Tenure": np.log1p(player_df["TenureDays"]),
        }
    )
    means = features.mean()
    stds = features.std(ddof=0).replace(0, 1)
    scaled = (features - means) / stds
    return scaled.to_numpy(), features


def kmeans_plus_plus_init(x: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    n_samples, n_features = x.shape
    centroids = np.empty((k, n_features), dtype=float)
    first_idx = rng.integers(n_samples)
    centroids[0] = x[first_idx]
    closest_dist_sq = np.sum((x - centroids[0]) ** 2, axis=1)

    for centroid_idx in range(1, k):
        total = closest_dist_sq.sum()
        if total == 0:
            centroids[centroid_idx] = x[rng.integers(n_samples)]
            continue
        probs = closest_dist_sq / total
        next_idx = rng.choice(n_samples, p=probs)
        centroids[centroid_idx] = x[next_idx]
        dist_sq = np.sum((x - centroids[centroid_idx]) ** 2, axis=1)
        closest_dist_sq = np.minimum(closest_dist_sq, dist_sq)

    return centroids


def run_kmeans_once(
    x: np.ndarray,
    k: int = KMEANS_K,
    max_iter: int = 100,
    random_state: int = KMEANS_SEED,
) -> tuple[np.ndarray, np.ndarray, float]:
    rng = np.random.default_rng(random_state)
    centroids = kmeans_plus_plus_init(x, k, rng)

    for _ in range(max_iter):
        distances = np.sum((x[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
        labels = distances.argmin(axis=1)

        new_centroids = centroids.copy()
        for cluster_idx in range(k):
            cluster_points = x[labels == cluster_idx]
            if len(cluster_points) == 0:
                farthest_idx = distances.min(axis=1).argmax()
                new_centroids[cluster_idx] = x[farthest_idx]
            else:
                new_centroids[cluster_idx] = cluster_points.mean(axis=0)

        shift = np.abs(new_centroids - centroids).max()
        centroids = new_centroids
        if shift < 1e-6:
            break

    distances = np.sum((x[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
    labels = distances.argmin(axis=1)
    inertia = float(np.min(distances, axis=1).sum())
    return labels, centroids, inertia


def run_kmeans(
    x: np.ndarray,
    k: int = KMEANS_K,
    max_iter: int = 100,
    random_state: int = KMEANS_SEED,
    n_init: int = KMEANS_N_INIT,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return the lowest-inertia result across multiple KMeans++ starts."""
    best_labels: np.ndarray | None = None
    best_centroids: np.ndarray | None = None
    best_inertia = np.inf

    for initialization in range(n_init):
        labels, centroids, inertia = run_kmeans_once(
            x,
            k=k,
            max_iter=max_iter,
            random_state=random_state + initialization,
        )
        if inertia < best_inertia:
            best_labels = labels
            best_centroids = centroids
            best_inertia = inertia

    if best_labels is None or best_centroids is None:
        raise RuntimeError("KMeans did not produce a valid initialization.")
    return best_labels, best_centroids, float(best_inertia)


def silhouette_score(x: np.ndarray, labels: np.ndarray) -> float:
    # Mean silhouette width, implemented directly so the workbook can justify
    # the choice of K without pulling in scikit-learn.
    unique = np.unique(labels)
    if len(unique) < 2:
        return 0.0
    distances = np.sqrt(np.sum((x[:, None, :] - x[None, :, :]) ** 2, axis=2))
    scores = np.zeros(len(x), dtype=float)
    for i in range(len(x)):
        same = labels == labels[i]
        same[i] = False
        # The silhouette of a singleton cluster is defined as zero. Treating
        # its within-cluster distance as zero would incorrectly give it 1.0.
        if not same.any():
            scores[i] = 0.0
            continue
        a = distances[i, same].mean()
        b = min(distances[i, labels == other].mean() for other in unique if other != labels[i])
        denominator = max(a, b)
        scores[i] = (b - a) / denominator if denominator > 0 else 0.0
    return float(scores.mean())


# =========================================================
# 4.5 Solution 1 result — delivered Value Segment and behaviour profile
# =========================================================
# Two separate outputs from the same clustering:
#   Value Segment       -> the PRIMARY delivered value label. Clusters are
#                          ranked by NET GAMING REVENUE PER PLAYER.
#                          Ranking on a single monetary quantity avoids adding
#                          days to dollars, which silently mislabels clusters.
#                          Revenue per player is the quantity the operator
#                          actually banks per head; the median is reported
#                          alongside it so the skew inside each tier is visible.
#   Behaviour Archetype -> a supporting descriptive label read off the
#                          standardised
#                          centroid, so the fact that a cluster is "lapsed but
#                          valuable" rather than simply "below Premium" is
#                          preserved for CRM action.

def describe_archetype(centroid: pd.Series) -> str:
    recency, frequency, monetary = centroid["Recency"], centroid["Frequency"], centroid["Monetary"]

    # Recency is stored as a distance from today, so a negative z-score means
    # the cluster is recently active.
    if recency < -0.5:
        lifecycle = "Active"
    elif recency > 0.5:
        lifecycle = "Lapsed"
    else:
        lifecycle = "Cooling"

    if monetary < -0.5:
        profile = "Net Winners"
    elif monetary > 0.5:
        profile = "Whales"
    elif frequency > 0:
        profile = "Regulars"
    else:
        profile = "Casuals"

    return f"{lifecycle} {profile}"


def assign_unique_archetypes(cluster_value: pd.DataFrame) -> pd.Series:
    # Two clusters can land in the same descriptive box. Suffix the duplicates
    # with the cluster id rather than silently shipping identical labels.
    names = cluster_value.apply(describe_archetype, axis=1)
    duplicated = names.duplicated(keep=False)
    return names.where(
        ~duplicated,
        names + " (C" + cluster_value["KMeansCluster"].astype(str) + ")",
    )


def label_kmeans_segments(player_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    x_scaled, _ = standardize_for_kmeans(player_df)
    labels, centroids, inertia = run_kmeans(x_scaled, k=KMEANS_K)

    working = player_df.copy()
    working["KMeansCluster"] = labels.astype(int)

    centroid_df = pd.DataFrame(centroids, columns=KMEANS_FEATURES)
    centroid_df.insert(0, "KMeansCluster", range(KMEANS_K))

    # Rank on NGR per player, expressed in one unit so no dimensional mixing is
    # possible. Median NGR is carried alongside to expose the skew.
    cluster_value = (
        working.groupby("KMeansCluster")
        .agg(
            Players=("UserID", "count"),
            TotalNetGaming=("NetGaming", "sum"),
            MedianNetGaming=("NetGaming", "median"),
            MedianRecencyDays=("RecencyDays", "median"),
            MedianFrequency=("Frequency", "median"),
            MedianDepositAmount=("DepositAmount", "median"),
        )
        .reset_index()
        .merge(centroid_df, on="KMeansCluster")
    )
    cluster_value["NetGamingPerPlayer"] = (
        cluster_value["TotalNetGaming"] / cluster_value["Players"]
    )
    cluster_value["Behaviour Archetype"] = assign_unique_archetypes(cluster_value)

    ranking = cluster_value.sort_values("NetGamingPerPlayer", ascending=True).reset_index(drop=True)
    value_map = {
        int(ranking.loc[position, "KMeansCluster"]): VALUE_LABELS[position]
        for position in range(len(ranking))
    }
    archetype_map = dict(
        zip(cluster_value["KMeansCluster"].astype(int), cluster_value["Behaviour Archetype"])
    )

    working["Value Segment"] = working["KMeansCluster"].map(value_map)
    working["Behaviour Archetype"] = working["KMeansCluster"].map(archetype_map)
    working["Value Segment"] = pd.Categorical(
        working["Value Segment"], categories=VALUE_LABELS, ordered=True
    )

    cluster_value["Value Segment"] = cluster_value["KMeansCluster"].map(value_map)
    cluster_value["NetGamingShare"] = (
        cluster_value["TotalNetGaming"] / cluster_value["TotalNetGaming"].sum()
    )
    cluster_value = cluster_value[
        [
            "KMeansCluster",
            "Value Segment",
            "Behaviour Archetype",
            "Players",
            "NetGamingPerPlayer",
            "MedianNetGaming",
            "TotalNetGaming",
            "NetGamingShare",
            "MedianRecencyDays",
            "MedianFrequency",
            "MedianDepositAmount",
            *KMEANS_FEATURES,
        ]
    ]
    return working, cluster_value


def build_kmeans_diagnostics(player_df: pd.DataFrame) -> pd.DataFrame:
    # Elbow (inertia) and mean silhouette width across a range of K. The
    # silhouette is computed on a fixed random sample because the full pairwise
    # distance matrix is quadratic in the number of players.
    x_scaled, _ = standardize_for_kmeans(player_df)
    rng = np.random.default_rng(KMEANS_SEED)
    sample_size = min(SILHOUETTE_SAMPLE, len(x_scaled))
    sample_idx = rng.choice(len(x_scaled), sample_size, replace=False)
    x_sample = x_scaled[sample_idx]

    rows = []
    for k in KMEANS_K_RANGE:
        _, _, inertia = run_kmeans(x_scaled, k=k)
        sample_labels, _, _ = run_kmeans(x_sample, k=k)
        rows.append(
            {
                "K": k,
                "Inertia": round(inertia, 2),
                "MeanSilhouette": round(silhouette_score(x_sample, sample_labels), 4),
                "SilhouetteSampleSize": sample_size,
                "Selected": "Yes" if k == KMEANS_K else "",
            }
        )

    rows.append({
        "K": None,
        "Inertia": None,
        "MeanSilhouette": None,
        "SilhouetteSampleSize": None,
        "Selected": (
            f"K={KMEANS_K} is a business interpretability choice: four tiers map to "
            "four distinct CRM treatments. K=2 has the strongest silhouette in this "
            "dataset, so K=4 is disclosed as a granularity-versus-separation trade-off, "
            f"not the statistical optimum. Each K uses {KMEANS_N_INIT} initialisations."
        ),
    })
    return pd.DataFrame(rows)


# =========================================================
# 4.6 Solution 2 — required Risk Segment: review-priority rules
# =========================================================
# This is the second required segmentation axis, not an alternative model for
# Value Segment. Risk is scored with absolute, auditable triggers instead of
# equal-sized
# quantile buckets, for three reasons:
#   1. A regulator's high-risk population is a tail, not a fixed third of the
#      book. Equal buckets guarantee 33% high risk regardless of behaviour.
#   2. Roughly two thirds of players never withdraw, so their withdrawal-based
#      components are tied at zero and a quantile cut splits them arbitrarily.
#   3. Absolute withdrawal volume on its own is a proxy for player size, which
#      would make the risk axis collinear with the value axis and therefore
#      useless for decisions.
#
# Two independent scores are produced:
#   AML score -> financial-crime typologies (pass-through, card testing).
#   RG score  -> markers of gambling harm (chasing, escalation, intensity).

def build_risk_segment(player_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = player_df.copy()

    large_withdrawal_cut = working["WithdrawalAmount"].quantile(AML_LARGE_WITHDRAWAL_PCTL)
    loss_velocity_cut = working["NetLossPerActiveDay"].quantile(RG_LOSS_VELOCITY_PCTL)
    absolute_loss_cut = working["NetGaming"].quantile(RG_ABSOLUTE_LOSS_PCTL)

    # --- AML triggers --------------------------------------------------------
    # Money in and straight back out with almost no play is the classic
    # pass-through / layering pattern.
    working["AML_PassThrough"] = (
        (working["DepositAmount"] >= AML_PASSTHROUGH_MIN_DEPOSIT)
        & (working["Playthrough"] < AML_PASSTHROUGH_MAX_PLAYTHROUGH)
        & (working["WithdrawalToDeposit"] >= AML_PASSTHROUGH_MIN_WITHDRAWAL_RATIO)
        & (working["WithdrawalAmount"] > 0)
    ).astype(int)
    working["AML_WithdrawalNoDeposit"] = (
        (working["DepositAmount"] == 0) & (working["WithdrawalAmount"] > 0)
    ).astype(int)
    working["AML_WithdrawalExceedsDeposit"] = (
        (working["DepositAmount"] >= AML_RATIO_MIN_DEPOSIT)
        & (working["WithdrawalToDeposit"] >= AML_RATIO_THRESHOLD)
    ).astype(int)
    # Repeated failed deposits against a low success rate is a card-testing
    # signature rather than a payment-provider outage.
    working["AML_CardTesting"] = (
        (working["DepositFailedCount"] >= AML_CARD_TESTING_MIN_FAILS)
        & (working["DepositFailedRate"] >= AML_CARD_TESTING_MIN_RATE)
    ).astype(int)
    # Volume alone is not suspicious; it only adds a point on top of a pattern.
    working["AML_LargeWithdrawalVolume"] = (
        working["WithdrawalAmount"] >= large_withdrawal_cut
    ).astype(int)

    aml_pattern_score = (
        working["AML_PassThrough"] * 3
        + working["AML_WithdrawalNoDeposit"] * 3
        + working["AML_WithdrawalExceedsDeposit"] * 2
        + working["AML_CardTesting"] * 2
    )
    # Large volume is a severity multiplier only when another pattern exists;
    # it cannot by itself place a commercially valuable player into Risk.
    working["AMLRiskScore"] = aml_pattern_score + (
        working["AML_LargeWithdrawalVolume"] * (aml_pattern_score > 0).astype(int)
    )

    # --- Responsible Gambling triggers ---------------------------------------
    working["RG_LossChasing"] = (
        working["LossChasingDays"] >= RG_CHASING_MIN_DAYS
    ).astype(int)
    working["RG_DepositEscalation"] = (
        (
            (working["DepositEscalationRatio"] >= RG_ESCALATION_RATIO)
            | (working["RecentDepositWithoutEarlierBaseline"] == 1)
        )
        & (working["TenureDays"] >= RG_ESCALATION_MIN_TENURE_DAYS)
    ).astype(int)
    working["RG_HighLossVelocity"] = (
        working["NetLossPerActiveDay"] >= loss_velocity_cut
    ).astype(int)
    working["RG_SustainedIntensity"] = (
        working["MaxConsecutiveActiveDays"] >= RG_SUSTAINED_STREAK_DAYS
    ).astype(int)
    working["RG_HighAbsoluteLoss"] = (working["NetGaming"] >= absolute_loss_cut).astype(int)

    working["RGRiskScore"] = (
        working["RG_LossChasing"] * 2
        + working["RG_DepositEscalation"] * 2
        + working["RG_HighLossVelocity"] * 2
        + working["RG_SustainedIntensity"] * 1
        + working["RG_HighAbsoluteLoss"] * 1
    )

    # --- Tiering -------------------------------------------------------------
    def to_tier(row: pd.Series) -> str:
        if row["AMLRiskScore"] >= RISK_HIGH_AML_POINTS or row["RGRiskScore"] >= RISK_HIGH_RG_POINTS:
            return "High Risk"
        if (
            row["AMLRiskScore"] >= RISK_MEDIUM_AML_POINTS
            or row["RGRiskScore"] >= RISK_MEDIUM_RG_POINTS
        ):
            return "Medium Risk"
        return "Low Risk"

    working["Risk Segment"] = working.apply(to_tier, axis=1)
    working["Risk Segment"] = pd.Categorical(
        working["Risk Segment"], categories=RISK_LABELS, ordered=True
    )
    # Which of the two scores put the player where they are, so a case can be
    # routed to Compliance or to the Responsible Gambling team without reading
    # the individual flags. "None" is avoided as a literal because Excel and
    # pandas both read it back as a missing value.
    working["Risk Driver"] = np.select(
        [
            (working["AMLRiskScore"] >= RISK_HIGH_AML_POINTS)
            & (working["RGRiskScore"] >= RISK_HIGH_RG_POINTS),
            working["AMLRiskScore"] >= RISK_HIGH_AML_POINTS,
            working["RGRiskScore"] >= RISK_HIGH_RG_POINTS,
            (working["AMLRiskScore"] > 0) & (working["RGRiskScore"] > 0),
            (working["AMLRiskScore"] > 0)
            & (working["AMLRiskScore"] >= working["RGRiskScore"]),
            working["RGRiskScore"] > 0,
        ],
        [
            "AML + Responsible Gambling",
            "AML",
            "Responsible Gambling",
            "AML + Responsible Gambling (watch)",
            "AML (watch)",
            "Responsible Gambling (watch)",
        ],
        default="Not flagged",
    )

    flag_columns = [column for column in working.columns if column.startswith(("AML_", "RG_"))]
    flag_summary = pd.DataFrame(
        [
            {
                "Flag": column,
                "Category": "AML" if column.startswith("AML_") else "Responsible Gambling",
                "PlayersTriggered": int(working[column].sum()),
                "ShareOfPlayers": working[column].mean(),
                "AvgNetGaming": working.loc[working[column] == 1, "NetGaming"].mean(),
                "AvgWithdrawalAmount": working.loc[
                    working[column] == 1, "WithdrawalAmount"
                ].mean(),
            }
            for column in flag_columns
        ]
    ).sort_values(["Category", "PlayersTriggered"], ascending=[True, False])

    return working, flag_summary.reset_index(drop=True)


# =========================================================
# 4.7 Segment profiles
# =========================================================
# Profiles combine demographics with behaviour. Money metrics use medians and
# P90 because the distributions are right-skewed. Age is shown as a band mix
# plus an explicit eligibility-review share; an overall mean would make the
# implausible recorded ages look like a normal customer profile.

def gender_mix(series: pd.Series) -> str:
    counts = series.astype("string").fillna("Unknown").value_counts(normalize=True)
    return ", ".join(f"{key}: {value:.0%}" for key, value in counts.items())


def country_mix(series: pd.Series) -> str:
    counts = series.astype("string").fillna("Unknown").value_counts(normalize=True)
    return ", ".join(f"{key}: {value:.0%}" for key, value in counts.head(3).items())


def age_band_mix(series: pd.Series) -> str:
    counts = series.astype("string").fillna("Unknown").value_counts(normalize=True)
    return ", ".join(f"{key}: {value:.0%}" for key, value in counts.items())


def median_age_19_plus(series: pd.Series) -> float:
    eligible_ages = series[series >= IGAMING_MIN_AGE]
    return float(eligible_ages.median()) if not eligible_ages.empty else np.nan


def percentile(quantile: float):
    def inner(series: pd.Series) -> float:
        return series.quantile(quantile)

    inner.__name__ = f"p{int(quantile * 100)}"
    return inner


def build_profile(df: pd.DataFrame, segment_column: str) -> pd.DataFrame:
    grouped = df.groupby(segment_column, as_index=False, observed=True)
    profile = grouped.agg(
        Players=("UserID", "count"),
        MedianRecordedAge=("Age", "median"),
        MedianAge19Plus=("Age", median_age_19_plus),
        Under19Players=("AgeEligibilityFlag", "sum"),
        AgeBandMix=("AgeBand", age_band_mix),
        GenderMix=("Gender", gender_mix),
        CountryMix=("Country", country_mix),
        MedianTenureDays=("TenureDays", "median"),
        MedianRecencyDays=("RecencyDays", "median"),
        MedianFrequency=("Frequency", "median"),
        MedianWagerAmount=("WagerAmount", "median"),
        P90WagerAmount=("WagerAmount", percentile(0.90)),
        TotalWagerAmount=("WagerAmount", "sum"),
        MedianNetGaming=("NetGaming", "median"),
        TotalNetGaming=("NetGaming", "sum"),
        MedianDepositAmount=("DepositAmount", "median"),
        MedianWithdrawalAmount=("WithdrawalAmount", "median"),
        MedianWithdrawalToDeposit=("WithdrawalToDeposit", "median"),
        MedianAvgCashOdds=("AvgCashOdds", "median"),
        MedianCashGameShare=("CashGameShare", "median"),
        AvgFailedTxnRate=("FailedTxnRate", "mean"),
        AvgLossChasingDays=("LossChasingDays", "mean"),
    )
    profile["PlayerShare"] = profile["Players"] / profile["Players"].sum()
    profile["Under19Share"] = profile["Under19Players"] / profile["Players"]
    profile["NetGamingShare"] = profile["TotalNetGaming"] / profile["TotalNetGaming"].sum()
    profile["WagerShare"] = profile["TotalWagerAmount"] / profile["TotalWagerAmount"].sum()
    return profile.sort_values(segment_column).reset_index(drop=True)


# =========================================================
# 4.8 Value x Risk action matrix
# =========================================================
# The deliverable the question is really asking for: every player sits in one
# of twelve cells, and each cell carries a single owned action.

ACTION_MATRIX = {
    ("Premium", "High Risk"): "Prioritise manual Compliance and Responsible Gambling review before any targeted promotion; determine action only after case review.",
    ("Premium", "Medium Risk"): "Continue service cautiously, monitor the triggered indicators, and review before personalised promotion.",
    ("Premium", "Low Risk"): "Consider high-touch retention and personalised service within standard responsible-gambling controls.",
    ("High Value", "High Risk"): "Prioritise manual review and pause targeted promotional decisions until the indicators are assessed.",
    ("High Value", "Medium Risk"): "Monitor the triggered indicators and use conservative, reviewable retention activity.",
    ("High Value", "Low Risk"): "Prioritise for retention and relevant cross-sell testing with normal controls.",
    ("Medium Value", "High Risk"): "Route for manual review; avoid automated promotional escalation while indicators remain unresolved.",
    ("Medium Value", "Medium Risk"): "Use low-cost lifecycle activity and monitor for movement in the review indicators.",
    ("Medium Value", "Low Risk"): "Use scalable reactivation and cross-sell tests, measuring incremental response.",
    ("Low Value", "High Risk"): "Route for proportionate manual review; do not infer misconduct from the segment label alone.",
    ("Low Value", "Medium Risk"): "Use automated servicing and monitor the specific review indicators.",
    ("Low Value", "Low Risk"): "Use low-cost automated reactivation and measure cost per reactivated player.",
}


def build_value_risk_matrix(detailed: pd.DataFrame) -> pd.DataFrame:
    # Aggregate only combinations that are present, then explicitly reindex to
    # the full 4 x 3 grid. Some pandas versions fail when observed=False tries
    # to expand two categorical groupers during named aggregation.
    observed_groups = (
        detailed.groupby(["Value Segment", "Risk Segment"], as_index=False, observed=True)
        .agg(
            Players=("UserID", "count"),
            TotalNetGaming=("NetGaming", "sum"),
            MedianNetGaming=("NetGaming", "median"),
            TotalWithdrawalAmount=("WithdrawalAmount", "sum"),
            AMLIndicatorPlayers=("AMLRiskScore", lambda s: int((s > 0).sum())),
            RGIndicatorPlayers=("RGRiskScore", lambda s: int((s > 0).sum())),
            AMLHighPriorityPlayers=(
                "AMLRiskScore", lambda s: int((s >= RISK_HIGH_AML_POINTS).sum())
            ),
            RGHighPriorityPlayers=(
                "RGRiskScore", lambda s: int((s >= RISK_HIGH_RG_POINTS).sum())
            ),
        )
    )

    segment_grid = pd.MultiIndex.from_product(
        [VALUE_LABELS, RISK_LABELS],
        names=["Value Segment", "Risk Segment"],
    ).to_frame(index=False)
    grouped = segment_grid.merge(
        observed_groups,
        on=["Value Segment", "Risk Segment"],
        how="left",
    )

    zero_fill_columns = [
        "Players",
        "TotalNetGaming",
        "TotalWithdrawalAmount",
        "AMLIndicatorPlayers",
        "RGIndicatorPlayers",
        "AMLHighPriorityPlayers",
        "RGHighPriorityPlayers",
    ]
    grouped[zero_fill_columns] = grouped[zero_fill_columns].fillna(0)
    count_columns = [
        "Players",
        "AMLIndicatorPlayers",
        "RGIndicatorPlayers",
        "AMLHighPriorityPlayers",
        "RGHighPriorityPlayers",
    ]
    grouped[count_columns] = grouped[count_columns].astype(int)

    grouped["Value Segment"] = pd.Categorical(
        grouped["Value Segment"], categories=VALUE_LABELS, ordered=True
    )
    grouped["Risk Segment"] = pd.Categorical(
        grouped["Risk Segment"], categories=RISK_LABELS, ordered=True
    )
    grouped["PlayerShare"] = grouped["Players"] / grouped["Players"].sum()
    grouped["NetGamingShare"] = grouped["TotalNetGaming"] / grouped["TotalNetGaming"].sum()
    grouped["Recommended Action"] = [
        ACTION_MATRIX.get((str(value), str(risk)), "")
        for value, risk in zip(grouped["Value Segment"], grouped["Risk Segment"])
    ]
    return grouped.sort_values(["Value Segment", "Risk Segment"], ascending=[False, False]).reset_index(
        drop=True
    )


# =========================================================
# 4.9 Method comparison
# =========================================================
# The clustering is the primary method; the RFM score is retained as a
# robustness check. Reporting the agreement rate makes it explicit which one
# drives the delivered Value Segment column.

def build_method_summary(detailed: pd.DataFrame) -> pd.DataFrame:
    tier_rank = {label: position for position, label in enumerate(VALUE_LABELS)}
    kmeans_rank = detailed["Value Segment"].astype(str).map(tier_rank)
    score_rank = detailed["Value Segment (RFM Score)"].map(tier_rank)
    gap = (kmeans_rank - score_rank).abs()
    same = gap == 0
    # Exact agreement understates the fit because the two methods produce
    # different tier sizes by construction. Within-one-tier agreement is the
    # fairer read on whether they rank players the same way.
    adjacent = gap <= 1
    high_risk_share = (detailed["Risk Segment"] == "High Risk").mean()
    value_counts = detailed["Value Segment"].value_counts(sort=False)
    risk_counts = detailed["Risk Segment"].value_counts(sort=False)
    return pd.DataFrame(
        [
            {
                "Metric": "Business objective",
                "Value": (
                    "Map every player to one Value Segment and one Risk Segment, then profile "
                    "each segment using demographics and behavioural metrics."
                ),
            },
            {
                "Metric": "Output grain",
                "Value": (
                    "One row per UserID. Player-day Q1 records are aggregated before modelling "
                    "to prevent active players from receiving multiple segment assignments."
                ),
            },
            {"Metric": "Players segmented", "Value": len(detailed)},
            {
                "Metric": "Value feature framework",
                "Value": (
                    "Continuous LRFM+ features: Recency, Frequency, Net Gaming, Deposit and "
                    "Tenure. Net Gaming is Wagers minus Winnings and is not profit."
                ),
            },
            {
                "Metric": "Value preprocessing",
                "Value": (
                    "Skewed continuous features are log-transformed and standardised so a "
                    "large currency scale does not dominate the distance calculation."
                ),
            },
            {
                "Metric": "Primary value method",
                "Value": (
                    f"KMeans (k={KMEANS_K}) on standardised log Recency, Frequency, "
                    "NetGaming, Deposit and Tenure; clusters ranked by NGR per player"
                ),
            },
            {
                "Metric": "Why KMeans",
                "Value": (
                    "No labelled value outcome is supplied. KMeans provides a reproducible "
                    "multi-dimensional grouping, while the cluster profiles preserve the "
                    "behavioural differences behind each tier."
                ),
            },
            {
                "Metric": "Why four value tiers",
                "Value": (
                    "k=2 has the strongest silhouette but is too coarse for CRM action. k=4 is "
                    "a deliberate trade-off between statistical separation and the requested "
                    "Premium / High / Medium / Low business tiers."
                ),
            },
            {
                "Metric": "Primary value output",
                "Value": "; ".join(
                    f"{label}: {int(value_counts.get(label, 0))}" for label in VALUE_LABELS
                ),
            },
            {
                "Metric": "Cross-check value method",
                "Value": "RFM quintile scores (M = net gaming revenue) bucketed into four tiers",
            },
            {
                "Metric": "Why retain the RFM cross-check",
                "Value": (
                    "RFM is transparent and easy to explain, but its bins impose arbitrary "
                    "cut-offs. It is used as a robustness benchmark rather than a second "
                    "delivered segmentation or a source of truth."
                ),
            },
            {"Metric": "Value tiers", "Value": " / ".join(VALUE_LABELS)},
            {"Metric": "Methods agree exactly (players)", "Value": int(same.sum())},
            {"Metric": "Exact agreement rate", "Value": round(float(same.mean()), 4)},
            {
                "Metric": "Agreement within one tier",
                "Value": round(float(adjacent.mean()), 4),
            },
            {
                "Metric": "Disagreement of two tiers or more",
                "Value": int((gap >= 2).sum()),
            },
            {
                "Metric": "Risk method",
                "Value": (
                    "Rule-based AML and Responsible Gambling review indicators with absolute "
                    "triggers; labels prioritise review and do not establish misconduct or harm"
                ),
            },
            {
                "Metric": "Why rule-based risk",
                "Value": (
                    "No confirmed AML or responsible-gambling outcome labels are supplied. "
                    "Transparent indicators are auditable and show exactly why a player is "
                    "prioritised for human review."
                ),
            },
            {
                "Metric": "Risk limitation",
                "Value": (
                    "Thresholds are analytical review heuristics, not regulatory findings. "
                    "Production use would require validation by Compliance, Responsible Gaming "
                    "and operators against confirmed case outcomes."
                ),
            },
            {
                "Metric": "Risk output",
                "Value": "; ".join(
                    f"{label}: {int(risk_counts.get(label, 0))}" for label in RISK_LABELS
                ),
            },
            {"Metric": "High Risk share of players", "Value": round(float(high_risk_share), 4)},
            {
                "Metric": "Age treatment",
                "Value": (
                    "Retain all records; report AgeBand and under-19 eligibility-review share; "
                    "exclude Age from value and risk model inputs"
                ),
            },
            {
                "Metric": "Why age is not silently removed",
                "Value": (
                    "The recorded under-19 population is a material data-quality and eligibility "
                    "signal. Removing it would hide the issue; using it in the model would let a "
                    "questionable field distort commercial segmentation."
                ),
            },
            {
                "Metric": "Profile design",
                "Value": (
                    "Profiles combine player counts, gender/country/age-band mix and behavioural "
                    "metrics. Median and P90 are emphasised for skewed monetary distributions."
                ),
            },
            {
                "Metric": "Action design",
                "Value": (
                    "The Value x Risk matrix separates commercial value from review priority. "
                    "Recommendations are proportionate actions and never infer misconduct from "
                    "a segment label alone."
                ),
            },
            {
                "Metric": "Value / Risk rank correlation",
                "Value": round(
                    float(
                        detailed["NetGaming"]
                        .rank()
                        .corr((detailed["AMLRiskScore"] + detailed["RGRiskScore"]).rank())
                    ),
                    4,
                ),
            },
        ]
    )


def build_crosstab(detailed: pd.DataFrame) -> pd.DataFrame:
    matrix = pd.crosstab(
        detailed["Value Segment"].astype(str),
        detailed["Value Segment (RFM Score)"],
    )
    return matrix.reindex(index=VALUE_LABELS, columns=VALUE_LABELS, fill_value=0)


def build_data_quality_notes(q1_df: pd.DataFrame, player_df: pd.DataFrame) -> pd.DataFrame:
    ages = player_df["Age"]
    return pd.DataFrame(
        [
            {
                "Topic": "Analysis window",
                "Observation": (
                    f"Activity spans {q1_df['ActivityDate'].min():%Y-%m-%d} to "
                    f"{q1_df['ActivityDate'].max():%Y-%m-%d}; median recency is "
                    f"{player_df['RecencyDays'].median():.0f} days."
                ),
                "Treatment": (
                    "Recency is measured against the dataset maximum date, so the segmentation "
                    "is a full-lifetime view. For an operational CRM run the window should be "
                    "restricted to the trailing 12 to 24 months."
                ),
            },
            {
                "Topic": "Age distribution",
                "Observation": (
                    f"Age ranges from {ages.min()} to {ages.max()} with a median of "
                    f"{ages.median():.0f}; {(ages < IGAMING_MIN_AGE).sum()} of {len(ages)} "
                    f"players are recorded below the minimum legal age threshold of "
                    f"{IGAMING_MIN_AGE}."
                ),
                "Treatment": (
                    "All records are retained. Age bands and the under-19 share are reported as "
                    "data-quality and eligibility-review indicators, while Age is excluded from "
                    "both models. Because the data predates the regulated market it would be compared "
                    "against and spans several jurisdictions with different thresholds, this is "
                    "not interpreted as evidence of actual underage participation. In production "
                    "the records would be reconciled against date of birth and KYC controls."
                ),
            },
            {
                "Topic": "Monetary definition",
                "Observation": (
                    f"Total turnover is {player_df['WagerAmount'].sum():,.0f} against net gaming "
                    f"revenue of {player_df['NetGaming'].sum():,.0f}; "
                    f"{(player_df['NetGaming'] < 0).sum()} players finished net ahead."
                ),
                "Treatment": (
                    "Value is scored on net gaming revenue rather than turnover, so high-churn "
                    "low-margin play is not mistaken for high value."
                ),
            },
            {
                "Topic": "Withdrawal coverage",
                "Observation": (
                    f"{(player_df['WithdrawalAmount'] == 0).sum()} of {len(player_df)} players "
                    "never withdrew, and "
                    f"{(player_df['DepositAmount'] == 0).sum()} never deposited."
                ),
                "Treatment": (
                    "Withdrawal-derived ratios are undefined for these players, so risk uses "
                    "absolute rule triggers instead of quantile buckets which would split the "
                    "tied population at zero arbitrarily."
                ),
            },
            {
                "Topic": "Zero-play accounts",
                "Observation": (
                    f"{(player_df['WagerAmount'] == 0).sum()} players have activity records but "
                    "zero lifetime wagers."
                ),
                "Treatment": (
                    "Retained in the population because deposit and withdrawal behaviour without "
                    "play is itself an AML signal rather than an empty record."
                ),
            },
        ]
    )


# =========================================================
# 4.10 Workbook helpers
# =========================================================

PERCENT_COLUMNS = ("Share", "Rate")
INTEGER_COLUMNS = ("Players", "Count", "Days", "Score", "Flag", "K")


def write_dataframe_sheet(ws, df: pd.DataFrame) -> None:
    for row in dataframe_to_rows(df, index=False, header=True):
        ws.append(row)


def resolve_number_format(column: str) -> str | None:
    if any(token in column for token in PERCENT_COLUMNS):
        return "0.0%"
    if column.startswith(("AML_", "RG_")) or any(token in column for token in INTEGER_COLUMNS):
        return "0"
    return "#,##0.00"


def style_sheet(ws, df: pd.DataFrame) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center")

    for idx, column in enumerate(df.columns, start=1):
        series = df[column]
        widths = series.map(lambda value: len(str(value)))
        max_len = max(len(str(column)), int(widths.max()) if not widths.empty else 0)
        ws.column_dimensions[get_column_letter(idx)].width = min(max_len + 2, 45)

        if max_len > 45 and not pd.api.types.is_numeric_dtype(series):
            for row in range(2, ws.max_row + 1):
                ws.cell(row=row, column=idx).alignment = Alignment(
                    vertical="top", wrap_text=True
                )

        if pd.api.types.is_datetime64_any_dtype(series):
            for row in range(2, ws.max_row + 1):
                ws.cell(row=row, column=idx).number_format = "yyyy-mm-dd"
        elif pd.api.types.is_numeric_dtype(series):
            fmt = resolve_number_format(str(column))
            if fmt:
                for row in range(2, ws.max_row + 1):
                    ws.cell(row=row, column=idx).number_format = fmt


def save_workbook(sheets: list[tuple[str, pd.DataFrame]], output_path: Path) -> None:
    wb = Workbook()
    wb.remove(wb.active)

    for sheet_name, df in sheets:
        ws = wb.create_sheet(title=sheet_name[:31])
        write_dataframe_sheet(ws, df)
        style_sheet(ws, df)

    wb.save(output_path)


# =========================================================
# 4.11 Main workflow
# =========================================================

DETAIL_COLUMNS = [
    "UserID",
    "Gender",
    "Age",
    "AgeBand",
    "AgeEligibilityFlag",
    "Country",
    "CountryCode",
    "FirstActivityDate",
    "LastActivityDate",
    "TenureDays",
    "RecencyDays",
    "Frequency",
    "ActivityRate",
    "MaxConsecutiveActiveDays",
    "CashGames",
    "CashGameWagers",
    "CashGameWinnings",
    "AvgCashOdds",
    "Tournaments",
    "TournamentWagers",
    "TournamentWinnings",
    "WagerAmount",
    "WinningAmount",
    "CashGameShare",
    "TournamentShare",
    "WagerPerActiveDay",
    "NetGaming",
    "NetLossPerActiveDay",
    "DepositAmount",
    "WithdrawalAmount",
    "WithdrawalToDeposit",
    "Playthrough",
    "DepositFailedCount",
    "WithdrawalFailedCount",
    "FailedTxnRate",
    "LossChasingDays",
    "DepositEscalationRatio",
    "RecentDepositWithoutEarlierBaseline",
    "RecencyScore",
    "FrequencyScore",
    "MonetaryScore",
    "RFMScore",
    "KMeansCluster",
    "Behaviour Archetype",
    "Value Segment",
    "Value Segment (RFM Score)",
    "AML_PassThrough",
    "AML_WithdrawalNoDeposit",
    "AML_WithdrawalExceedsDeposit",
    "AML_CardTesting",
    "AML_LargeWithdrawalVolume",
    "AMLRiskScore",
    "RG_LossChasing",
    "RG_DepositEscalation",
    "RG_HighLossVelocity",
    "RG_SustainedIntensity",
    "RG_HighAbsoluteLoss",
    "RGRiskScore",
    "Risk Driver",
    "Risk Segment",
]


def main(input_path: Path | None = None, output_path: Path = OUTPUT_XLSX) -> None:
    resolved_input = resolve_q1_path(input_path)
    q1_df = load_q1_result(resolved_input)
    player_df = build_player_features(q1_df)

    # Solution 1A: primary delivered Value Segment.
    kmeans_df, cluster_profile = label_kmeans_segments(player_df)
    # Solution 1B: validation-only RFM benchmark.
    score_df = build_rfm_scores(player_df)
    # Solution 2: independently delivered Risk Segment / review priority.
    risk_df, flag_summary = build_risk_segment(player_df)

    risk_columns = [
        column
        for column in risk_df.columns
        if column.startswith(("AML", "RG")) or column in {"Risk Segment", "Risk Driver"}
    ]
    detailed = (
        kmeans_df.merge(
            score_df[
                [
                    "UserID",
                    "RecencyScore",
                    "FrequencyScore",
                    "MonetaryScore",
                    "RFMScore",
                    "Value Segment (RFM Score)",
                ]
            ],
            on="UserID",
            how="inner",
        )
        .merge(risk_df[["UserID", *risk_columns]], on="UserID", how="inner")
        .loc[:, DETAIL_COLUMNS]
        .sort_values(
            ["Value Segment", "Risk Segment", "NetGaming"], ascending=[False, False, False]
        )
        .reset_index(drop=True)
    )

    save_workbook(
        [
            # Reviewer-facing sheets first: purpose and decisions, then the
            # segment profiles and the actionable Value x Risk matrix.
            ("Method_Summary", build_method_summary(detailed)),
            ("Value_Profile", build_profile(detailed, "Value Segment")),
            ("Risk_Profile", build_profile(detailed, "Risk Segment")),
            ("Value_Risk_Matrix", build_value_risk_matrix(detailed)),
            ("Player_Segments", detailed),
            ("Data_Quality_Notes", build_data_quality_notes(q1_df, player_df)),
            # Supporting diagnostics follow the main answer.
            ("Archetype_Profile", build_profile(detailed, "Behaviour Archetype")),
            ("Risk_Flag_Summary", flag_summary),
            ("Cluster_Profile", cluster_profile),
            ("KMeans_Diagnostics", build_kmeans_diagnostics(player_df)),
            ("Method_Crosstab", build_crosstab(detailed).reset_index()),
        ],
        output_path,
    )

    print(f"Loaded Q1 workbook: {resolved_input}")
    print(f"Saved Q4 workbook: {output_path}")
    print(detailed["Value Segment"].value_counts().sort_index().to_string())
    print(detailed["Risk Segment"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Q4 player segmentation outputs.")
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional path to Q1_Result.xlsx. Common local/submission layouts are auto-detected.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_XLSX,
        help="Output path for Q4_Result.xlsx.",
    )
    arguments = parser.parse_args()
    main(arguments.input, arguments.output)
