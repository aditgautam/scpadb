# scpadb

Historical SCPA competitive percussion scoring database. Data collected from
CompetitionSuite recap pages using
[cs-parse](https://github.com/aditgautam/cs-parse),
stored in a committed SQLite file, and queryable in-browser via a static HTML
frontend powered by sql.js and D3.

The live frontend exposes Season Leaderboard, Show Records, and Ensemble View.
Judge Statistics and the read-only SQL Query view remain implemented but hidden
for the current pre-deploy build.

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

Manual judge mappings live in `config/judge_names.csv`. Fill
`judge_first_name` when the surname is already present in the parsed judge
label. Use `judge_name_override` only when the exact display name cannot be
derived from that label. Leave unresolved names blank; `scripts/derive.py`
falls back to the parsed abbreviated judge label.

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
