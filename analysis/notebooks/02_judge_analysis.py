import marimo

__generated_with = "0.23.9"
app = marimo.App()


@app.cell
def _():
    import pathlib
    import sqlite3

    import marimo as mo
    import matplotlib.pyplot as plt
    import pandas as pd
    import seaborn as sns

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
    return mo, pathlib, pd, plt, sns, sqlite3


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # 02 - Judge Block Normalization

    This notebook screens for unusual judge scores. It does not test intent or
    prove favoritism.

    For score \(x_{ij}\) assigned to ensemble \(i\) in exact judging block
    \(j\):

    \[
    z_{ij} = \frac{x_{ij} - \bar{x}_{j}}{s_j}
    \]

    A block is one event, class, round, caption, subcaption, judge, and judge
    slot. The standard deviation is the sample standard deviation. Analysis is
    restricted to blocks with at least three scored ensembles, and all-zero
    performance artifacts are removed before block statistics are calculated.
    """)
    return


@app.cell
def _(pathlib, pd, sqlite3):
    _conn = sqlite3.connect(pathlib.Path(__file__).parents[2] / "scores.db")
    judge_scores = pd.read_sql(
        """
        SELECT *
        FROM v_judge_block_stats
        WHERE block_score_count >= 3
          AND block_z_score IS NOT NULL
        """,
        _conn,
        parse_dates=["performance_date"],
    )
    return (judge_scores,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Workload and block coverage

    Workload matters because repeated-pair analyses are only credible when a
    judge appears across many shows and a judge-program pair has enough
    observations.
    """)
    return


@app.cell
def _(judge_scores):
    judge_workload = (
        judge_scores.groupby(["judge", "judge_display_name"])
        .agg(
            score_count=("score_id", "count"),
            block_count=("score_block_id", "nunique"),
            first_date=("performance_date", "min"),
            last_date=("performance_date", "max"),
        )
        .sort_values(["block_count", "score_count"], ascending=False)
    )
    judge_workload.head(20)
    return (judge_workload,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Distribution after cleaning

    Because each block is centered separately, an individual judge's overall
    mean z-score is mechanically close to zero. The distribution is useful for
    anomaly screening, not as a direct measure of leniency or severity.
    """)
    return


@app.cell
def _(judge_scores, judge_workload, plt, sns):
    _top = judge_workload.head(12).index.get_level_values("judge")
    _plot = judge_scores[judge_scores["judge"].isin(_top)]
    _fig, _ax = plt.subplots(figsize=(12, 5))
    sns.boxplot(
        data=_plot,
        x="judge_display_name",
        y="block_z_score",
        color="#d8d8d8",
        showfliers=False,
        ax=_ax,
    )
    _ax.axhline(0, color="#000", linewidth=1)
    _ax.set(
        title="Block-normalized scores for the busiest judges",
        xlabel="Judge",
        ylabel="Within-block z-score",
    )
    _ax.tick_params(axis="x", rotation=30)
    plt.tight_layout()
    return _fig


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Largest cleaned deviations

    These are legitimate scored performances after artifact removal. A large
    absolute z-score means the ensemble was far from the mean of that exact
    field on one subcaption; it does not identify the cause.
    """)
    return


@app.cell
def _(judge_scores):
    _outliers = judge_scores.assign(
        abs_z=judge_scores["block_z_score"].abs()
    ).sort_values("abs_z", ascending=False)
    _outliers[[
        "performance_date",
        "competition_name",
        "class_code",
        "canonical_ensemble_name",
        "judge_display_name",
        "caption",
        "subcaption",
        "score",
        "block_z_score",
        "block_score_count",
    ]].head(30)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Repeated judge-program pairs

    Raw repeated positive z-scores still confound ensemble strength with judge
    behavior. They are retained only to identify pairs with enough observations
    for the residual model in notebook 05.
    """)
    return


@app.cell
def _(judge_scores):
    repeated_pairs = (
        judge_scores.groupby([
            "judge_display_name",
            "canonical_ensemble_id",
            "canonical_ensemble_name",
            "caption",
            "subcaption",
        ])
        .agg(
            observations=("score_id", "count"),
            mean_z=("block_z_score", "mean"),
            median_z=("block_z_score", "median"),
        )
        .query("observations >= 5")
        .sort_values(["observations", "mean_z"], ascending=[False, False])
    )
    repeated_pairs.head(30)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Limitation

    Judge assignments are not random, and the data does not observe repertoire,
    staff, membership, or performance order. Any residual pair flagged later
    should be described as a persistent deviation requiring contextual review,
    never as proof of bias.
    """)
    return


if __name__ == "__main__":
    app.run()
