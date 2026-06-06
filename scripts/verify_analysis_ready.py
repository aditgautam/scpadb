#!/usr/bin/env python3
"""Verify the current derived database and modeling dataset are analysis-ready."""

import sqlite3
import sys
import json
from pathlib import Path

import pandas as pd

DB_PATH = Path("scores.db")
MODEL_PATH = Path("analysis/data/model_dataset.csv")
DEVELOPMENT_SEASONS = {2017, 2018, 2019, 2022, 2023, 2024}
HOLDOUT_SEASONS = {2025, 2026}
REPRESENTATIVE_PATH = Path("config/representative_programs.csv")
OUTPUT_TABLES = Path("analysis/outputs/tables")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def verify_database() -> None:
    require(DB_PATH.exists(), f"Missing database: {DB_PATH}")
    with sqlite3.connect(DB_PATH) as conn:
        marching = scalar(
            conn,
            """
            SELECT count(*)
            FROM v_frontend_ensemble_performances
            WHERE class_code IN ('pia','pio','piw','psa','psj','pso','psw')
            """,
        )
        mapped = scalar(
            conn,
            """
            SELECT count(*)
            FROM v_frontend_ensemble_performances v
            JOIN ensemble_track_assignments eta
              ON eta.canonical_ensemble_id = v.canonical_ensemble_id
             AND eta.class_code = v.class_code
             AND eta.season_year = v.season_year
            WHERE v.class_code IN ('pia','pio','piw','psa','psj','pso','psw')
            """,
        )
        require(marching == 3_808, f"Expected 3,808 marching records, found {marching}")
        require(mapped == marching, f"Only {mapped}/{marching} marching records map")
        artifacts = scalar(
            conn,
            "SELECT count(*) FROM analysis_excluded_performances",
        )
        require(artifacts == 16, f"Expected 16 analytical artifacts, found {artifacts}")
        artifact_blocks = scalar(
            conn,
            """
            SELECT count(*)
            FROM judge_block_stats jbs
            JOIN analysis_excluded_performances aep USING (performance_key)
            """,
        )
        require(artifact_blocks == 0, "Analytical artifacts remain in judge blocks")
        require(
            scalar(conn, "SELECT count(*) FROM ensemble_class_tracks") == 297,
            "Expected 297 track summaries",
        )
        require(
            scalar(conn, "SELECT count(*) FROM ensemble_track_assignments") == 1_244,
            "Expected 1,244 track assignments",
        )

        false_flags = scalar(
            conn,
            """
            SELECT count(*)
            FROM ensemble_track_season_flags
            WHERE canonical_ensemble_id IN ('arcadia_hs', 'vista_murrieta_hs')
            """,
        )
        require(false_flags == 0, "Arcadia or Vista Murrieta has a false promotion flag")

        expected_flags = {
            tuple(row)
            for row in conn.execute(
                """
                SELECT canonical_ensemble_id, track_id, season_year
                FROM ensemble_track_season_flags
                WHERE canonical_ensemble_id IN (
                    'etiwanda_hs', 'rancho_cucamonga_hs', 'west_ranch_hs'
                )
                """
            )
        }
        require(
            expected_flags
            == {
                ("etiwanda_hs", "psw_line", 2017),
                ("rancho_cucamonga_hs", "pso_line", 2023),
                ("west_ranch_hs", "track:concert", 2019),
                ("west_ranch_hs", "track:marching", 2022),
            },
            f"Unexpected selected promotion flags: {sorted(expected_flags)}",
        )


def verify_model_dataset() -> None:
    require(MODEL_PATH.exists(), f"Missing model dataset: {MODEL_PATH}")
    data = pd.read_csv(MODEL_PATH)
    require(len(data) == 781, f"Expected 781 model rows, found {len(data)}")
    require(len(data.columns) == 55, f"Expected 55 columns, found {len(data.columns)}")
    require(
        not data.duplicated(
            ["canonical_ensemble_id", "track_id", "season_year"]
        ).any(),
        "Duplicate ensemble track-seasons in model dataset",
    )
    require(
        data["terminal_subtotal_score"].notna().all(),
        "Primary target contains missing values",
    )
    require(
        (data["debut_subtotal_score"] > 0).all(),
        "Model dataset contains an all-zero debut artifact",
    )
    require(
        (data["terminal_subtotal_score"] > 0).all(),
        "Model dataset contains an all-zero target artifact",
    )
    require(
        {"prior_class_code", "class_change_direction"}.issubset(data.columns),
        "Missing reclassification features",
    )
    development = int(data["season_year"].isin(DEVELOPMENT_SEASONS).sum())
    holdout = int(data["season_year"].isin(HOLDOUT_SEASONS).sum())
    require(development == 574, f"Expected 574 development rows, found {development}")
    require(holdout == 207, f"Expected 207 holdout rows, found {holdout}")


def verify_representative_programs() -> None:
    require(REPRESENTATIVE_PATH.exists(), f"Missing roster: {REPRESENTATIVE_PATH}")
    roster = pd.read_csv(REPRESENTATIVE_PATH)
    require(len(roster) == 6, f"Expected 6 representative programs, found {len(roster)}")
    require(
        not roster["canonical_ensemble_id"].duplicated().any(),
        "Representative program IDs must be unique",
    )
    with sqlite3.connect(DB_PATH) as conn:
        known = {
            row[0]
            for row in conn.execute(
                "SELECT canonical_ensemble_id FROM canonical_ensembles"
            )
        }
    missing = sorted(set(roster["canonical_ensemble_id"]) - known)
    require(not missing, f"Unknown representative program IDs: {missing}")


def verify_experiment_outputs() -> None:
    ablation_path = OUTPUT_TABLES / "ablation.csv"
    summary_path = OUTPUT_TABLES / "model_summary.json"
    require(ablation_path.exists(), f"Missing experiment output: {ablation_path}")
    require(summary_path.exists(), f"Missing experiment output: {summary_path}")

    ablation = pd.read_csv(ablation_path)
    score_only = ablation.loc[
        ablation["feature_set"] == "A: debut score only"
    ]
    require(len(score_only) == 1, "Missing score-only ablation")
    require(
        int(score_only.iloc[0]["numeric_features"]) == 1
        and int(score_only.iloc[0]["categorical_features"]) == 0,
        "Score-only ablation contains hidden features",
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    require(
        summary["development_rows"] == 574 and summary["holdout_rows"] == 207,
        "Experiment outputs use an unexpected temporal split",
    )
    ci_low, ci_high = summary["bootstrap_gbm_minus_ridge_mae_ci"]
    require(ci_low <= ci_high, "Bootstrap confidence interval is malformed")


def main() -> None:
    try:
        verify_database()
        verify_model_dataset()
        verify_representative_programs()
        verify_experiment_outputs()
    except (AssertionError, sqlite3.Error, pd.errors.ParserError) as exc:
        print(f"NOT READY: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("Analysis-ready: scores.db and analysis/data/model_dataset.csv passed.")


if __name__ == "__main__":
    main()
