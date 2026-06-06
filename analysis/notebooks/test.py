import marimo

__generated_with = "0.23.9"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # DB Sanity Check
    Quick debug cells to verify ingestion output is clean and readable.
    """)
    return


@app.cell
def _():
    import sqlite3
    import pandas as pd

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 120)

    import pathlib
    conn = sqlite3.connect(pathlib.Path(__file__).parents[2] / 'scores.db')

    perf_count = conn.execute('SELECT COUNT(*) FROM performances').fetchone()[0]
    score_count = conn.execute('SELECT COUNT(*) FROM scores').fetchone()[0]
    print(f'performances: {perf_count}')
    print(f'scores:       {score_count}')
    return conn, pd


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Canonical Ensembles
    """)
    return


@app.cell
def _(conn, pd):
    ensembles = pd.read_sql("""
        SELECT
            ce.canonical_ensemble_id,
            ce.display_name,
            ce.primary_slug,
            ce.performance_count,
            ce.alias_count,
            GROUP_CONCAT(ea.alias_ensemble_slug, ', ') AS alias_slugs,
            GROUP_CONCAT(ea.alias_name, ', ') AS alias_names
        FROM canonical_ensembles ce
        JOIN ensemble_aliases ea
            ON ea.canonical_ensemble_id = ce.canonical_ensemble_id
        GROUP BY
            ce.canonical_ensemble_id,
            ce.display_name,
            ce.primary_slug,
            ce.performance_count,
            ce.alias_count
        ORDER BY lower(ce.display_name), ce.canonical_ensemble_id
    """, conn)

    print(f'{len(ensembles)} canonical ensembles')
    ensembles
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
 
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
 
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Unique Performance Days
    """)
    return


@app.cell
def _(conn, pd):
    days = pd.read_sql("""
        SELECT performance_date,
               GROUP_CONCAT(DISTINCT competition_name) AS competitions,
               COUNT(*) AS performances
        FROM performances
        GROUP BY performance_date
        ORDER BY performance_date
    """, conn)

    days
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Full Block: PSW Championship Prelims (2026-03-29)

    Percussion Scholastic World class at Championship Prelims, sorted by total score.
    """)
    return


@app.cell
def _(conn, pd):
    block = pd.read_sql("""
        SELECT
            total_rank        AS rank,
            placement         AS place,
            ensemble_name,
            ensemble_location,
            subtotal_score,
            penalty_score,
            total_score
        FROM performances
        WHERE class_code = 'psw'
          AND competition_name = 'Championship Prelims'
          AND performance_date = '2026-03-29'
        ORDER BY total_score DESC
    """, conn)

    block
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Caption scores for one ensemble (spot check)

    Drill into a single performance to verify the scores table is populated correctly.
    """)
    return


@app.cell
def _(conn, pd):
    spot = pd.read_sql("""
        SELECT s.caption, s.subcaption, s.role, s.score, s.rank, s.judge, s.judge_slot
        FROM scores s
        JOIN performances p ON s.performance_key = p.performance_key
        WHERE p.ensemble_name = 'Arcadia HS'
          AND p.performance_date = '2026-03-29'
          AND p.class_code = 'psw'
        ORDER BY s.caption, s.role, s.judge_slot
    """, conn)

    spot
    return


if __name__ == "__main__":
    app.run()
