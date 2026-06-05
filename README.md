# scpadb

Historical SCPA competitive percussion scoring database. Data collected from
CompetitionSuite recap pages using
[cs-parse](https://github.com/aditgautam/cs-parse),
stored in a committed SQLite file, and queryable in-browser via a static HTML
frontend powered by sql.js and D3.

## Setup

    uv sync

## Ingest new data

    uv run python ingest.py "https://recaps.competitionsuite.com/<uuid>.htm"
    uv run python ingest.py --batch urls/all_seasons.txt

## Run the frontend locally

> sql.js requires HTTP (not `file://`), so you must serve the files:

    python -m http.server 8000
    # open http://localhost:8000

**Note:** `js/sql-wasm.js` and `js/sql-wasm.wasm` must be downloaded once before
the frontend will work. Grab them from the
[sql.js releases page](https://github.com/sql-js/sql.js/releases) and place
them in `js/`.

## EDA notebooks

    uv run jupyter notebook notebooks/

## Seed the database from scratch

    uv run python ingest.py --batch urls/all_seasons.txt
    git add scores.db
    git commit -m "seed database with full historical dataset"
