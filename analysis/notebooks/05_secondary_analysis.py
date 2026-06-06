import marimo

__generated_with = "0.23.9"
app = marimo.App()


@app.cell
def _():
    import pathlib

    import marimo as mo
    import matplotlib.pyplot as plt
    import pandas as pd

    return mo, pathlib, pd, plt


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # 05 - Secondary Analyses

    This notebook addresses two observational questions:

    1. Are later-season scores higher after accounting for class, week, stage,
       and ensemble track?
    2. Do any repeated judge-program-caption pairs remain unusual after a basic
       expected-score adjustment?

    These analyses are secondary. They do not alter the predictive model and
    should not be described causally.
    """)
    return


@app.cell
def _(pathlib, pd):
    _root = pathlib.Path(__file__).parents[2]
    _tables = _root / "analysis" / "outputs" / "tables"
    season_effects = pd.read_csv(_tables / "adjusted_season_effects.csv")
    season_descriptives = pd.read_csv(
        _tables / "season_score_descriptives.csv"
    )
    judge_pairs = pd.read_csv(_tables / "judge_residual_pairs.csv")
    figure_dir = _root / "analysis" / "outputs" / "figures"
    return figure_dir, judge_pairs, season_descriptives, season_effects


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Adjusted season-score model

    An OLS model predicts artifact-free subtotal from season, class, SCPA week,
    event stage, and ensemble-track fixed effects. Standard errors are clustered
    by composite ensemble track. Coefficients below are differences from 2017,
    conditional on those controls.

    This is stronger than comparing raw yearly means, but it cannot control for
    changing show quality, repertoire, staff, membership, or scoring-sheet
    instructions.
    """)
    return


@app.cell
def _(season_effects):
    season_effects.round(3)
    return


@app.cell
def _(figure_dir, plt):
    _image = plt.imread(figure_dir / "adjusted_season_effects.png")
    _fig, _ax = plt.subplots(figsize=(10, 6))
    _ax.imshow(_image)
    _ax.axis("off")
    plt.tight_layout()
    return _fig


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The estimates do not show a simple monotonic post-pandemic rise. Relative
    to 2017, 2019 and 2025 are significantly higher at the conventional 0.05
    level, while 2022-2024 and 2026 are not distinguishable from 2017 after
    adjustment. This does not support a broad claim that every recent season
    is uniformly inflated.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Descriptive high-score frequency

    The share of 90-plus performances is shown as context only. It changes with
    class mix, schedule timing, and participating programs, so it is not itself
    a score-inflation test.
    """)
    return


@app.cell
def _(season_descriptives):
    season_descriptives.round(3)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Judge-program residual screen

    Expected block z-score is modeled using ensemble track, class, season, week,
    caption, subcaption, and stage. For each judge-track-caption pair with at
    least five scores, its residual mean is compared with residuals assigned to
    the same track and caption by other judges. Benjamini-Hochberg correction is
    applied across tested pairs.

    This screen produces many flagged pairs, indicating that the remaining
    residuals are not independent enough for simple pairwise tests to support a
    clean paper claim. Repeated observations share shows, ensembles, and judge
    assignment mechanisms. The table is retained for methodological
    transparency, but individual names should not be highlighted as evidence of
    favoritism.
    """)
    return


@app.cell
def _(judge_pairs, pd):
    judge_summary = pd.DataFrame({
        "eligible_pairs": [len(judge_pairs)],
        "BH_adjusted_flags": [int(judge_pairs["flag_after_bh"].sum())],
        "minimum_pair_observations": [int(judge_pairs["pair_observations"].min())],
        "median_pair_observations": [judge_pairs["pair_observations"].median()],
    })
    judge_summary
    return


@app.cell
def _(judge_pairs):
    judge_pairs[[
        "judge_display_name",
        "canonical_ensemble_name",
        "caption",
        "pair_observations",
        "difference",
        "p_adjusted_bh",
        "flag_after_bh",
    ]].head(20).round(3)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Paper recommendation

    Include the adjusted season-score figure as a cautious secondary result.
    Omit named judge-pair findings from the main paper unless a hierarchical
    repeated-measures model and stronger assignment controls are added. The
    defensible conclusion is that the current data cannot isolate judge liking
    from schedule, assignment, and ensemble-quality confounding.
    """)
    return


if __name__ == "__main__":
    app.run()
