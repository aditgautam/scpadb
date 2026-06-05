#!/usr/bin/env python3
"""Ingest cs-parse data into scores.db.

Usage:
    uv run python ingest.py "https://recaps.competitionsuite.com/<uuid>.htm"
    uv run python ingest.py --batch urls/all_seasons.txt
    uv run python ingest.py --db path/to/other.db "https://..."
    uv run python ingest.py --debug "https://..."
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from competition_suite_parser.source import parse_batch_manifest, parse_source

DB_PATH = Path("scores.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS performances (
    performance_key      TEXT PRIMARY KEY,
    content_hash         TEXT NOT NULL,
    ensemble_name        TEXT NOT NULL,
    ensemble_slug        TEXT NOT NULL,
    ensemble_location    TEXT,
    class_code           TEXT NOT NULL,
    class_name_raw       TEXT,
    performance_date     TEXT NOT NULL,
    round                INTEGER,
    competition_name     TEXT NOT NULL,
    competition_slug     TEXT NOT NULL,
    competition_location TEXT,
    subtotal_score       REAL,
    subtotal_rank        INTEGER,
    penalty_score        REAL,
    total_score          REAL,
    total_rank           INTEGER,
    placement            INTEGER,
    ingested_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_perf_ensemble ON performances(ensemble_slug);
CREATE INDEX IF NOT EXISTS idx_perf_date     ON performances(performance_date);
CREATE INDEX IF NOT EXISTS idx_perf_class    ON performances(class_code);

CREATE TABLE IF NOT EXISTS scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    performance_key TEXT NOT NULL REFERENCES performances(performance_key),
    caption         TEXT NOT NULL,
    subcaption      TEXT NOT NULL,
    role            TEXT NOT NULL,
    score           REAL NOT NULL,
    rank            INTEGER,
    judge           TEXT,
    judge_slot      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_scores_perf    ON scores(performance_key);
CREATE INDEX IF NOT EXISTS idx_scores_judge   ON scores(judge);
CREATE INDEX IF NOT EXISTS idx_scores_caption ON scores(caption, subcaption);

CREATE TABLE IF NOT EXISTS ingest_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    inserted    INTEGER NOT NULL,
    updated     INTEGER NOT NULL,
    skipped     INTEGER NOT NULL
);
"""

_DROPPED_FIELDS = {"performance_hash", "identity_hash", "round_raw"}


def _init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _content_hash(perf: dict) -> str:
    # Hash score-relevant fields; excludes stable identity fields and fields
    # we drop. Detects mid-day recap corrections without re-fetching everything.
    fields = {k: v for k, v in perf.items() if k not in _DROPPED_FIELDS}
    canonical = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _map_performance(perf: dict, now: str) -> dict:
    competition = perf.get("competition") or {}
    subtotal = perf.get("subtotal") or {}
    penalty = perf.get("penalty") or {}
    total = perf.get("total") or {}
    return {
        "performance_key": perf["performance_key"],
        "content_hash": _content_hash(perf),
        "ensemble_name": perf["ensemble_name"],
        "ensemble_slug": perf["ensemble_slug"],
        "ensemble_location": perf.get("ensemble_location"),
        "class_code": perf["class_code"],
        "class_name_raw": perf.get("class_name_raw"),
        "performance_date": perf["performance_date"],
        "round": perf.get("round"),
        "competition_name": competition.get("name", ""),
        "competition_slug": competition.get("slug", ""),
        "competition_location": competition.get("location"),
        "subtotal_score": subtotal.get("score"),
        "subtotal_rank": subtotal.get("rank"),
        "penalty_score": penalty.get("score"),
        "total_score": total.get("score"),
        "total_rank": total.get("rank"),
        "placement": perf.get("placement"),
        "ingested_at": now,
    }


