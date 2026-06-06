#!/usr/bin/env python3
"""Run adjusted score-trend and judge residual secondary analyses."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import ttest_ind


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="scores.db")
    parser.add_argument("--output", default="analysis/outputs")
    return parser.parse_args()


def set_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Roboto", "Arial", "DejaVu Sans"],
            "figure.facecolor": "#f2f2f2",
            "axes.facecolor": "#ffffff",
            "axes.edgecolor": "#d0d0d0",
            "axes.grid": True,
            "grid.color": "#ebebeb",
            "axes.titleweight": "bold",
        }
    )


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    count = len(p_values)
    order = np.argsort(p_values.to_numpy())
    ranked = p_values.to_numpy()[order]
    adjusted = np.minimum.accumulate(
        (ranked * count / np.arange(1, count + 1))[::-1]
    )[::-1]
    result = np.empty(count)
    result[order] = np.clip(adjusted, 0, 1)
    return pd.Series(result, index=p_values.index)


def load_performances(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT
            v.canonical_ensemble_id,
            eta.track_id,
            v.season_year,
            v.class_code,
            v.season_week_calendar,
            v.display_stage,
            p.subtotal_score
        FROM v_frontend_ensemble_performances v
        JOIN performances p USING (performance_key)
        JOIN ensemble_track_assignments eta
          ON eta.canonical_ensemble_id = v.canonical_ensemble_id
         AND eta.class_code = v.class_code
         AND eta.season_year = v.season_year
        WHERE v.class_code IN ('pia','pio','piw','psa','psj','pso','psw')
          AND NOT EXISTS (
              SELECT 1
              FROM analysis_excluded_performances aep
              WHERE aep.performance_key = v.performance_key
          )
        """,
        conn,
    )


def score_calibration(performance: pd.DataFrame):
    data = performance.copy()
    data["track_key"] = (
        data["canonical_ensemble_id"].astype(str)
        + "|"
        + data["track_id"].astype(str)
    )
    model = smf.ols(
        """
        subtotal_score ~ C(season_year, Treatment(reference=2017))
        + C(class_code)
        + season_week_calendar
        + C(display_stage)
        + C(track_key)
        """,
        data=data,
    ).fit(cov_type="cluster", cov_kwds={"groups": data["track_key"]})

    rows = [
        {
            "season_year": 2017,
            "adjusted_difference_vs_2017": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "p_value": np.nan,
        }
    ]
    for year in sorted(set(data["season_year"]) - {2017}):
        term = f"C(season_year, Treatment(reference=2017))[T.{year}]"
        estimate = model.params[term]
        interval = model.conf_int().loc[term]
        rows.append(
            {
                "season_year": year,
                "adjusted_difference_vs_2017": estimate,
                "ci_low": interval.iloc[0],
                "ci_high": interval.iloc[1],
                "p_value": model.pvalues[term],
            }
        )
    effects = pd.DataFrame(rows)

    descriptive = (
        data.groupby("season_year")
        .agg(
            performances=("subtotal_score", "size"),
            median_subtotal=("subtotal_score", "median"),
            share_90_plus=("subtotal_score", lambda values: (values >= 90).mean()),
        )
        .reset_index()
    )
    return model, effects, descriptive


