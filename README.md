# scpadb

**Live web app: [aditgautam.github.io/scpadb](https://aditgautam.github.io/scpadb)**

*This project is also being submitted as the final project for DSC 148 at UC San Diego, Spring 2026.*

This repository is designed to be navigated with an AI agent if desired, documentation lives in `./AGENTS.md`.

This repository serves as the source for **scpadb**, an interactive GUI for
browsing a database of historical SCPA (Southern California Percussion
Alliance) records. It additionally serves as the project repository for the
companion paper *"Forecasting Competitive Percussion Scores Based on Debut
Performance"*. Contained in the repository are the scripts and notebooks that
are needed to reproduce the analyses presented in the paper from scratch,
along with the code that powers the web app.

While score records have always been public, the actual CompetitionSuite
database used by judges has never been available to members or fans. The
scores are organized by show, with no ability to query a centralized database
to find specific records. Consequently, one may need to open dozens of tabs to
simply track an ensemble's score progression or check standings within a
division. This project aims to create a solution by centralizing existing
records into a unified database, creating an intuitive way to interact with
said database, and presenting simple statistical analysis algorithmically
drawn from the data.

The data has been collected from CompetitionSuite recap pages, the list of
links to those recaps was sourced from the publicly available scores tab on
SCPA's official site (https://scpa.live) and is stored in the committed
SQLite database `scores.db`. While the database is committed to ensure the
hosted web app functions as intended, the repository contains all the code
needed to rebuild the database from scratch, including a batched URL list of
all CompetitionSuite Recap links from the 2017-2026 seasons. Ingestion into
the database utilizes [cs-parse], a custom package designed specifically to
parse the HTML tables that scores are posted to. Ingestion is designed to
error handle duplicate detection, score updates, and is modular with the
possibility of ingesting future scores automatically given only a recap link.
In the database, an individual record stores the scores down to the
subcaption of each performance with metadata of the ensemble, performance
information, and judging information. Performance records are pulled exactly
as they appear on the recap, however light database management to account for
group continuity, midseason promotions, and multiple-ensemble programs has
been done, configured in the `./config` folder.

Due to the small size and static nature of the committed database, queries
can be done client-side entirely in the browser using [sql.js], with
visualizations drawn by [D3]. The current live version presents 3 tabs:
- Leaderboard: final season standings which account for promotions, finals
  night score drops, guest participation and more
- Show Records: show day recaps which are directly analagous to the ones
  found on SCPA's official site
- Ensembles: A comprehensive view of all of an ensemble's available records,
  seasonal growth graphs and statistics, accounting for classification
  history and support for programs that field multiple ensembles in a season

## How to run the web app locally

sql.js loads `scores.db` over HTTP, so it needs to be served — opening `index.html` directly via `file://` will NOT work.

```bash
python -m http.server 8000 # or python3 depending on your system
# open http://localhost:8000
```

Alternatively, you can use the VS Code Live Server extension.

`js/sql-wasm.js` and `js/sql-wasm.wasm` must be present before the frontend
will work; if missing, grab them from the
[sql.js releases page](https://github.com/sql-js/sql.js/releases) and place
them in `js/`.

## Repository layout 

```text
scpadb/
├── README.md                  # CURRENT FILE
├── AGENTS.md                  # AI agent guide for a fresh clone of the repo
├── pyproject.toml, uv.lock    # Python 3.12 project + locked dependencies
├── .python-version            # pins Python 3.12 for `uv`
├── scores.db                  # committed SQLite database 
│
├── scripts/                   # the data pipeline, run in this order
│   ├── ingest.py                    # fetch + upsert recap pages into scores.db
│   ├── derive.py                    # rebuild canonical/derived tables & views
│   ├── audit_tracks.py              # ensemble track-continuity audit [maintenance, not part of reproduction]
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
│   ├── ensemble_aliases.csv         # merge heuristic for ensembles that changed their registered name, or dups
│   ├── ensemble_class_tracks.csv    # manual track assignment rules
│   ├── judge_names.csv              # map for judges first names (J. Doe -> John Doe)
│   ├── representative_programs.csv  # selected programs for trajectory plots
│   └── duplicates_manual_check.md   # manual review notes from analysis
│
├── urls/all_seasons.txt       # 127 recap URLs spanning 9 seasons (2017-2026, no 2021)
│
├── index.html                 # web app entry, source for live page
├── js/
│   ├── app.js                       # frontend application logic 
│   ├── sql-wasm.js, sql-wasm.wasm   # sql.js: for SQL WebAssembly capabilities
└── css/style.css
```

## Dependencies

**Python 3.12** ([download](https://www.python.org/downloads/))

The project is managed with **[uv](https://docs.astral.sh/uv/getting-started/installation/)**.

Once both dependencies are installed

```bash
uv sync   # creates .venv/ and installs every locked dependency
```

All commands below should be run with `uv run ...` so they execute inside
that managed environment. No manual `pip install` or `venv` activation
needed. Core dependencies: `cs-parse` (recap parser), `pandas`,
`scikit-learn`, `statsmodels`, `scipy`, `matplotlib`/`seaborn`, `marimo`.

## Reproducing the analysis: the pipeline, step by step

Each script below reads the previous stage's output and writes the next
stage's input. `scores.db` is the single committed source of truth; every
derived table, CSV, figure, and table downstream of it is regenerable.

### 1. Ingest recap data -> `scores.db`

```bash
uv run python scripts/ingest.py --batch urls/all_seasons.txt
# or a single recap:
uv run python scripts/ingest.py "https://recaps.competitionsuite.com/<uuid>.htm"
```
Fetches CompetitionSuite recap pages and **upserts** raw `performances` and
`scores` rows into `scores.db`, using a content hash keyed on each performance's
unique identifier to detect same-day recap corrections or additions without
needing to re-fetch unchanged pages. Output: the committed `scores.db`, updated
in place (raw `performances`/`scores` rows inserted, updated, or skipped).

### 2. Derive canonical/analysis tables

```bash
uv run python scripts/derive.py --rebuild
```

Drops and rebuilds every derived table and view from the raw data plus the
manual mapping rules in `config/` (`ensemble_aliases.csv`,
`ensemble_class_tracks.csv`, `judge_names.csv`): canonical ensembles, events,
season/week calendars, score blocks, judge lookups and block-level z-score
statistics, ensemble track assignments, and mid-season promotion flags.

Output: derived tables/projected views inside `scores.db` (e.g.
`v_frontend_season_leaderboard`, `v_frontend_ensemble_performances`,
`v_judge_block_stats`). This step should be re-run after every ingest or `config/` edit — the
frontend and downstream logic depend on the derived lookup tables.

### 3. Build the modeling cohort

```bash
uv run python scripts/build_model_dataset.py
```

Extracts and assembles the modeling dataset from the derived tables: one row
per ensemble-season debut, with debut score-profile features (raw +
z-normalized subcaptions), prior-history features, and terminal/championship
targets — scoped to marching classes only (PIA/PIO/PIW/PSA/PSJ/PSO/PSW;
Concert classes excluded for incompatible two-caption structure). 

Output:
`analysis/data/model_dataset.csv` (Expected 781 rows × 55 columns, gitignored and should be
regenerated locally). Used downstream by `run_model_analysis.py` and notebook
`04_debut_prediction.py`.

### 4. Dataset Verification

```bash
uv run python scripts/verify_analysis_ready.py
```

Asserts that the database and `model_dataset.csv` match the data used in the
report. Expects 574 development rows with 207 held out, proper midseason
promotion flagging, and the correctness of specific program tracks. This step
should be run before trusting the output of any analysis.

Output: console pass/fail report (no file written).

### 5. Running the analysis scripts

```bash
uv run python scripts/run_descriptive_analysis.py
uv run python scripts/run_model_analysis.py
uv run python scripts/run_secondary_analysis.py
```

Each script reads `scores.db` and/or `analysis/data/model_dataset.csv` and writes
CSV/JSON tables to `analysis/outputs/tables/` along with PNG figures to
`analysis/outputs/figures/` (all gitignored, regenerate locally):

- **`run_descriptive_analysis.py`** — terminal-championship medians, weekly
  score progressions, program tenure, and representative-program trajectories
  (tables + line-plot figures).
- **`run_model_analysis.py`** — the primary modeling pipeline: temporal
  cross-validation, three baselines, Ridge and GBM grid search, six feature
  ablations, held-out evaluation with bootstrap confidence intervals, and
  feature importance figures. This produces the headline result reported in
  the paper.
- **`run_secondary_analysis.py`** — OLS-based score-calibration trends across
  seasons (clustered errors) and judge-residual screening with
  Benjamini-Hochberg correction.

### 6. Explore interactively in Notebooks

The same analyses are mirrored as [Marimo](https://marimo.io/) notebooks
under `analysis/notebooks/`, run `uv run python scripts/derive.py --rebuild`
first, then:

```bash
uv run marimo edit analysis/notebooks/01_eda.py             # opens in browser for editing
uv run marimo run --headless analysis/notebooks/01_eda.py   # runs with no browser
```

Notebooks: `01_eda` (initial EDA and distributions), `02_judge_analysis` (judge
block-level patterns), `03_score_trends` (within-season trends),
`04_debut_prediction` (modeling), `05_secondary_analysis` (score
calibration and judge analysis). 

## Notes for agents

See `AGENTS.md` for a fuller annotated file tree, environment-setup details,
and an end-to-end reproduction checklist written for AI coding agents.
