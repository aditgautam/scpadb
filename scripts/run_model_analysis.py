#!/usr/bin/env python3
"""Run the debut-to-championship modeling analysis and export results."""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DEV_SEASONS = [2017, 2018, 2019, 2022, 2023, 2024]
HOLDOUT_SEASONS = [2025, 2026]
TARGET = "terminal_subtotal_score"
RANDOM_STATE = 42

FEAT_SCORE = ["debut_subtotal_score"]
FEAT_PENALTY = ["debut_penalty_score"]
FEAT_TIMING = ["debut_week", "debut_week_index", "debut_day_of_week"]
FEAT_COMP = [
    "debut_event_field_size",
    "debut_score_percentile",
    "debut_score_gap_to_class_leader",
    "debut_score_gap_to_class_median",
]
FEAT_PROFILE_RAW = [
    "debut_em_music_effect",
    "debut_em_overall_effect",
    "debut_ev_overall_effect",
    "debut_ev_visual_effect",
    "debut_mu_composition",
    "debut_mu_performance",
    "debut_vi_composition",
    "debut_vi_performance",
]
FEAT_PROFILE_Z = [f"{column}_z" for column in FEAT_PROFILE_RAW]
FEAT_PROFILE_MISSING = [f"{column}_missing" for column in FEAT_PROFILE_RAW]
FEAT_PRIOR = [
    "has_prior_history",
    "prior_champ_percentile",
    "prior_champ_subtotal",
    "n_prior_seasons",
    "years_since_prior",
]
CAT_CLASS = ["debut_class_code"]
CAT_RECLASS = ["prior_class_code", "class_change_direction"]

RIDGE_ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
GBM_GRID = [
    {
        "n_estimators": n_estimators,
        "learning_rate": learning_rate,
        "max_depth": max_depth,
        "min_samples_leaf": min_samples_leaf,
    }
    for n_estimators in [50, 100, 200]
    for learning_rate in [0.03, 0.05, 0.1]
    for max_depth in [1, 2, 3]
    for min_samples_leaf in [5, 10, 20]
]

ABLATIONS = {
    "A: debut score only": (FEAT_SCORE, []),
    "B: + timing and class": (FEAT_SCORE + FEAT_TIMING, CAT_CLASS),
    "C: + competition context": (
        FEAT_SCORE + FEAT_TIMING + FEAT_COMP,
        CAT_CLASS,
    ),
    "D: + score profile": (
        FEAT_SCORE + FEAT_TIMING + FEAT_COMP + FEAT_PROFILE_Z + FEAT_PROFILE_MISSING,
        CAT_CLASS,
    ),
    "E: + prior history": (
        FEAT_SCORE
        + FEAT_PENALTY
        + FEAT_TIMING
        + FEAT_COMP
        + FEAT_PROFILE_Z
        + FEAT_PROFILE_MISSING
        + FEAT_PRIOR,
        CAT_CLASS,
    ),
    "F: + reclassification": (
        FEAT_SCORE
        + FEAT_PENALTY
        + FEAT_TIMING
        + FEAT_COMP
        + FEAT_PROFILE_Z
        + FEAT_PROFILE_MISSING
        + FEAT_PRIOR,
        CAT_CLASS + CAT_RECLASS,
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="analysis/data/model_dataset.csv")
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
            "axes.labelcolor": "#222222",
            "axes.titleweight": "bold",
            "axes.grid": True,
            "grid.color": "#ebebeb",
            "grid.linewidth": 0.8,
            "text.color": "#000000",
            "xtick.color": "#555555",
            "ytick.color": "#555555",
        }
    )


def temporal_folds(data: pd.DataFrame):
    for index in range(1, len(DEV_SEASONS)):
        train_seasons = DEV_SEASONS[:index]
        validation_season = DEV_SEASONS[index]
        train = data[data["season_year"].isin(train_seasons)]
        validation = data[data["season_year"] == validation_season]
        yield train_seasons, validation_season, train, validation


