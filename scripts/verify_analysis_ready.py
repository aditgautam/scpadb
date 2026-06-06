#!/usr/bin/env python3
"""Verify the current derived database and modeling dataset are analysis-ready."""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

DB_PATH = Path("scores.db")
MODEL_PATH = Path("analysis/data/model_dataset.csv")
DEVELOPMENT_SEASONS = {2017, 2018, 2019, 2022, 2023, 2024}
HOLDOUT_SEASONS = {2025, 2026}


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
    require(len(data.columns) == 53, f"Expected 53 columns, found {len(data.columns)}")
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
    development = int(data["season_year"].isin(DEVELOPMENT_SEASONS).sum())
    holdout = int(data["season_year"].isin(HOLDOUT_SEASONS).sum())
    require(development == 574, f"Expected 574 development rows, found {development}")
    require(holdout == 207, f"Expected 207 holdout rows, found {holdout}")


def main() -> None:
    try:
        verify_database()
        verify_model_dataset()
    except (AssertionError, sqlite3.Error, pd.errors.ParserError) as exc:
        print(f"NOT READY: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("Analysis-ready: scores.db and analysis/data/model_dataset.csv passed.")


if __name__ == "__main__":
    main()
