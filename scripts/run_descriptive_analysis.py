#!/usr/bin/env python3
"""Export artifact-free descriptive tables and publication-ready figures."""

import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).parents[1]
OUTPUT = ROOT / "analysis" / "outputs"


def main() -> None:
    tables = OUTPUT / "tables"
    figures = OUTPUT / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Roboto", "Arial", "DejaVu Sans"],
        "figure.facecolor": "#f2f2f2",
        "axes.facecolor": "#ffffff",
        "axes.edgecolor": "#d0d0d0",
        "axes.grid": True,
        "grid.color": "#ebebeb",
        "axes.titleweight": "bold",
    })

    with sqlite3.connect(ROOT / "scores.db") as conn:
        valid = pd.read_sql(
            """
            SELECT
                v.performance_key,
                v.canonical_ensemble_id,
                v.canonical_ensemble_name,
                eta.track_id,
                v.season_year,
                v.performance_date,
                v.class_code,
                v.display_stage,
                v.season_week_calendar,
                p.subtotal_score
            FROM v_frontend_ensemble_performances v
            JOIN performances p USING (performance_key)
            JOIN ensemble_track_assignments eta
              ON eta.canonical_ensemble_id = v.canonical_ensemble_id
             AND eta.class_code = v.class_code
             AND eta.season_year = v.season_year
            WHERE NOT EXISTS (
                SELECT 1 FROM analysis_excluded_performances aep
                WHERE aep.performance_key = v.performance_key
            )
            """,
            conn,
            parse_dates=["performance_date"],
        )
        artifacts = pd.read_sql(
            """
            SELECT p.*, aep.reason
            FROM analysis_excluded_performances aep
            JOIN performances p USING (performance_key)
            ORDER BY performance_date, ensemble_name
            """,
            conn,
        )

    stage_priority = {
        "championship_finals": 1,
        "championship_semifinals": 2,
        "championship_prelims": 3,
        "championship": 4,
        "mixed_championship": 4,
    }
    championship = valid[
        valid["display_stage"].str.startswith("championship", na=False)
    ].copy()
    championship["stage_priority"] = championship["display_stage"].map(
        stage_priority
    ).fillna(4)
    terminal = (
        championship.sort_values(
            ["stage_priority", "performance_date"],
            ascending=[True, False],
        )
        .groupby(
            [
                "canonical_ensemble_id",
                "canonical_ensemble_name",
                "track_id",
                "season_year",
            ],
            as_index=False,
        )
        .first()
    )
    terminal_medians = terminal.pivot_table(
        index="season_year",
        columns="class_code",
        values="subtotal_score",
        aggfunc="median",
    ).reset_index()
    weekly_medians = (
        valid.groupby(["season_year", "season_week_calendar"])["subtotal_score"]
        .median()
        .reset_index()
    )
    tenure = (
        valid.groupby(["canonical_ensemble_id", "canonical_ensemble_name"])[
            "season_year"
        ]
        .nunique()
        .reset_index(name="observed_seasons")
        .sort_values(["observed_seasons", "canonical_ensemble_name"], ascending=[False, True])
    )
    roster = pd.read_csv(ROOT / "config" / "representative_programs.csv")
    representative = (
        terminal[
            terminal["canonical_ensemble_id"].isin(
                roster["canonical_ensemble_id"]
            )
        ]
        .groupby(
            ["canonical_ensemble_id", "canonical_ensemble_name", "season_year"],
            as_index=False,
        )["subtotal_score"]
        .max()
    )

    artifacts.to_csv(tables / "analysis_artifacts.csv", index=False)
    terminal_medians.to_csv(tables / "terminal_championship_medians.csv", index=False)
    weekly_medians.to_csv(tables / "weekly_score_medians.csv", index=False)
    tenure.to_csv(tables / "program_tenure.csv", index=False)
    representative.to_csv(
        tables / "representative_program_trajectories.csv", index=False
    )

    figure, axis = plt.subplots(figsize=(10, 5))
    terminal_medians.set_index("season_year").plot(marker="o", ax=axis)
    axis.set(
        title="Median terminal championship subtotal by class",
        xlabel="Season",
        ylabel="Median terminal subtotal",
    )
    axis.legend(title="Class", ncol=2, fontsize=8)
    figure.tight_layout()
    figure.savefig(figures / "terminal_championship_medians.png", dpi=200)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(10, 5.5))
    for (_, name), group in representative.groupby(
        ["canonical_ensemble_id", "canonical_ensemble_name"]
    ):
        axis.plot(
            group["season_year"],
            group["subtotal_score"],
            marker="o",
            linewidth=2,
            label=name,
        )
    axis.set(
        title="Terminal championship trajectories: representative programs",
        xlabel="Season",
        ylabel="Terminal subtotal",
    )
    axis.legend(ncol=2, fontsize=8)
    figure.tight_layout()
    figure.savefig(figures / "representative_program_trajectories.png", dpi=200)
    plt.close(figure)

    print(
        f"Exported {len(artifacts)} artifacts, {len(terminal)} terminal scores, "
        f"and {len(tenure)} program tenure rows."
    )


if __name__ == "__main__":
    main()
