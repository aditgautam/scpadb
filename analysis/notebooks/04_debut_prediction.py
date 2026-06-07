import marimo

__generated_with = "0.23.9"
app = marimo.App()


@app.cell
def _():
    import json
    import pathlib

    import marimo as mo
    import matplotlib.pyplot as plt
    import pandas as pd

    return json, mo, pathlib, pd, plt


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # 04 - Debut-to-Championship Prediction

    **Research question:** How accurately can information available after an
    ensemble's first valid competitive performance forecast its terminal
    championship subtotal?

    **Unit:** one ensemble track-season.

    **Primary target:** terminal championship subtotal, excluding penalties.

    **Development seasons:** 2017-2019 and 2022-2024.

    **Held-out test seasons:** 2025-2026. These seasons are excluded from all
    fitting and hyperparameter tuning. Their results have now been reviewed, so
    they are described as held out rather than untouched.

    The reproducible pipeline lives in `scripts/run_model_analysis.py`. Run it
    after rebuilding `analysis/data/model_dataset.csv`; this notebook reads and
    explains the exported results.
    """)
    return


@app.cell
def _(json, pathlib, pd):
    _root = pathlib.Path(__file__).parents[2]
    _tables = _root / "analysis" / "outputs" / "tables"
    summary = json.loads((_tables / "model_summary.json").read_text())
    holdout_metrics = pd.read_csv(_tables / "holdout_metrics.csv")
    percentile_baselines = pd.read_csv(
        _tables / "percentile_baseline_metrics.csv"
    )
    ablation = pd.read_csv(_tables / "ablation.csv")
    class_metrics = pd.read_csv(_tables / "holdout_by_class.csv")
    excellent = pd.read_csv(_tables / "excellent_predictions.csv")
    largest_errors = pd.read_csv(_tables / "largest_errors.csv")
    coefficients = pd.read_csv(_tables / "ridge_coefficients.csv")
    figure_dir = _root / "analysis" / "outputs" / "figures"
    return (
        ablation,
        class_metrics,
        coefficients,
        excellent,
        figure_dir,
        holdout_metrics,
        largest_errors,
        percentile_baselines,
        summary,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Features and leakage controls

    Features are grouped in a fixed sequence:

    - debut subtotal;
    - debut penalty, timing, and debut class;
    - position within the same event, class, and round;
    - eight normalized score-sheet subcaptions;
    - prior track history;
    - prior class and reclassification direction as a final experimental block.

    No current-season score after debut, championship attendance, terminal
    stage, or championship result is used as an input. All imputation,
    standardization, and category encoding is fitted inside each training fold.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Models and validation

    The primary baselines predict the global median, debut-class median, or use
    debut subtotal unchanged as the terminal-score forecast. The secondary
    baseline uses debut percentile unchanged as the championship-percentile
    forecast. Ridge regression represents a regularized linear model. Gradient
    boosting is the proposed nonlinear model.

    Hyperparameters are selected by expanding-season validation: each fold
    trains only on seasons earlier than its validation season. MAE is measured
    in raw score points; an MAE of 2.68 means the average absolute forecast
    error is approximately 2.68 championship points.
    """)
    return


@app.cell
def _(holdout_metrics):
    holdout_metrics.round(3)
    return


@app.cell
def _(percentile_baselines):
    percentile_baselines.round(3)
    return


@app.cell(hide_code=True)
def _(mo, summary):
    _low, _high = summary["bootstrap_gbm_minus_ridge_mae_ci"]
    mo.md(
        f"""
        **Held-out result:** Ridge achieved MAE
        **{summary['ridge_holdout_mae']:.3f}**, compared with
        **{summary['gbm_holdout_mae']:.3f}** for gradient boosting.

        The 95% composite-track bootstrap interval for
        `GBM MAE - Ridge MAE` is **[{_low:.3f}, {_high:.3f}]**. Positive values
        favor Ridge. The interval is entirely positive after correcting the
        earlier bootstrap identity bug.
        """
    )
    return


