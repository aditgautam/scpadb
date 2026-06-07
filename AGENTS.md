# AGENTS.md

This file serves as a guide for any AI agent (Claude, Codex, etc.) or contributor 
working in this
repository — the **scpadb** project: a historical SCPA competitive percussion
scoring database, a static in-browser frontend for it, and the data pipeline
behind the companion paper *"Forecasting Competitive Percussion Scores Based
on Debut Performance."*

This file documents the **tracked** repository — what a fresh `git clone`
actually contains — and how to reproduce the full pipeline from scratch with
[`uv`](https://docs.astral.sh/uv/).

## Tracked file tree

```text
scpadb/
├── README.md                  # human-facing overview, setup, pipeline walkthrough
├── AGENTS.md                  # this file
├── pyproject.toml, uv.lock    # Python 3.12 project + locked dependencies
├── .python-version            # pins Python 3.12 for `uv`
├── scores.db                  # committed SQLite database — source of truth
│
├── scripts/                   # the data pipeline, run in this order
│   ├── ingest.py                    # fetch + upsert recap pages into scores.db
│   ├── derive.py                    # rebuild canonical/derived tables & views
│   ├── audit_tracks.py              # [maintenance] ensemble track-continuity audit
│   ├── build_model_dataset.py       # build the 781-row modeling cohort CSV
│   ├── verify_analysis_ready.py     # assert DB + dataset invariants
│   ├── run_descriptive_analysis.py  # descriptive tables + figures
│   ├── run_model_analysis.py        # primary modeling (Ridge/GBM, CV, holdout)
│   └── run_secondary_analysis.py    # score calibration + judge residual screening
│
├── analysis/
│   ├── notebooks/             # Marimo pure-Python notebooks (interactive mirrors
│   │   ├── test.py            #   of the scripts above, run with `uv run marimo edit`)
│   │   ├── 01_eda.py
│   │   ├── 02_judge_analysis.py
│   │   ├── 03_score_trends.py
│   │   ├── 04_debut_prediction.py
│   │   └── 05_secondary_analysis.py
│   ├── data/                  # generated model_dataset.csv (gitignored, .gitkeep only)
│   └── outputs/
│       ├── figures/           # generated plots (gitignored, .gitkeep only)
│       └── tables/            # generated CSV/JSON tables (gitignored, .gitkeep only)
│
├── config/                    # manual mapping/rule files consumed by derive.py
│   ├── ensemble_aliases.csv         # canonical ensemble merge rules
│   ├── ensemble_class_tracks.csv    # manual track assignment rules
│   ├── judge_names.csv              # judge display-name mappings
│   ├── representative_programs.csv  # curated programs for trajectory plots
│   └── duplicates_manual_check.md   # human review notes
│
├── urls/all_seasons.txt       # 127 recap URLs spanning 9 seasons (2017-2026, no 2021)
│
├── index.html                 # frontend entry point — the live scpadb web app
├── js/
│   ├── app.js                       # frontend application logic (queries + views + charts)
│   ├── sql-wasm.js, sql-wasm.wasm   # sql.js — SQLite compiled to WebAssembly
└── css/style.css
```

Notable **untracked** paths you'll see locally but won't find in a clone:
`report/` (LaTeX paper source, submitted separately), `.agents/`, `.claude/`,
`skills-lock.json` (local AI tooling config), `.venv/`, `analysis/data/*.csv`,
`analysis/outputs/**/*` (generated — see "Reproducing the pipeline").

## Environment setup with `uv`

Requires Python 3.12 (pinned in `.python-version`) and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv sync                 # creates .venv/ and installs locked dependencies
uv run python <script>  # run any script inside the project's environment
uv run marimo edit <notebook.py>           # open a notebook interactively (browser)
uv run marimo run --headless <notebook.py> # execute a notebook without opening a browser
```

Core dependencies (see `pyproject.toml`): `cs-parse` (recap-page parser),
`pandas`, `scikit-learn`, `statsmodels`, `scipy`, `matplotlib`/`seaborn`,
`marimo`. `ruff` is used for linting.

## Reproducing the pipeline end to end

Each stage reads the previous stage's output; `scores.db` is the one
committed artifact everything else derives from or feeds back into.

1. **Ingest** — `uv run python scripts/ingest.py --batch urls/all_seasons.txt`
   Fetches CompetitionSuite recap pages and upserts raw `performances`/`scores`
   rows into `scores.db` (content-hashed, idempotent). For a single recap:
   `uv run python scripts/ingest.py "<recap-url>"`.

2. **Derive** — `uv run python scripts/derive.py --rebuild`
   Rebuilds every derived table/view from raw data + `config/*.csv`: canonical
   ensembles & aliases, events, season/week calendars, score blocks, judge
   lookups and block-level z-score stats, track assignments, and promotion
   flags. Re-run this after any ingest or `config/` edit.

3. **Build the model dataset** — `uv run python scripts/build_model_dataset.py`
   Produces `analysis/data/model_dataset.csv` (781 rows × 55 columns: identity,
   debut score-profile features, prior-history features, and terminal/holdout
   targets), scoped to marching classes only (PIA/PIO/PIW/PSA/PSJ/PSO/PSW;
   Concert excluded). Asserts one debut + one terminal performance per
   track-season and no duplication.

4. **Verify** — `uv run python scripts/verify_analysis_ready.py`
   Checks the database and `model_dataset.csv` against known-good invariants
   (row/column counts, dev/holdout split sizes, promotion flags, representative
   program coverage). Run this after any pipeline change before trusting
   downstream analysis.

5. **Analyze** — run independently, each writes to `analysis/outputs/`:
   ```bash
   uv run python scripts/run_descriptive_analysis.py   # score trends, program tenure, trajectories
   uv run python scripts/run_model_analysis.py         # Ridge/GBM CV, ablations, holdout eval, figures
   uv run python scripts/run_secondary_analysis.py     # adjusted season effects, judge residual screening
   ```
   Or work interactively in the matching Marimo notebooks under
   `analysis/notebooks/` (`uv run marimo edit analysis/notebooks/04_debut_prediction.py`).

6. **Frontend** (no build step — static + client-side):
   ```bash
   python -m http.server 8000   # sql.js requires HTTP, not file://
   # open http://localhost:8000
   ```
   Loads `scores.db` into the browser via sql.js/WASM and queries it directly;
   no backend server. Live at https://aditgautam.github.io/scpadb.


## Database maintenance / debugging tools

`scripts/audit_tracks.py` is **not** part of the reproduction pipeline above —
it's a database-debugging utility for reviewing ensemble track-continuity
assignments (cases where a program's class changed mid-season or across
seasons, and whether that should be treated as one continuing "track" or
separate ones). Run it with:

```bash
uv run python scripts/audit_tracks.py
```

By default it writes a Markdown report to `docs/TRACK_AUDIT.md`. Running the
script creates a `docs/` directory if one doesn't already exist — this won't
be present in a fresh clone:

```text
docs/
└── TRACK_AUDIT.md   # only created if you run scripts/audit_tracks.py — untracked, won't exist in a fresh clone
```

This is intentional: the audit is a maintainer tool for reviewing/adjusting
`config/ensemble_class_tracks.csv`, not an artifact the study depends on.
Pass `--out <path>` to write it elsewhere.
