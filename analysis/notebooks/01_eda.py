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
    # 01 - Dataset and Exploratory Analysis

    This notebook describes the database before modeling. It distinguishes
    records preserved for historical display from records suitable for
    statistical analysis.

    **Analytical rule:** an all-zero subtotal and total is treated as a
    no-show, withdrawal, or recap artifact. These rows remain in `scores.db`
    and the frontend, but are excluded from numerical summaries and models.
    """)
    return


@app.cell
def _(mo):
    mo.Html("""
    <style>
      .marimo-output { font-family: Roboto, Arial, sans-serif; }
      .marimo-output table { background: #fff; border: 1px solid #d8d8d8; }
      .marimo-output h1, .marimo-output h2 { color: #000; }
    </style>
    """)
    return


@app.cell
def _(pathlib, pd, sqlite3):
    _root = pathlib.Path(__file__).parents[2]
    _conn = sqlite3.connect(_root / "scores.db")
    performances = pd.read_sql(
        """
        SELECT v.*, aep.reason AS exclusion_reason
        FROM v_performances_canonical v
        LEFT JOIN analysis_excluded_performances aep USING (performance_key)
        """,
        _conn,
        parse_dates=["performance_date"],
    )
    clean = performances[performances["exclusion_reason"].isna()].copy()
    artifacts = performances[performances["exclusion_reason"].notna()].copy()
    return artifacts, clean, performances


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Coverage

    The first table counts raw database records. The second plot uses only
    analytically valid performances. The missing 2021 season is structural,
    not a notebook filtering decision.
    """)
    return


@app.cell
def _(performances, pd):
    coverage = pd.DataFrame({
        "metric": [
            "performances",
            "seasons",
            "canonical programs",
            "classes",
            "first date",
            "last date",
        ],
        "value": [
            len(performances),
            performances["season_year"].nunique(),
            performances["canonical_ensemble_id"].nunique(),
            performances["class_code"].nunique(),
            performances["performance_date"].min().date(),
            performances["performance_date"].max().date(),
        ],
    })
    coverage
    return


@app.cell
def _(clean, plt):
    _counts = clean.groupby(["season_year", "class_code"]).size().unstack(fill_value=0)
    _ax = _counts.plot(
        kind="bar",
        stacked=True,
        figsize=(11, 5),
        colormap="tab10",
    )
    _ax.set(
        title="Analytically valid performances by season and class",
        xlabel="Season",
        ylabel="Performances",
    )
    _ax.legend(title="Class", ncol=2, fontsize=8)
    plt.tight_layout()
    return _ax.get_figure()


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Artifact audit

    Sixteen records contain zero in every score field. A genuine judged
    performance cannot receive an all-zero sheet under the observed score
    range, so these rows are retained as historical database artifacts but are
    not interpreted as performance quality.
    """)
    return


@app.cell
def _(artifacts):
    artifacts[[
        "performance_date",
        "competition_name",
        "class_code",
        "canonical_ensemble_name",
        "subtotal_score",
        "total_score",
        "exclusion_reason",
    ]].sort_values(["performance_date", "canonical_ensemble_name"])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Score distributions

    Subtotal is used rather than penalty-adjusted total because penalties
    primarily describe timing, logistics, or rule compliance. The plot shows
    that class expectations are a major source of score variation and must be
    represented in the predictive model.
    """)
    return


@app.cell
def _(clean, plt, sns):
    _marching = clean[clean["class_code"].isin(
        ["pia", "pio", "piw", "psa", "psj", "pso", "psw"]
    )]
    _fig, _ax = plt.subplots(figsize=(11, 5))
    sns.boxplot(
        data=_marching,
        x="class_code",
        y="subtotal_score",
        order=["pia", "pio", "piw", "psa", "psj", "pso", "psw"],
        color="#d8d8d8",
        ax=_ax,
    )
    _ax.set(
        title="Artifact-free subtotal distributions by marching class",
        xlabel="Class",
        ylabel="Subtotal score",
    )
    plt.tight_layout()
    return _fig


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Modeling cohort flow

    The modeling table contains one eligible ensemble track-season with a
    regular-season debut and a later championship result. Multi-class seasons
    are excluded because the eventual championship class may not be knowable
    at debut.
    """)
    return


@app.cell
def _(pathlib, pd):
    _model = pd.read_csv(
        pathlib.Path(__file__).parents[1] / "data" / "model_dataset.csv"
    )
    cohort_flow = pd.DataFrame({
        "stage": [
            "Marching performances after artifact exclusion",
            "Eligible model track-seasons",
            "Development seasons",
            "Held-out 2025-2026",
        ],
        "rows": [
            3795,
            len(_model),
            _model["season_year"].isin([2017, 2018, 2019, 2022, 2023, 2024]).sum(),
            _model["season_year"].isin([2025, 2026]).sum(),
        ],
    })
    cohort_flow
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Interpretation

    The database is broad enough for longitudinal analysis, but participation
    is unbalanced across classes and seasons. PSA dominates the cohort, while
    PIA and PIO contain small class-season groups. Results should therefore be
    reported overall and by class, with caution around small independent
    cohorts.
    """)
    return


if __name__ == "__main__":
    app.run()