def build_preprocessor(
    numeric_features: list[str], categorical_features: list[str]
) -> ColumnTransformer:
    transformers = []
    if numeric_features:
        transformers.append(
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric_features,
            )
        )
    if categorical_features:
        transformers.append(
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        (
                            "ohe",
                            OneHotEncoder(
                                handle_unknown="ignore",
                                drop="first",
                                sparse_output=False,
                            ),
                        ),
                    ]
                ),
                categorical_features,
            )
        )
    return ColumnTransformer(transformers, remainder="drop")


def make_pipeline(model, numeric_features, categorical_features) -> Pipeline:
    return Pipeline(
        [
            ("pre", build_preprocessor(numeric_features, categorical_features)),
            ("model", model),
        ]
    )


def metric_row(label: str, actual, predicted) -> dict[str, float | str]:
    predicted_array = np.asarray(predicted)
    rho = (
        np.nan
        if np.unique(predicted_array).size < 2
        else spearmanr(actual, predicted_array).statistic
    )
    return {
        "model": label,
        "mae": mean_absolute_error(actual, predicted),
        "rmse": np.sqrt(mean_squared_error(actual, predicted)),
        "r2": r2_score(actual, predicted),
        "spearman_rho": rho,
        "mean_residual": np.mean(predicted_array - np.asarray(actual)),
    }


