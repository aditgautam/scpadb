"""
Build the debut-to-championship modeling dataset from scores.db.

Usage:
    uv run python scripts/build_model_dataset.py
    uv run python scripts/build_model_dataset.py --db path/to/scores.db
    uv run python scripts/build_model_dataset.py --out analysis/data/model_dataset.csv

Scope: marching classes only (PIA, PIO, PIW, PSA, PSJ, PSO, PSW).
Unit of analysis: one ensemble track-season.

Output columns (see RESEARCH_PROJECT_OVERVIEW.md for full spec):
  identity:        track_id, canonical_ensemble_id, season_year, class_code
  debut features:  debut_subtotal_score, debut_penalty_score, debut_week,
                   debut_week_index, debut_day_of_week, debut_class_code,
                   affiliation, level, division,
                   debut_event_field_size,
                   debut_score_percentile, debut_score_gap_to_class_leader,
                   debut_score_gap_to_class_median,
                   debut_em_overall_effect, debut_em_music_effect,
                   debut_ev_overall_effect, debut_ev_visual_effect,
                   debut_mu_composition, debut_mu_performance,
                   debut_vi_composition, debut_vi_performance,
                   (+ _z and _missing variants of each subcaption feature)
  prior history:   has_prior_history, prior_champ_percentile,
                   prior_champ_subtotal, n_prior_seasons,
                   years_since_prior
  targets:         terminal_subtotal_score, terminal_stage,
                   championship_percentile  (secondary, 0-1)

Assertions (all must pass before CSV is written):
  1. Every included performance maps to exactly one track.
  2. Every track-season has exactly one debut performance.
  3. Every labeled track-season has exactly one terminal championship performance.
  4. No performance is duplicated by the track expansion.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import numpy as np

MARCHING_CLASSES = {"pia", "pio", "piw", "psa", "psj", "pso", "psw"}

# Stage priority for terminal championship selection (lower = better)
STAGE_PRIORITY = {
    "championship_finals": 1,
    "championship_semifinals": 2,
    "championship_prelims": 3,
}

SUBCAPTION_MAP = {
    # (caption, subcaption) -> feature_name
    ("effect_music", "overall"): "em_overall_effect",
    ("effect_music", "music"): "em_music_effect",
    ("effect_visual", "overall"): "ev_overall_effect",
    ("effect_visual", "visual"): "ev_visual_effect",
    ("music", "composition"): "mu_composition",
    ("music", "performance"): "mu_performance",
    ("visual", "composition"): "vi_composition",
    ("visual", "performance"): "vi_performance",
}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="scores.db")
    p.add_argument("--out", default="analysis/data/model_dataset.csv")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Load raw data
# ---------------------------------------------------------------------------

def load_raw(conn):
    # All marching performances with canonical metadata and display_stage
    perf = pd.read_sql("""
        SELECT
            vep.performance_key,
            vsp.event_id,
            vep.canonical_ensemble_id,
            vep.canonical_ensemble_name,
            vep.class_code,
            vep.season_year,
            vep.performance_date,
            vep.event_stage,
            vep.display_stage,
            vep.round,
            vep.season_week_calendar,
            vep.season_week_index,
            p.subtotal_score,
            p.penalty_score,
            p.total_score
        FROM v_frontend_ensemble_performances vep
        JOIN v_frontend_show_performances vsp
          ON vsp.performance_key = vep.performance_key
        JOIN performances p ON p.performance_key = vep.performance_key
        WHERE vep.class_code IN ('pia','pio','piw','psa','psj','pso','psw')
    """, conn)
    perf["performance_date"] = pd.to_datetime(perf["performance_date"])

    # Ensemble class tracks (marching scope)
    tracks = pd.read_sql("""
        SELECT track_id, canonical_ensemble_id, class_code, season_year
        FROM ensemble_track_assignments
    """, conn)

    # Raw subcaption scores for debut score-profile features
    raw_scores = pd.read_sql("""
        SELECT s.performance_key, s.caption, s.subcaption,
               s.score, s.judge_slot
        FROM scores s
        JOIN performances p ON p.performance_key = s.performance_key
        WHERE s.role = 'raw_score'
          AND p.class_code IN ('pia','pio','piw','psa','psj','pso','psw')
    """, conn)

    # Block-level z-scores for normalization
    block_z = pd.read_sql("""
        SELECT jbs.performance_key, jbs.caption, jbs.subcaption,
               jbs.block_z_score
        FROM v_judge_block_stats jbs
        JOIN performances p ON p.performance_key = jbs.performance_key
        WHERE p.class_code IN ('pia','pio','piw','psa','psj','pso','psw')
    """, conn)

    return perf, tracks, raw_scores, block_z


# ---------------------------------------------------------------------------
# Track expansion
# ---------------------------------------------------------------------------

def expand_tracks(perf, tracks):
    """
    Assign every performance to exactly one (canonical_ensemble_id, track_id).

    A performance belongs to the one explicit assignment matching its canonical
    ensemble, class code, and season.
    """
    expanded = perf.merge(
        tracks,
        on=["canonical_ensemble_id", "class_code", "season_year"],
        how="left",
        validate="many_to_one",
    )
    unassigned = expanded[expanded["track_id"].isna()]
    if not unassigned.empty:
        sample = unassigned[
            ["canonical_ensemble_name", "season_year", "class_code", "performance_key"]
        ].head(20)
        raise ValueError(
            f"{len(unassigned)} performances have no track assignment:\n"
            + sample.to_string(index=False)
        )
    if len(expanded) != len(perf):
        raise AssertionError(
            f"Track expansion changed row count from {len(perf)} to {len(expanded)}"
        )
    return expanded


# ---------------------------------------------------------------------------
# Cohort selection
# ---------------------------------------------------------------------------

def is_championship(display_stage):
    return isinstance(display_stage, str) and display_stage.startswith("championship")


def select_debut(group):
    """
    Earliest non-championship performance. Tie-break: stage priority asc,
    round asc (null=0), performance_key lex.
    """
    non_champ = group[~group["display_stage"].apply(is_championship)].copy()
    if non_champ.empty:
        return None
    non_champ["_round"] = non_champ["round"].fillna(0).astype(int)
    non_champ = non_champ.sort_values(
        ["performance_date", "_round", "performance_key"]
    )
    return non_champ.iloc[0]


def select_terminal_championship(group):
    """
    Highest championship stage reached. Tie-break: latest date, highest round,
    lex performance_key.
    """
    champ = group[group["display_stage"].apply(is_championship)].copy()
    if champ.empty:
        return None
    champ["_priority"] = champ["display_stage"].map(
        lambda s: STAGE_PRIORITY.get(s, 4)
    )
    champ["_round"] = champ["round"].fillna(0).astype(int)
    champ = champ.sort_values(
        ["_priority", "performance_date", "_round", "performance_key"],
        ascending=[True, False, False, True],
    )
    return champ.iloc[0]


def build_cohort(expanded):
    """
    Build one row per eligible track-season with debut and terminal records.
    Unit of analysis: (canonical_ensemble_id, track_id, season_year).
    Note: track_id is NOT globally unique — multiple ensembles share ids like
    'class:psa'. The composite key is required.
    Returns (cohort_df, exclusion_counts).
    """
    exclusions = {}
    rows = []

    # Exclude track-seasons with multiple classes in-season
    class_per_track_season = (
        expanded.groupby(["canonical_ensemble_id", "track_id", "season_year"])["class_code"]
        .nunique()
        .reset_index(name="n_classes")
    )
    multi_class = set(
        zip(
            class_per_track_season[class_per_track_season["n_classes"] > 1]["canonical_ensemble_id"],
            class_per_track_season[class_per_track_season["n_classes"] > 1]["track_id"],
            class_per_track_season[class_per_track_season["n_classes"] > 1]["season_year"],
        )
    )
    exclusions["multi_class_in_season"] = len(multi_class)

    for (ens_id, track_id, season_year), group in expanded.groupby(
        ["canonical_ensemble_id", "track_id", "season_year"]
    ):
        if (ens_id, track_id, season_year) in multi_class:
            continue

        debut_row = select_debut(group)
        terminal_row = select_terminal_championship(group)

        if debut_row is None or terminal_row is None:
            exclusions["no_debut_or_no_championship"] = (
                exclusions.get("no_debut_or_no_championship", 0) + 1
            )
            continue

        # Debut must be strictly before championship
        if debut_row["performance_date"] >= terminal_row["performance_date"]:
            exclusions["debut_same_day_as_championship"] = (
                exclusions.get("debut_same_day_as_championship", 0) + 1
            )
            continue

        # Both must have non-null subtotal scores
        if pd.isna(debut_row["subtotal_score"]) or pd.isna(terminal_row["subtotal_score"]):
            exclusions["missing_subtotal"] = (
                exclusions.get("missing_subtotal", 0) + 1
            )
            continue

        rows.append({
            "track_id": track_id,
            "canonical_ensemble_id": debut_row["canonical_ensemble_id"],
            "canonical_ensemble_name": debut_row["canonical_ensemble_name"],
            "season_year": season_year,
            "class_code": debut_row["class_code"],
            # debut fields
            "debut_performance_key": debut_row["performance_key"],
            "debut_date": debut_row["performance_date"],
            "debut_subtotal_score": debut_row["subtotal_score"],
            "debut_penalty_score": debut_row["penalty_score"] if not pd.isna(debut_row["penalty_score"]) else 0.0,
            "debut_week": debut_row["season_week_calendar"],
            "debut_week_index": debut_row["season_week_index"],
            "debut_day_of_week": debut_row["performance_date"].dayofweek,
            "debut_class_code": debut_row["class_code"],
            # terminal fields
            "terminal_performance_key": terminal_row["performance_key"],
            "terminal_subtotal_score": terminal_row["subtotal_score"],
            "terminal_stage": terminal_row["display_stage"],
        })

    cohort = pd.DataFrame(rows)
    return cohort, exclusions


# ---------------------------------------------------------------------------
# Derived identity features
# ---------------------------------------------------------------------------

def add_identity_features(cohort):
    code = cohort["class_code"].str.lower()
    cohort["affiliation"] = code.str.startswith("pi").map({True: "independent", False: "scholastic"})
    cohort["level"] = code.str.extract(r"(a|o|w)$")[0].map(
        {"a": "A", "o": "Open", "w": "World"}
    )
    cohort["division"] = code.apply(
        lambda c: "junior" if c == "psj" else "standard"
    )
    return cohort


# ---------------------------------------------------------------------------
# Competition-relative debut features
# ---------------------------------------------------------------------------

def add_competition_relative_features(cohort, expanded):
    """
    For each debut, compute:
    - debut_event_field_size: # ensembles in same event/class/round
    - debut_score_percentile: subtotal percentile within event/class/round
    - debut_score_gap_to_class_leader
    - debut_score_gap_to_class_median
    """
    # Pull all non-championship performances for debut-event context
    non_champ = expanded[~expanded["display_stage"].apply(is_championship)].copy()
    non_champ = non_champ.dropna(subset=["subtotal_score"])

    event_groups = non_champ.groupby(
        ["event_id", "class_code", "round"]
    )["subtotal_score"]

    event_field_size = event_groups.transform("count").rename("_field_size")
    event_leader = event_groups.transform("max").rename("_leader")
    event_median = event_groups.transform("median").rename("_median")
    event_rank = event_groups.rank(method="average", ascending=True).rename("_rank")

    non_champ = non_champ.join(event_field_size).join(event_leader).join(event_median).join(event_rank)
    non_champ["_percentile"] = (non_champ["_rank"] - 1) / (non_champ["_field_size"] - 1).clip(lower=1)

    debut_stats = non_champ.set_index("performance_key")[
        ["_field_size", "_percentile", "_leader", "_median"]
    ]

    cohort = cohort.join(debut_stats.rename(columns={
        "_field_size": "debut_event_field_size",
        "_percentile": "debut_score_percentile",
        "_leader": "_debut_leader",
        "_median": "_debut_median",
    }), on="debut_performance_key")

    cohort["debut_score_gap_to_class_leader"] = (
        cohort["debut_subtotal_score"] - cohort["_debut_leader"]
    )
    cohort["debut_score_gap_to_class_median"] = (
        cohort["debut_subtotal_score"] - cohort["_debut_median"]
    )
    cohort = cohort.drop(columns=["_debut_leader", "_debut_median"])
    return cohort


# ---------------------------------------------------------------------------
# Debut score-profile features
# ---------------------------------------------------------------------------

def add_score_profile_features(cohort, raw_scores, block_z):
    """
    For each of the 8 (caption, subcaption) pairs in SUBCAPTION_MAP,
    compute the mean raw score across judges at debut, plus the mean block
    z-score, plus a missing indicator.
    """
    debut_keys = set(cohort["debut_performance_key"])
    rel_raw = raw_scores[raw_scores["performance_key"].isin(debut_keys)].copy()
    rel_z = block_z[block_z["performance_key"].isin(debut_keys)].copy()

    # Average across judge slots (handles single and double panels uniformly)
    raw_mean = (
        rel_raw[rel_raw.apply(
            lambda r: (r["caption"], r["subcaption"]) in SUBCAPTION_MAP, axis=1
        )]
        .groupby(["performance_key", "caption", "subcaption"])["score"]
        .mean()
        .reset_index()
    )
    raw_mean["feature"] = raw_mean.apply(
        lambda r: "debut_" + SUBCAPTION_MAP[(r["caption"], r["subcaption"])], axis=1
    )
    raw_pivot = raw_mean.pivot(index="performance_key", columns="feature", values="score")

    z_mean = (
        rel_z[rel_z.apply(
            lambda r: (r["caption"], r["subcaption"]) in SUBCAPTION_MAP, axis=1
        )]
        .groupby(["performance_key", "caption", "subcaption"])["block_z_score"]
        .mean()
        .reset_index()
    )
    z_mean["feature"] = z_mean.apply(
        lambda r: "debut_" + SUBCAPTION_MAP[(r["caption"], r["subcaption"])] + "_z", axis=1
    )
    z_pivot = z_mean.pivot(index="performance_key", columns="feature", values="block_z_score")

    cohort = cohort.join(raw_pivot, on="debut_performance_key")
    cohort = cohort.join(z_pivot, on="debut_performance_key")

    # Missing indicators
    for feat in SUBCAPTION_MAP.values():
        col = f"debut_{feat}"
        cohort[f"{col}_missing"] = cohort[col].isna().astype(int)

    return cohort


# ---------------------------------------------------------------------------
# Prior history features
# ---------------------------------------------------------------------------

def add_prior_history(cohort):
    """
    For each track-season, look up prior championship percentiles from earlier
    seasons of the same track. Uses only seasons strictly before the current one.
    """
    # We need championship_percentile to be computed first (added after this fn)
    # so we defer filling until after target computation. Return a placeholder
    # that will be filled in build_prior_history_after_target().
    cohort["has_prior_history"] = 0
    cohort["prior_champ_percentile"] = np.nan
    cohort["prior_champ_subtotal"] = np.nan
    cohort["n_prior_seasons"] = 0
    cohort["years_since_prior"] = np.nan
    return cohort


def fill_prior_history(cohort):
    """
    Fill prior history features after championship_percentile is computed.
    Uses most recent prior season per track.
    """
    sorted_cohort = cohort.sort_values(["track_id", "season_year"])
    prior_rows = {}

    for row_index, row in sorted_cohort.iterrows():
        prior = sorted_cohort[
            (sorted_cohort["canonical_ensemble_id"] == row["canonical_ensemble_id"])
            & (sorted_cohort["track_id"] == row["track_id"])
            & (sorted_cohort["season_year"] < row["season_year"])
        ]
        if prior.empty:
            prior_rows[row_index] = {
                "has_prior_history": 0,
                "prior_champ_percentile": np.nan,
                "prior_champ_subtotal": np.nan,
                "n_prior_seasons": 0,
                "years_since_prior": np.nan,
            }
        else:
            most_recent = prior.sort_values("season_year").iloc[-1]
            prior_rows[row_index] = {
                "has_prior_history": 1,
                "prior_champ_percentile": most_recent["championship_percentile"],
                "prior_champ_subtotal": most_recent["terminal_subtotal_score"],
                "n_prior_seasons": len(prior),
                "years_since_prior": row["season_year"] - most_recent["season_year"],
            }

    prior_df = pd.DataFrame.from_dict(prior_rows, orient="index")
    for col in prior_df.columns:
        cohort[col] = prior_df[col]
    return cohort


# ---------------------------------------------------------------------------
# Primary target: championship percentile within class/season
# ---------------------------------------------------------------------------

def compute_target(cohort):
    """
    championship_percentile = (rank - 1) / (cohort_size - 1)
    within (season_year, class_code), ranked by terminal_subtotal_score ascending.
    Requires at least 2 eligible ensembles per class/season.
    """
    def percentile_within_group(g):
        if len(g) < 2:
            return pd.Series(np.nan, index=g.index)
        ranks = g["terminal_subtotal_score"].rank(method="average", ascending=True)
        return (ranks - 1) / (len(g) - 1)

    cohort["championship_percentile"] = cohort.groupby(
        ["season_year", "class_code"], group_keys=False
    ).apply(percentile_within_group)

    # Drop class/seasons with fewer than 2 ensembles
    n_before = len(cohort)
    cohort = cohort.dropna(subset=["championship_percentile"])
    n_dropped = n_before - len(cohort)
    if n_dropped:
        print(f"  Dropped {n_dropped} rows: class/season cohort < 2 ensembles")

    return cohort


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

def run_assertions(cohort, expanded):
    errors = []

    # 1. Every included debut performance maps to exactly one track.
    debut_counts = (
        expanded[expanded["performance_key"].isin(cohort["debut_performance_key"])]
        .groupby("performance_key")["track_id"]
        .nunique()
    )
    multi_track = debut_counts[debut_counts > 1]
    if not multi_track.empty:
        errors.append(f"ASSERTION 1 FAILED: {len(multi_track)} debut performances map to >1 track")

    # 2. Every track-season has exactly one debut performance.
    debut_per_ts = cohort.groupby(
        ["canonical_ensemble_id", "track_id", "season_year"]
    )["debut_performance_key"].nunique()
    if (debut_per_ts != 1).any():
        errors.append("ASSERTION 2 FAILED: some track-seasons have != 1 debut")

    # 3. Every labeled track-season has exactly one terminal championship performance.
    terminal_per_ts = cohort.groupby(
        ["canonical_ensemble_id", "track_id", "season_year"]
    )["terminal_performance_key"].nunique()
    if (terminal_per_ts != 1).any():
        errors.append("ASSERTION 3 FAILED: some track-seasons have != 1 terminal championship")

    # 4. No performance is duplicated by track expansion.
    dup_count = expanded.duplicated(subset=["performance_key", "track_id"]).sum()
    if dup_count > 0:
        errors.append(f"ASSERTION 4 FAILED: {dup_count} duplicate (performance_key, track_id) rows")

    if errors:
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)
    else:
        print("  All four assertions passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    print("Loading raw data...")
    perf, tracks, raw_scores, block_z = load_raw(conn)
    conn.close()

    print(f"  Marching performances: {len(perf):,}")
    print(
        "  Track assignments: "
        f"{len(tracks):,} across {tracks[['canonical_ensemble_id', 'track_id']].drop_duplicates().shape[0]:,} tracks"
    )

    print("Expanding tracks...")
    expanded = expand_tracks(perf, tracks)
    print(f"  Performances assigned to tracks: {len(expanded):,}")
    unassigned = len(perf) - len(expanded)
    if unassigned:
        print(f"  Unassigned (ambiguous or untracked): {unassigned:,}")

    print("Building cohort...")
    cohort, exclusions = build_cohort(expanded)
    for reason, count in sorted(exclusions.items()):
        print(f"  Excluded ({reason}): {count:,}")
    print(f"  Cohort rows before class-size filter: {len(cohort):,}")

    print("Computing target...")
    cohort = add_identity_features(cohort)
    cohort = compute_target(cohort)
    print(f"  Final cohort rows: {len(cohort):,}")

    # Print class/season breakdown
    breakdown = (
        cohort.groupby(["season_year", "class_code"])
        .agg(n=("championship_percentile", "count"))
        .reset_index()
        .pivot(index="season_year", columns="class_code", values="n")
        .fillna(0)
        .astype(int)
    )
    print("\n  Cohort size by season/class:")
    print(breakdown.to_string())

    holdout_years = {2025, 2026}
    dev_n = cohort[~cohort["season_year"].isin(holdout_years)].shape[0]
    hold_n = cohort[cohort["season_year"].isin(holdout_years)].shape[0]
    print(f"\n  Development (2017-2019, 2022-2024): {dev_n:,}")
    print(f"  Holdout (2025-2026): {hold_n:,}")

    print("\nAdding features...")
    cohort = add_competition_relative_features(cohort, expanded)
    cohort = add_score_profile_features(cohort, raw_scores, block_z)
    cohort = add_prior_history(cohort)
    cohort = fill_prior_history(cohort)

    print("\nRunning assertions...")
    run_assertions(cohort, expanded)

    # Final column order
    id_cols = ["track_id", "canonical_ensemble_id", "canonical_ensemble_name",
               "season_year", "class_code",
               "debut_performance_key", "terminal_performance_key"]
    feature_cols = [c for c in cohort.columns if c not in id_cols
                    and c not in ("terminal_subtotal_score", "terminal_stage",
                                  "championship_percentile", "debut_date")]
    target_cols = ["terminal_subtotal_score", "terminal_stage", "championship_percentile"]
    final_cols = id_cols + ["debut_date"] + feature_cols + target_cols
    final_cols = [c for c in final_cols if c in cohort.columns]

    cohort[final_cols].to_csv(out_path, index=False)
    print(f"\nDataset written to {out_path}  ({len(cohort):,} rows, {len(final_cols)} columns)")


if __name__ == "__main__":
    main()