def _insert_scores(conn: sqlite3.Connection, key: str, score_rows: list) -> None:
    conn.executemany(
        """INSERT INTO scores
           (performance_key, caption, subcaption, role, score, rank, judge, judge_slot)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                key,
                s["caption"],
                s["subcaption"],
                s["role"],
                s["score"],
                s.get("rank"),
                s.get("judge"),
                s.get("judge_slot"),
            )
            for s in score_rows
        ],
    )


def _upsert(conn: sqlite3.Connection, perf: dict, now: str, debug: bool) -> str:
    p = _map_performance(perf, now)
    key = p["performance_key"]

    row = conn.execute(
        "SELECT content_hash FROM performances WHERE performance_key = ?", (key,)
    ).fetchone()

    if row is None:
        conn.execute(
            """INSERT INTO performances VALUES (
                :performance_key, :content_hash, :ensemble_name, :ensemble_slug,
                :ensemble_location, :class_code, :class_name_raw, :performance_date,
                :round, :competition_name, :competition_slug, :competition_location,
                :subtotal_score, :subtotal_rank, :penalty_score,
                :total_score, :total_rank, :placement, :ingested_at
            )""",
            p,
        )
        _insert_scores(conn, key, perf.get("scores", []))
        if debug:
            print(f"  INSERT {key}")
        return "inserted"

    if row[0] == p["content_hash"]:
        if debug:
            print(f"  SKIP   {key}")
        return "skipped"

    conn.execute(
        """UPDATE performances SET
            content_hash=:content_hash, ensemble_name=:ensemble_name,
            ensemble_slug=:ensemble_slug, ensemble_location=:ensemble_location,
            class_code=:class_code, class_name_raw=:class_name_raw,
            performance_date=:performance_date, round=:round,
            competition_name=:competition_name, competition_slug=:competition_slug,
            competition_location=:competition_location,
            subtotal_score=:subtotal_score, subtotal_rank=:subtotal_rank,
            penalty_score=:penalty_score, total_score=:total_score,
            total_rank=:total_rank, placement=:placement,
            ingested_at=:ingested_at
        WHERE performance_key=:performance_key""",
        p,
    )
    conn.execute("DELETE FROM scores WHERE performance_key = ?", (key,))
    _insert_scores(conn, key, perf.get("scores", []))
    if debug:
        print(f"  UPDATE {key}")
    return "updated"


def ingest(
    conn: sqlite3.Connection,
    performances: list,
    source: str,
    debug: bool = False,
) -> None:
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    now = datetime.now(timezone.utc).isoformat()

    with conn:
        for perf in performances:
            result = _upsert(conn, perf, now, debug)
            counts[result] += 1

        conn.execute(
            "INSERT INTO ingest_log (source, ingested_at, inserted, updated, skipped)"
            " VALUES (?, ?, ?, ?, ?)",
            (source, now, counts["inserted"], counts["updated"], counts["skipped"]),
        )

    print(
        f"inserted={counts['inserted']} updated={counts['updated']} skipped={counts['skipped']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest cs-parse data into scores.db")
    parser.add_argument("url", nargs="?", help="Single recap URL to ingest")
    parser.add_argument("--batch", metavar="FILE", help="Manifest file with one URL per line")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite DB path (default: scores.db)")
    parser.add_argument("--debug", action="store_true", help="Print per-row INSERT/UPDATE/SKIP")
    args = parser.parse_args()

    if not args.url and not args.batch:
        parser.error("Provide a URL or --batch FILE")

    conn = _init_db(Path(args.db))

    if args.batch:
        result = parse_batch_manifest(args.batch)
        performances = result["performances"]
        source = args.batch
        errors = [s for s in result["sources"] if s["status"] != "parsed"]
        for e in errors:
            print(f"WARN  [{e['status']}] {e['source']}: {e.get('error', '')}", file=sys.stderr)
    else:
        performances = parse_source(args.url)
        source = args.url

    ingest(conn, performances, source, debug=args.debug)


if __name__ == "__main__":
    main()