def baseline_cv(dev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, validation_season, train, validation in temporal_folds(dev):
        global_median = train[TARGET].median()
        class_medians = train.groupby("debut_class_code")[TARGET].median()
        class_prediction = (
            validation["debut_class_code"].map(class_medians).fillna(global_median)
        )
        rows.extend(
            [
                {
                    "model": "Global median",
                    "validation_season": validation_season,
                    "mae": mean_absolute_error(
                        validation[TARGET],
                        np.repeat(global_median, len(validation)),
                    ),
                },
                {
                    "model": "Class median",
                    "validation_season": validation_season,
                    "mae": mean_absolute_error(validation[TARGET], class_prediction),
                },
            ]
        )
    return pd.DataFrame(rows)


def tune_ridge(dev, numeric_features, categorical_features):
    rows = []
    for alpha in RIDGE_ALPHAS:
        fold_maes = []
        for _, _, train, validation in temporal_folds(dev):
            model = make_pipeline(
                Ridge(alpha=alpha), numeric_features, categorical_features
            )
            columns = numeric_features + categorical_features
            model.fit(train[columns], train[TARGET])
            fold_maes.append(
                mean_absolute_error(
                    validation[TARGET], model.predict(validation[columns])
                )
            )
        rows.append({"alpha": alpha, "cv_mae": np.mean(fold_maes)})
    results = pd.DataFrame(rows)
    best_alpha = float(results.loc[results["cv_mae"].idxmin(), "alpha"])
    return best_alpha, results


def tune_gbm(dev, numeric_features, categorical_features):
    rows = []
    columns = numeric_features + categorical_features
    for params in GBM_GRID:
        fold_maes = []
        for _, _, train, validation in temporal_folds(dev):
            model = make_pipeline(
                GradientBoostingRegressor(random_state=RANDOM_STATE, **params),
                numeric_features,
                categorical_features,
            )
            model.fit(train[columns], train[TARGET])
            fold_maes.append(
                mean_absolute_error(
                    validation[TARGET], model.predict(validation[columns])
                )
            )
        rows.append({**params, "cv_mae": np.mean(fold_maes)})
    results = pd.DataFrame(rows).sort_values("cv_mae").reset_index(drop=True)
    keys = ["n_estimators", "learning_rate", "max_depth", "min_samples_leaf"]
    best = results.iloc[0][keys].to_dict()
    best["n_estimators"] = int(best["n_estimators"])
    best["max_depth"] = int(best["max_depth"])
    best["min_samples_leaf"] = int(best["min_samples_leaf"])
    return best, results


def model_cv(
    dev,
    label,
    model_factory,
    numeric_features,
    categorical_features,
    collect_oof=False,
):
    rows = []
    oof_rows = []
    columns = numeric_features + categorical_features
    for train_seasons, validation_season, train, validation in temporal_folds(dev):
        model = make_pipeline(
            model_factory(), numeric_features, categorical_features
        )
        model.fit(train[columns], train[TARGET])
        predicted = model.predict(validation[columns])
        row = metric_row(label, validation[TARGET], predicted)
        row.update(
            {
                "validation_season": validation_season,
                "train_seasons": ",".join(map(str, train_seasons)),
                "train_n": len(train),
                "validation_n": len(validation),
            }
        )
        rows.append(row)
        if collect_oof:
            fold = validation[
                [
                    "canonical_ensemble_id",
                    "track_id",
                    "season_year",
                    TARGET,
                ]
            ].copy()
            fold["predicted"] = predicted
            fold["residual"] = fold["predicted"] - fold[TARGET]
            fold["abs_error"] = fold["residual"].abs()
            oof_rows.append(fold)
    oof = pd.concat(oof_rows, ignore_index=True) if oof_rows else pd.DataFrame()
    return pd.DataFrame(rows), oof


def run_ablation(dev, best_gbm_params):
    rows = []
    for label, (numeric_features, categorical_features) in ABLATIONS.items():
        fold_results, _ = model_cv(
            dev,
            label,
            lambda: GradientBoostingRegressor(
                random_state=RANDOM_STATE, **best_gbm_params
            ),
            numeric_features,
            categorical_features,
        )
        rows.append(
            {
                "feature_set": label,
                "numeric_features": len(numeric_features),
                "categorical_features": len(categorical_features),
                "cv_mae": fold_results["mae"].mean(),
                "cv_rmse": fold_results["rmse"].mean(),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_difference(holdout_predictions, replicates=2000):
    rng = np.random.default_rng(RANDOM_STATE)
    keys = (
        holdout_predictions["canonical_ensemble_id"].astype(str)
        + "|"
        + holdout_predictions["track_id"].astype(str)
    )
    unique_keys = keys.unique()
    differences = []
    actual = holdout_predictions[TARGET].to_numpy()
    ridge = holdout_predictions["ridge_prediction"].to_numpy()
    gbm = holdout_predictions["gbm_prediction"].to_numpy()
    for _ in range(replicates):
        sampled = rng.choice(unique_keys, size=len(unique_keys), replace=True)
        indices = np.concatenate(
            [np.flatnonzero(keys.to_numpy() == key) for key in sampled]
        )
        differences.append(
            mean_absolute_error(actual[indices], gbm[indices])
            - mean_absolute_error(actual[indices], ridge[indices])
        )
    return np.percentile(differences, [2.5, 97.5])


def feature_names(model: Pipeline, numeric_features, categorical_features):
    names = list(numeric_features)
    if categorical_features:
        encoder = model.named_steps["pre"].named_transformers_["cat"].named_steps[
            "ohe"
        ]
        names.extend(encoder.get_feature_names_out(categorical_features))
    return names


def save_plots(predictions, coefficients, output_dir):
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    for class_code, group in predictions.groupby("debut_class_code"):
        ax.scatter(
            group[TARGET],
            group["ridge_prediction"],
            label=class_code.upper(),
            alpha=0.72,
            s=28,
        )
    bounds = [
        min(predictions[TARGET].min(), predictions["ridge_prediction"].min()) - 1,
        max(predictions[TARGET].max(), predictions["ridge_prediction"].max()) + 1,
    ]
    ax.plot(bounds, bounds, color="#000000", linewidth=1.2, linestyle="--")
    ax.set(xlabel="Observed terminal subtotal", ylabel="Ridge prediction")
    ax.set_title("Held-out predictions, 2025-2026")
    ax.legend(ncol=2, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(figures_dir / "model_predicted_vs_observed.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.scatter(
        predictions["ridge_prediction"],
        predictions["ridge_residual"],
        color="#555555",
        alpha=0.7,
        s=28,
    )
    ax.axhline(0, color="#000000", linewidth=1.2)
    ax.set(xlabel="Ridge prediction", ylabel="Prediction - observed")
    ax.set_title("Held-out residuals")
    fig.tight_layout()
    fig.savefig(figures_dir / "model_residuals.png", dpi=200)
    plt.close(fig)

    top = coefficients.reindex(
        coefficients["coefficient"].abs().sort_values(ascending=False).index
    ).head(18)
    colors = np.where(top["coefficient"] >= 0, "#1b6e3a", "#9f1d1d")
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    ax.barh(top["feature"][::-1], top["coefficient"][::-1], color=colors[::-1])
    ax.axvline(0, color="#000000", linewidth=0.8)
    ax.set_xlabel("Standardized Ridge coefficient")
    ax.set_title("Largest Ridge coefficients")
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    fig.savefig(figures_dir / "ridge_coefficients.png", dpi=200)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    output_dir = Path(args.output)
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    set_plot_style()
    warnings.filterwarnings(
        "ignore", message="Skipping features without any observed values"
    )
    warnings.filterwarnings(
        "ignore", message="Found unknown categories in columns"
    )

    data = pd.read_csv(data_path)
    dev = data[data["season_year"].isin(DEV_SEASONS)].copy()
    holdout = data[data["season_year"].isin(HOLDOUT_SEASONS)].copy()

    baseline_folds = baseline_cv(dev)
    baseline_folds.to_csv(tables_dir / "baseline_cv.csv", index=False)

    primary_numeric, primary_categorical = ABLATIONS["E: + prior history"]
    best_alpha, ridge_grid = tune_ridge(
        dev, primary_numeric, primary_categorical
    )
    best_gbm_params, gbm_grid = tune_gbm(
        dev, primary_numeric, primary_categorical
    )
    ridge_grid.to_csv(tables_dir / "ridge_grid.csv", index=False)
    gbm_grid.to_csv(tables_dir / "gbm_grid.csv", index=False)

    ridge_folds, ridge_oof = model_cv(
        dev,
        "Ridge",
        lambda: Ridge(alpha=best_alpha),
        primary_numeric,
        primary_categorical,
        collect_oof=True,
    )
    gbm_folds, _ = model_cv(
        dev,
        "GBM",
        lambda: GradientBoostingRegressor(
            random_state=RANDOM_STATE, **best_gbm_params
        ),
        primary_numeric,
        primary_categorical,
    )
    cv_results = pd.concat([ridge_folds, gbm_folds], ignore_index=True)
    cv_results.to_csv(tables_dir / "model_cv.csv", index=False)

    ablation = run_ablation(dev, best_gbm_params)
    ablation.to_csv(tables_dir / "ablation.csv", index=False)

    columns = primary_numeric + primary_categorical
    ridge_final = make_pipeline(
        Ridge(alpha=best_alpha), primary_numeric, primary_categorical
    )
    gbm_final = make_pipeline(
        GradientBoostingRegressor(
            random_state=RANDOM_STATE, **best_gbm_params
        ),
        primary_numeric,
        primary_categorical,
    )
    ridge_final.fit(dev[columns], dev[TARGET])
    gbm_final.fit(dev[columns], dev[TARGET])

    predictions = holdout[
        [
            "canonical_ensemble_id",
            "canonical_ensemble_name",
            "track_id",
            "season_year",
            "debut_class_code",
            "affiliation",
            "terminal_stage",
            "debut_week",
            "has_prior_history",
            TARGET,
        ]
    ].copy()
    predictions["ridge_prediction"] = ridge_final.predict(holdout[columns])
    predictions["gbm_prediction"] = gbm_final.predict(holdout[columns])
    for model in ["ridge", "gbm"]:
        predictions[f"{model}_residual"] = (
            predictions[f"{model}_prediction"] - predictions[TARGET]
        )
        predictions[f"{model}_abs_error"] = predictions[
            f"{model}_residual"
        ].abs()

    global_median = dev[TARGET].median()
    class_medians = dev.groupby("debut_class_code")[TARGET].median()
    predictions["global_median_prediction"] = global_median
    predictions["class_median_prediction"] = (
        holdout["debut_class_code"].map(class_medians).fillna(global_median)
    )

    holdout_metrics = pd.DataFrame(
        [
            metric_row(
                "Global median",
                predictions[TARGET],
                predictions["global_median_prediction"],
            ),
            metric_row(
                "Class median",
                predictions[TARGET],
                predictions["class_median_prediction"],
            ),
            metric_row(
                "Ridge",
                predictions[TARGET],
                predictions["ridge_prediction"],
            ),
            metric_row(
                "GBM",
                predictions[TARGET],
                predictions["gbm_prediction"],
            ),
        ]
    )
    holdout_metrics.to_csv(tables_dir / "holdout_metrics.csv", index=False)

    class_metrics = (
        predictions.groupby("debut_class_code")
        .agg(
            n=(TARGET, "size"),
            ridge_mae=("ridge_abs_error", "mean"),
            ridge_bias=("ridge_residual", "mean"),
            gbm_mae=("gbm_abs_error", "mean"),
        )
        .reset_index()
    )
    class_metrics.to_csv(tables_dir / "holdout_by_class.csv", index=False)

    prediction_band = float(ridge_oof["abs_error"].quantile(0.90))
    predictions["ridge_lower_90"] = predictions["ridge_prediction"] - prediction_band
    predictions["ridge_upper_90"] = predictions["ridge_prediction"] + prediction_band
    coverage = float(
        (
            (predictions[TARGET] >= predictions["ridge_lower_90"])
            & (predictions[TARGET] <= predictions["ridge_upper_90"])
        ).mean()
    )
    predictions.to_csv(tables_dir / "holdout_predictions.csv", index=False)
    predictions.nsmallest(10, "ridge_abs_error").to_csv(
        tables_dir / "excellent_predictions.csv", index=False
    )
    predictions.nlargest(10, "ridge_abs_error").to_csv(
        tables_dir / "largest_errors.csv", index=False
    )

    names = feature_names(ridge_final, primary_numeric, primary_categorical)
    coefficients = pd.DataFrame(
        {
            "feature": names,
            "coefficient": ridge_final.named_steps["model"].coef_,
        }
    ).sort_values("coefficient", ascending=False)
    coefficients.to_csv(tables_dir / "ridge_coefficients.csv", index=False)

    ci_low, ci_high = bootstrap_difference(predictions)
    summary = {
        "development_rows": len(dev),
        "holdout_rows": len(holdout),
        "best_ridge_alpha": best_alpha,
        "best_gbm_params": best_gbm_params,
        "ridge_cv_mae": ridge_folds["mae"].mean(),
        "gbm_cv_mae": gbm_folds["mae"].mean(),
        "ridge_holdout_mae": holdout_metrics.loc[
            holdout_metrics["model"] == "Ridge", "mae"
        ].iloc[0],
        "gbm_holdout_mae": holdout_metrics.loc[
            holdout_metrics["model"] == "GBM", "mae"
        ].iloc[0],
        "bootstrap_gbm_minus_ridge_mae_ci": [ci_low, ci_high],
        "ridge_oof_abs_error_90pct": prediction_band,
        "ridge_holdout_band_coverage": coverage,
        "ablation_best": ablation.loc[ablation["cv_mae"].idxmin()].to_dict(),
    }
    (tables_dir / "model_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    save_plots(predictions, coefficients, output_dir)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