def load_judge_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT
            j.score_id,
            j.block_z_score,
            j.judge_display_name,
            j.canonical_ensemble_id,
            j.canonical_ensemble_name,
            eta.track_id,
            j.season_year,
            j.season_week_calendar,
            j.class_code,
            j.caption,
            j.subcaption,
            j.event_stage
        FROM v_judge_block_stats j
        JOIN ensemble_track_assignments eta
          ON eta.canonical_ensemble_id = j.canonical_ensemble_id
         AND eta.class_code = j.class_code
         AND eta.season_year = j.season_year
        WHERE j.block_score_count >= 3
          AND j.block_z_score IS NOT NULL
          AND j.class_code IN ('pia','pio','piw','psa','psj','pso','psw')
        """,
        conn,
    )


def judge_residual_screen(judge_scores: pd.DataFrame):
    data = judge_scores.copy()
    data["track_key"] = (
        data["canonical_ensemble_id"].astype(str)
        + "|"
        + data["track_id"].astype(str)
    )
    expected = smf.ols(
        """
        block_z_score ~ C(track_key)
        + C(class_code)
        + C(season_year)
        + season_week_calendar
        + C(caption)
        + C(subcaption)
        + C(event_stage)
        """,
        data=data,
    ).fit()
    data["residual"] = expected.resid

    rows = []
    group_columns = [
        "judge_display_name",
        "track_key",
        "canonical_ensemble_name",
        "caption",
    ]
    for keys, pair in data.groupby(group_columns):
        if len(pair) < 5:
            continue
        judge, track_key, ensemble_name, caption = keys
        comparison = data[
            (data["track_key"] == track_key)
            & (data["caption"] == caption)
            & (data["judge_display_name"] != judge)
        ]
        if len(comparison) < 5:
            continue
        test = ttest_ind(
            pair["residual"],
            comparison["residual"],
            equal_var=False,
        )
        rows.append(
            {
                "judge_display_name": judge,
                "track_key": track_key,
                "canonical_ensemble_name": ensemble_name,
                "caption": caption,
                "pair_observations": len(pair),
                "comparison_observations": len(comparison),
                "pair_mean_residual": pair["residual"].mean(),
                "other_judges_mean_residual": comparison["residual"].mean(),
                "difference": pair["residual"].mean()
                - comparison["residual"].mean(),
                "p_value": test.pvalue,
            }
        )
    pairs = pd.DataFrame(rows)
    if pairs.empty:
        return expected, pairs
    pairs["p_adjusted_bh"] = benjamini_hochberg(pairs["p_value"])
    pairs["flag_after_bh"] = pairs["p_adjusted_bh"] < 0.05
    pairs = pairs.sort_values(
        ["flag_after_bh", "p_adjusted_bh", "difference"],
        ascending=[False, True, False],
    )
    return expected, pairs


def save_score_plot(effects: pd.DataFrame, figures_dir: Path) -> None:
    figure, axis = plt.subplots(figsize=(8, 4.8))
    errors = np.vstack(
        [
            effects["adjusted_difference_vs_2017"] - effects["ci_low"],
            effects["ci_high"] - effects["adjusted_difference_vs_2017"],
        ]
    )
    axis.errorbar(
        effects["season_year"],
        effects["adjusted_difference_vs_2017"],
        yerr=errors,
        fmt="o-",
        color="#000000",
        ecolor="#777777",
        capsize=4,
    )
    axis.axhline(0, color="#9f1d1d", linestyle="--", linewidth=1)
    axis.set(
        title="Adjusted season score differences relative to 2017",
        xlabel="Season",
        ylabel="Adjusted subtotal difference",
    )
    figure.tight_layout()
    figure.savefig(figures_dir / "adjusted_season_effects.png", dpi=200)
    plt.close(figure)


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    tables_dir = output / "tables"
    figures_dir = output / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    set_plot_style()

    with sqlite3.connect(args.db) as conn:
        performances = load_performances(conn)
        judge_scores = load_judge_scores(conn)

    score_model, season_effects, descriptive = score_calibration(performances)
    _, judge_pairs = judge_residual_screen(judge_scores)

    season_effects.to_csv(tables_dir / "adjusted_season_effects.csv", index=False)
    descriptive.to_csv(tables_dir / "season_score_descriptives.csv", index=False)
    judge_pairs.to_csv(tables_dir / "judge_residual_pairs.csv", index=False)
    (tables_dir / "score_calibration_model.txt").write_text(
        score_model.summary().as_text(),
        encoding="utf-8",
    )
    save_score_plot(season_effects, figures_dir)

    flagged = int(judge_pairs["flag_after_bh"].sum()) if not judge_pairs.empty else 0
    print(
        f"Adjusted season model: {len(performances):,} performances; "
        f"judge screen: {len(judge_pairs):,} eligible pairs, {flagged} BH flags."
    )


if __name__ == "__main__":
    main()
