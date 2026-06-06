# Analysis Workspace

This directory contains research code and generated artifacts for the DSC 148
paper. The root `scores.db` remains the source of truth.

## Layout

```text
analysis/
├── notebooks/
│   ├── test.py                    # sanity checks
│   ├── 01_eda.py                  # distribution exploration
│   ├── 02_judge_analysis.py       # judge block-level patterns
│   ├── 03_score_trends.py         # within-season score trends
│   ├── 04_debut_prediction.py     # debut prediction modeling
│   └── 05_secondary_analysis.py   # score calibration and judge residuals
├── data/                 # generated modeling datasets; contents ignored
└── outputs/
    ├── figures/          # generated plots; contents ignored
    └── tables/           # generated CSV/LaTeX tables; contents ignored
```

Notebooks are Marimo pure-Python files. Run interactively with:

```bash
uv run marimo edit analysis/notebooks/01_eda.py
```

Reusable extraction and modeling logic belongs in `scripts/`, not only in
notebook cells. Generated files must be reproducible from `scores.db`.

## Run

From the repository root:

```bash
uv run python scripts/derive.py --rebuild
uv run python scripts/audit_tracks.py
uv run python scripts/build_model_dataset.py
uv run python scripts/verify_analysis_ready.py
uv run python scripts/run_descriptive_analysis.py
uv run python scripts/run_model_analysis.py
uv run python scripts/run_secondary_analysis.py
uv run marimo edit analysis/notebooks/01_eda.py
```

Notebook database connections use `../../scores.db`.
The generated model input is `analysis/data/model_dataset.csv`; its current
verified shape is 781 rows by 55 columns. See `docs/ANALYSIS_HANDOFF.md` for
the split, feature preferences, exclusions, track rules, and notebook status.
Unconfirmed mid-season findings remain review items, but all multi-class
track-seasons are excluded from the primary model dataset.
