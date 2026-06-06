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
    # 03 - Score Trends and Program Trajectories

    This notebook separates three different questions that were previously
    blended together:

    1. How do **terminal championship subtotals** vary by season and class?
    2. How do **weekly median subtotals** progress within each season?
    3. Which programs have broad historical coverage, and how have a small
       owner-curated set of representative programs changed over time?

    The 2026 season is complete through championship finals on April 11, 2026.
    The 2020 season is shown separately because it ended after six weeks.
    """)
    return


@app.cell
def _(pathlib, pd, sqlite3):
    _root = pathlib.Path(__file__).parents[2]
    _conn = sqlite3.connect(_root / "scores.db")
    valid_scores = pd.read_sql(
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
            SELECT 1
            FROM analysis_excluded_performances aep
            WHERE aep.performance_key = v.performance_key
        )
        """,
        _conn,
        parse_dates=["performance_date"],
    )
    representative_programs = pd.read_csv(
        _root / "config" / "representative_programs.csv"
    )
    return representative_programs, valid_scores


@app.cell
def _(valid_scores):
    _stage_priority = {
        "championship_finals": 1,
        "championship_semifinals": 2,
        "championship_prelims": 3,
        "championship": 4,
        "mixed_championship": 4,
    }
    _championships = valid_scores[
        valid_scores["display_stage"].str.startswith("championship", na=False)
    ].copy()
    _championships["stage_priority"] = _championships["display_stage"].map(
        _stage_priority
    ).fillna(4)
    terminal_scores = (
        _championships.sort_values(
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
    return (terminal_scores,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Terminal championship medians

    Each point is the median terminal championship subtotal for one
    season-class. It is not the median of all regular-season scores. Terminal
    means the furthest championship stage reached by each eligible track.
    """)
    return


@app.cell
def _(plt, terminal_scores):
    _table = terminal_scores.pivot_table(
        index="season_year",
        columns="class_code",
        values="subtotal_score",
        aggfunc="median",
    )
    _ax = _table.plot(figsize=(12, 5), marker="o")
    _ax.set(
        title="Median terminal championship subtotal by class",
        xlabel="Season",
        ylabel="Median terminal subtotal",
    )
    _ax.legend(title="Class", ncol=2, fontsize=8)
    plt.tight_layout()
    return _ax.get_figure()


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Within-season progression

    Weekly medians are used instead of means to reduce sensitivity to unusual
    low or high performances. The chart describes the circuit's observed
    schedule, not the improvement of a fixed set of ensembles.
    """)
    return


@app.cell
def _(plt, valid_scores):
    _weekly = (
        valid_scores.groupby(["season_year", "season_week_calendar"])[
            "subtotal_score"
        ]
        .median()
        .reset_index()
    )
    _fig, _ax = plt.subplots(figsize=(12, 5))
    for _year, _group in _weekly.groupby("season_year"):
        _ax.plot(
            _group["season_week_calendar"],
            _group["subtotal_score"],
            marker="o",
            label=str(_year),
            linestyle="--" if _year == 2020 else "-",
            alpha=0.85,
        )
    _ax.set(
        title="Weekly median subtotal by season",
        xlabel="SCPA season week",
        ylabel="Median subtotal",
    )
    _ax.legend(ncol=3, fontsize=8)
    plt.tight_layout()
    return _fig


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Historical participation

    The earlier notebook used `.head(10)` on a 58-program tie and therefore
    published an arbitrary list. This table reports every program tied for the
    maximum nine observed seasons.
    """)
    return


@app.cell
def _(valid_scores):
    _tenure = (
        valid_scores.groupby(
            ["canonical_ensemble_id", "canonical_ensemble_name"]
        )["season_year"]
        .nunique()
        .reset_index(name="observed_seasons")
    )
    max_tenure = int(_tenure["observed_seasons"].max())
    most_tenured = _tenure[
        _tenure["observed_seasons"] == max_tenure
    ].sort_values("canonical_ensemble_name")
    most_tenured
    return max_tenure, most_tenured


@app.cell(hide_code=True)
def _(max_tenure, mo, most_tenured):
    mo.md(
        f"""
        **Result:** {len(most_tenured)} programs appear in all
        {max_tenure} available seasons. Tenure alone does not identify which
        programs best represent elite or nationally visible competition.
        """
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Representative-program trajectories

    The following six programs were selected by the project owner because they
    consistently attend or win national competition. This roster is used only
    for descriptive trajectories and case studies. It is not a model feature
    and is not presented as an objective ranking.
    """)
    return


@app.cell
def _(plt, representative_programs, terminal_scores):
    _ids = representative_programs["canonical_ensemble_id"].tolist()
    _representative = (
        terminal_scores[
            terminal_scores["canonical_ensemble_id"].isin(_ids)
        ]
        .groupby(
            ["canonical_ensemble_id", "canonical_ensemble_name", "season_year"],
            as_index=False,
        )["subtotal_score"]
        .max()
    )
    _fig, _ax = plt.subplots(figsize=(12, 6))
    for (_, _name), _group in _representative.groupby(
        ["canonical_ensemble_id", "canonical_ensemble_name"]
    ):
        _ax.plot(
            _group["season_year"],
            _group["subtotal_score"],
            marker="o",
            linewidth=2,
            label=_name,
        )
    _ax.set(
        title="Terminal championship trajectories: representative programs",
        xlabel="Season",
        ylabel="Terminal subtotal",
    )
    _ax.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    return _fig


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Interpretation

    Championship medians and weekly progression answer different questions and
    should not be interchanged in the paper. The representative-program panel
    provides domain context, while the full cohort remains the basis for all
    model estimates and circuit-wide conclusions.
    """)
    return


if __name__ == "__main__":
    app.run()
