# Analysis Workspace

This directory contains research code and generated artifacts for the DSC 148
paper. The root `scores.db` remains the source of truth.

## Layout

```text
analysis/
├── notebooks/
│   ├── test.ipynb
│   ├── 01_eda.ipynb
│   ├── 02_judge_analysis.ipynb
│   └── 03_score_trends.ipynb
├── data/                 # generated modeling datasets; contents ignored
└── outputs/
    ├── figures/          # generated plots; contents ignored
    └── tables/           # generated CSV/LaTeX tables; contents ignored
```

Future project notebooks should use:

- `04_debut_prediction.ipynb` for the primary model.
- `05_secondary_analysis.ipynb` for score inflation and judge residuals.

Reusable extraction and modeling logic belongs in `scripts/`, not only in
notebook cells. Generated files must be reproducible from `scores.db`.

## Run

From the repository root:

```bash
uv run python scripts/derive.py --rebuild
uv run python scripts/audit_tracks.py
uv run python scripts/build_model_dataset.py
uv run python scripts/verify_analysis_ready.py
uv run jupyter notebook analysis/notebooks/
```

Notebook database connections use `../../scores.db`.
The generated model input is `analysis/data/model_dataset.csv`; its current
verified shape is 781 rows by 53 columns. See `docs/ANALYSIS_HANDOFF.md` for
the split, feature preferences, exclusions, track rules, and notebook status.
Unconfirmed mid-season findings remain review items, but all multi-class
track-seasons are excluded from the primary model dataset.
