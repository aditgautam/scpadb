# scpadb

Historical SCPA competitive percussion scoring database. Data collected from
CompetitionSuite recap pages using
[cs-parse](https://github.com/aditgautam/cs-parse),
stored in a committed SQLite file, and queryable in-browser via a static HTML
frontend powered by sql.js and D3.

The frontend includes Season Leaderboard, Show Records, Ensemble View, Judge
Statistics, and read-only SQL Query tabs.

## Setup

    uv sync

## Ingest new data

    uv run python scripts/ingest.py "https://recaps.competitionsuite.com/<uuid>.htm"
    uv run python scripts/ingest.py --batch urls/all_seasons.txt

## Rebuild derived analysis tables

After ingesting, rebuild canonical ensemble mappings, event/week metadata, and
judge block statistics:

    uv run python scripts/derive.py --rebuild

Manual ensemble merge rules live in `config/ensemble_aliases.csv`. The raw
`performances` and `scores` tables remain the source of truth; derived tables
and views are rebuilt from them.

Manual judge full-name mappings live in `config/judge_names.csv`. Leave unknown
full-name cells blank; `scripts/derive.py` falls back to the parsed abbreviated
judge label.

## Run the frontend locally

> sql.js requires HTTP (not `file://`), so you must serve the files:

    python -m http.server 8000
    # open http://localhost:8000

**Note:** `js/sql-wasm.js` and `js/sql-wasm.wasm` must be downloaded once before
the frontend will work. Grab them from the
[sql.js releases page](https://github.com/sql-js/sql.js/releases) and place
them in `js/`.

## EDA notebooks

Run `scripts/derive.py --rebuild` before the judge and trend notebooks.

    uv run jupyter notebook notebooks/

## Seed the database from scratch

    uv run python scripts/ingest.py --batch urls/all_seasons.txt
    git add scores.db
    git commit -m "seed database with full historical dataset"