@app.cell
def _(figure_dir, plt):
    _image = plt.imread(figure_dir / "model_predicted_vs_observed.png")
    _fig, _ax = plt.subplots(figsize=(10, 7))
    _ax.imshow(_image)
    _ax.axis("off")
    plt.tight_layout()
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Feature ablation

    Each row adds only the features named in its label. Debut penalty enters
    with timing and class, so the prior-history row adds only prior-history
    variables.
    """)
    return


@app.cell
def _(ablation):
    ablation.round(3)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Competition-relative context improves gradient-boosting CV MAE beyond
    score, timing, and class. Score-profile z-scores add little at this sample
    size. Prior history produces the best feature set. Explicit
    reclassification variables do not improve CV MAE, so they are documented
    but excluded from the final model.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Ridge interpretation

    Numeric variables are standardized and class is reference coded. A
    coefficient describes conditional association with predicted championship
    subtotal, not a causal effect. Correlated score features can still divide
    influence across coefficients.
    """)
    return


@app.cell
def _(coefficients):
    (
        coefficients.assign(
            absolute_coefficient=coefficients["coefficient"].abs()
        )
        .sort_values("absolute_coefficient", ascending=False)
        .head(20)
        .round(3)
    )
    return


@app.cell
def _(figure_dir, plt):
    _image = plt.imread(figure_dir / "ridge_coefficients.png")
    _fig, _ax = plt.subplots(figsize=(10, 8))
    _ax.imshow(_image)
    _ax.axis("off")
    plt.tight_layout()
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Performance by class

    PSA represents 112 of 207 held-out observations and has the largest
    held-out MAE. Its median residual is near zero, while its terminal-score and
    residual distributions are the widest among classes. This supports a
    dispersion interpretation rather than a blanket claim of systematic PSA
    overprediction. PIA and PIO estimates are based on very small samples.
    """)
    return


@app.cell
def _(class_metrics):
    class_metrics.round(3)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Excellent forecasts

    These cases demonstrate what “within a fraction of a point” means in
    practice. They are selected after evaluation and are illustrations, not
    evidence of general performance beyond the aggregate metrics.
    """)
    return


@app.cell
def _(excellent):
    excellent[[
        "canonical_ensemble_name",
        "season_year",
        "debut_class_code",
        "terminal_subtotal_score",
        "ridge_prediction",
        "ridge_abs_error",
    ]].head(10).round(3)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Largest errors

    Eight of the ten largest positive residuals are PSA, but PSA also comprises
    54.1% of the holdout, so raw tail counts must be interpreted against its
    much larger sample. Large PSA errors occur in both directions: some groups
    change little after debut, while others gain nearly 20 points. A plausible
    domain interpretation is that A-class groups vary more in show completeness
    at debut than World-class groups. Because show completeness is not recorded,
    this remains an untested explanation rather than a model result.
    """)
    return


@app.cell
def _(largest_errors):
    largest_errors[[
        "canonical_ensemble_name",
        "season_year",
        "debut_class_code",
        "terminal_subtotal_score",
        "ridge_prediction",
        "ridge_residual",
    ]].head(10).round(3)
    return


@app.cell(hide_code=True)
def _(mo, summary):
    mo.md(f"""
    ## Uncertainty and conclusion

    The 90th percentile of expanding-fold absolute Ridge errors is
    **{summary['ridge_oof_abs_error_90pct']:.2f} points**. Applying that
    symmetric empirical error band to the held-out predictions covers
    **{summary['ridge_holdout_band_coverage']:.1%}** of outcomes. This is a
    marginal error band, not a guarantee for an individual ensemble.

    The model forecasts held-out championship scores substantially better
    than global and class-median baselines. Raw debut score is the strongest
    single signal, competition context adds useful information, and prior
    history provides the largest later improvement. The result is
    predictive association in a subjective art activity, not a claim that
    debut placement causes the championship outcome.
    """)
    return


if __name__ == "__main__":
    app.run()
