#!/usr/bin/env python3
"""Rebuild derived lookup tables and analysis views for scores.db."""

import argparse
import csv
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path("scores.db")
ALIASES_PATH = Path("config/ensemble_aliases.csv")
TRACKS_PATH = Path("config/ensemble_class_tracks.csv")
JUDGES_PATH = Path("config/judge_names.csv")

DERIVED_VIEWS = [
    "v_frontend_show_scores",
    "v_frontend_show_performances",
    "v_frontend_ensemble_performances",
    "v_judge_block_stats",
    "v_score_blocks",
    "v_performances_canonical",
]

DERIVED_TABLES = [
    "v_frontend_season_leaderboard",
    "ensemble_track_assignments",
    "ensemble_track_season_flags",
    "ensemble_class_tracks",
    "ensemble_multi_group_seasons",
    "ensemble_class_season_flags",
    "duplicate_ensemble_candidates",
    "analysis_excluded_performances",
    "judge_lookup",
    "judge_block_stats",
    "score_blocks",
    "season_weekends",
    "events",
    "ensemble_aliases",
    "canonical_ensembles",
]


@dataclass(frozen=True)
class AliasRule:
    canonical_id: str
    display_name: str
    alias_slug: str
    alias_name: str
    notes: str


@dataclass(frozen=True)
class TrackRule:
    canonical_id: str
    track_id: str
    track_label: str
    class_codes: str
    season_years: str
    assignments: tuple[tuple[str, int], ...]
    notes: str


@dataclass(frozen=True)
class JudgeRule:
    judge_abbrev: str
    judge_first_name: str
    judge_name_override: str
    notes: str


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_alias_rules(path: Path) -> dict[str, AliasRule]:
    if not path.exists():
        return {}

    rules: dict[str, AliasRule] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            alias_slug = row["alias_ensemble_slug"].strip()
            if not alias_slug:
                continue
            rule = AliasRule(
                canonical_id=row["canonical_ensemble_id"].strip(),
                display_name=row["display_name"].strip(),
                alias_slug=alias_slug,
                alias_name=row["alias_name"].strip(),
                notes=row.get("notes", "").strip(),
            )
            existing = rules.get(alias_slug)
            if existing and existing.canonical_id != rule.canonical_id:
                raise ValueError(
                    f"Alias slug {alias_slug!r} maps to both "
                    f"{existing.canonical_id!r} and {rule.canonical_id!r}"
                )
            rules[alias_slug] = rule
    return rules


def _load_track_rules(path: Path) -> dict[str, list[TrackRule]]:
    if not path.exists():
        return {}

    rules: dict[str, list[TrackRule]] = defaultdict(list)
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            canonical_id = row["canonical_ensemble_id"].strip()
            track_id = row["track_id"].strip()
            if not canonical_id or not track_id:
                continue
            class_codes = ",".join(
                code.strip().lower()
                for code in row["class_codes"].split(",")
                if code.strip()
            )
            season_years = ",".join(
                year.strip()
                for year in row["season_years"].split(",")
                if year.strip()
            )
            assignments = []
            assignment_text = row.get("assignments", "").strip()
            for segment in assignment_text.split(";"):
                if not segment.strip():
                    continue
                class_code, separator, years_text = segment.partition(":")
                if not separator:
                    raise ValueError(
                        f"Invalid track assignment {segment!r}; expected class:year,year"
                    )
                assignments.extend(
                    (class_code.strip().lower(), int(year.strip()))
                    for year in years_text.split(",")
                    if year.strip()
                )
            rules[canonical_id].append(
                TrackRule(
                    canonical_id=canonical_id,
                    track_id=track_id,
                    track_label=row["track_label"].strip(),
                    class_codes=class_codes,
                    season_years=season_years,
                    assignments=tuple(assignments),
                    notes=row.get("notes", "").strip(),
                )
            )
    return rules


def _load_judge_rules(path: Path) -> dict[str, JudgeRule]:
    if not path.exists():
        return {}

    rules: dict[str, JudgeRule] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            abbrev = row["judge_abbrev"].strip()
            if not abbrev:
                continue
            rules[abbrev] = JudgeRule(
                judge_abbrev=abbrev,
                judge_first_name=(
                    row.get("judge_first_name", "")
                    or row.get("judge_full_name", "")
                ).strip(),
                judge_name_override=row.get("judge_name_override", "").strip(),
                notes=row.get("notes", "").strip(),
            )
    return rules


def _judge_last_name(abbrev: str) -> str:
    parts = abbrev.split()
    return parts[-1] if len(parts) > 1 else ""


def _judge_full_name(abbrev: str, rule: JudgeRule | None) -> str | None:
    if not rule:
        return None
    if rule.judge_name_override:
        return rule.judge_name_override
    if not rule.judge_first_name:
        return None
    last_name = _judge_last_name(abbrev)
    return f"{rule.judge_first_name} {last_name}".strip()


def _reset_derived_objects(conn: sqlite3.Connection) -> None:
    for name in DERIVED_VIEWS:
        conn.execute(f"DROP VIEW IF EXISTS {name}")
    for name in DERIVED_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {name}")


def _event_stage(name: str, slug: str) -> tuple[str, int, int]:
    text = f"{name} {slug}".lower()
    is_championship = int("championship" in text)
    has_prelims = "prelim" in text
    has_semis = "semi" in text
    has_finals = "final" in text

    if not is_championship:
        return "regular", 0, 0
    if sum([has_prelims, has_semis, has_finals]) > 1:
        return "mixed_championship", 1, int(has_finals)
    if has_finals:
        return "championship_finals", 1, 1
    if has_semis:
        return "championship_semifinals", 1, 0
    if has_prelims:
        return "championship_prelims", 1, 0
    return "championship", 1, 0


def _weekend_start(performance_date: str) -> str:
    dt = datetime.strptime(performance_date, "%Y-%m-%d").date()
    if dt.weekday() == 6:
        dt -= timedelta(days=1)
    return dt.isoformat()


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE canonical_ensembles (
            canonical_ensemble_id TEXT PRIMARY KEY,
            display_name          TEXT NOT NULL,
            primary_slug          TEXT NOT NULL,
            source                TEXT NOT NULL,
            first_seen            TEXT NOT NULL,
            last_seen             TEXT NOT NULL,
            performance_count     INTEGER NOT NULL,
            alias_count           INTEGER NOT NULL,
            notes                 TEXT
        );

        CREATE TABLE ensemble_aliases (
            alias_ensemble_slug   TEXT NOT NULL,
            alias_name            TEXT NOT NULL,
            canonical_ensemble_id TEXT NOT NULL REFERENCES canonical_ensembles(canonical_ensemble_id),
            display_name          TEXT NOT NULL,
            source                TEXT NOT NULL,
            notes                 TEXT,
            PRIMARY KEY (alias_ensemble_slug, alias_name)
        );

        CREATE TABLE events (
            event_id             TEXT PRIMARY KEY,
            performance_date     TEXT NOT NULL,
            season_year          INTEGER NOT NULL,
            competition_slug     TEXT NOT NULL,
            competition_name     TEXT NOT NULL,
            competition_location TEXT,
            weekend_start        TEXT NOT NULL,
            event_stage          TEXT NOT NULL,
            is_championship      INTEGER NOT NULL,
            is_finals            INTEGER NOT NULL,
            performance_count    INTEGER NOT NULL
        );

        CREATE TABLE season_weekends (
            season_year          INTEGER NOT NULL,
            weekend_start        TEXT NOT NULL,
            season_week_calendar INTEGER NOT NULL,
            season_week_index    INTEGER NOT NULL,
            event_count          INTEGER NOT NULL,
            performance_count    INTEGER NOT NULL,
            PRIMARY KEY (season_year, weekend_start)
        );

        CREATE TABLE score_blocks (
            score_block_id       TEXT PRIMARY KEY,
            event_id             TEXT NOT NULL REFERENCES events(event_id),
            season_year          INTEGER NOT NULL,
            season_week_calendar INTEGER NOT NULL,
            season_week_index    INTEGER NOT NULL,
            performance_date     TEXT NOT NULL,
            competition_slug     TEXT NOT NULL,
            competition_name     TEXT NOT NULL,
            event_stage          TEXT NOT NULL,
            class_code           TEXT NOT NULL,
            round                INTEGER,
            caption              TEXT NOT NULL,
            subcaption           TEXT NOT NULL,
            judge                TEXT NOT NULL,
            judge_slot           INTEGER,
            score_count          INTEGER NOT NULL,
            min_score            REAL NOT NULL,
            max_score            REAL NOT NULL,
            mean_score           REAL NOT NULL,
            score_range          REAL NOT NULL,
            stddev_score         REAL
        );

        CREATE TABLE judge_lookup (
            judge_abbrev       TEXT PRIMARY KEY,
            judge_full_name    TEXT,
            judge_display_name TEXT NOT NULL,
            notes              TEXT
        );

        CREATE TABLE judge_block_stats (
            score_id             INTEGER PRIMARY KEY REFERENCES scores(id),
            score_block_id       TEXT NOT NULL REFERENCES score_blocks(score_block_id),
            performance_key      TEXT NOT NULL REFERENCES performances(performance_key),
            canonical_ensemble_id TEXT NOT NULL REFERENCES canonical_ensembles(canonical_ensemble_id),
            score                REAL NOT NULL,
            rank                 INTEGER,
            block_mean_score     REAL NOT NULL,
            block_stddev_score   REAL,
            block_z_score        REAL,
            block_score_count    INTEGER NOT NULL,
            block_score_range    REAL NOT NULL,
            judge                TEXT NOT NULL,
            caption              TEXT NOT NULL,
            subcaption           TEXT NOT NULL
        );

        CREATE TABLE duplicate_ensemble_candidates (
            candidate_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ensemble_slug_a      TEXT NOT NULL,
            ensemble_name_a      TEXT NOT NULL,
            ensemble_slug_b      TEXT NOT NULL,
            ensemble_name_b      TEXT NOT NULL,
            reason               TEXT NOT NULL
        );

        CREATE TABLE analysis_excluded_performances (
            performance_key TEXT PRIMARY KEY REFERENCES performances(performance_key),
            reason          TEXT NOT NULL,
            detected_by     TEXT NOT NULL
        );
        """
    )


def _build_analysis_exclusions(conn: sqlite3.Connection) -> None:
    """Flag records retained in the database but excluded from analysis."""
    conn.execute(
        """
        INSERT INTO analysis_excluded_performances
        (performance_key, reason, detected_by)
        SELECT
            performance_key,
            'all_zero_score_artifact',
            'subtotal_score = 0 AND total_score = 0'
        FROM performances
        WHERE subtotal_score = 0
          AND total_score = 0
        """
    )


def _observed_ensembles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            ensemble_slug,
            ensemble_name,
            min(performance_date) AS first_seen,
            max(performance_date) AS last_seen,
            count(*) AS performance_count
        FROM performances
        GROUP BY ensemble_slug, ensemble_name
        ORDER BY ensemble_slug, ensemble_name
        """
    ).fetchall()


def _display_name_for_slug(rows: list[sqlite3.Row]) -> str:
    return max(rows, key=lambda r: (r["performance_count"], r["last_seen"]))["ensemble_name"]


def _build_ensembles(conn: sqlite3.Connection, alias_rules: dict[str, AliasRule]) -> None:
    observed = _observed_ensembles(conn)
    rows_by_slug: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in observed:
        rows_by_slug[row["ensemble_slug"]].append(row)

    canonical_rows: dict[str, dict] = {}
    alias_rows: list[tuple] = []

    for slug, rows in rows_by_slug.items():
        rule = alias_rules.get(slug)
        canonical_id = rule.canonical_id if rule else slug
        display_name = rule.display_name if rule else _display_name_for_slug(rows)
        source = "manual" if rule else "auto"
        notes = rule.notes if rule else None
        first_seen = min(r["first_seen"] for r in rows)
        last_seen = max(r["last_seen"] for r in rows)
        performance_count = sum(r["performance_count"] for r in rows)

        existing = canonical_rows.get(canonical_id)
        if existing:
            existing["first_seen"] = min(existing["first_seen"], first_seen)
            existing["last_seen"] = max(existing["last_seen"], last_seen)
            existing["performance_count"] += performance_count
            existing["alias_count"] += len(rows)
            if source == "manual" and (
                existing["source"] != "manual" or slug == canonical_id
            ):
                existing["display_name"] = display_name
                existing["primary_slug"] = slug
                existing["source"] = source
                existing["notes"] = notes
        else:
            canonical_rows[canonical_id] = {
                "canonical_id": canonical_id,
                "display_name": display_name,
                "primary_slug": slug,
                "source": source,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "performance_count": performance_count,
                "alias_count": len(rows),
                "notes": notes,
            }

        for row in rows:
            alias_rows.append(
                (
                    row["ensemble_slug"],
                    row["ensemble_name"],
                    canonical_id,
                    display_name,
                    source,
                    notes,
                )
            )

    conn.executemany(
        """
        INSERT INTO canonical_ensembles
        (canonical_ensemble_id, display_name, primary_slug, source, first_seen,
         last_seen, performance_count, alias_count, notes)
        VALUES
        (:canonical_id, :display_name, :primary_slug, :source, :first_seen,
         :last_seen, :performance_count, :alias_count, :notes)
        """,
        list(canonical_rows.values()),
    )
    conn.executemany(
        """
        INSERT INTO ensemble_aliases
        (alias_ensemble_slug, alias_name, canonical_ensemble_id, display_name, source, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        alias_rows,
    )


def _build_events(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            performance_date,
            competition_slug,
            competition_name,
            competition_location,
            count(*) AS performance_count
        FROM performances
        GROUP BY performance_date, competition_slug, competition_name, competition_location
        ORDER BY performance_date, competition_slug
        """
    ).fetchall()

    event_rows = []
    for row in rows:
        stage, is_championship, is_finals = _event_stage(
            row["competition_name"], row["competition_slug"]
        )
        event_rows.append(
            (
                f"{row['performance_date']}|{row['competition_slug']}",
                row["performance_date"],
                int(row["performance_date"][:4]),
                row["competition_slug"],
                row["competition_name"],
                row["competition_location"],
                _weekend_start(row["performance_date"]),
                stage,
                is_championship,
                is_finals,
                row["performance_count"],
            )
        )

    conn.executemany(
        """
        INSERT INTO events
        (event_id, performance_date, season_year, competition_slug, competition_name,
         competition_location, weekend_start, event_stage, is_championship,
         is_finals, performance_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        event_rows,
    )


def _build_season_weekends(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            season_year,
            weekend_start,
            count(*) AS event_count,
            sum(performance_count) AS performance_count
        FROM events
        GROUP BY season_year, weekend_start
        ORDER BY season_year, weekend_start
        """
    ).fetchall()
    by_year: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_year[row["season_year"]].append(row)

    inserts = []
    for year, year_rows in by_year.items():
        first = date.fromisoformat(year_rows[0]["weekend_start"])
        for index, row in enumerate(year_rows, start=1):
            current = date.fromisoformat(row["weekend_start"])
            calendar_week = ((current - first).days // 7) + 1
            inserts.append(
                (
                    year,
                    row["weekend_start"],
                    calendar_week,
                    index,
                    row["event_count"],
                    row["performance_count"],
                )
            )

    conn.executemany(
        """
        INSERT INTO season_weekends
        (season_year, weekend_start, season_week_calendar, season_week_index,
         event_count, performance_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return variance**0.5


def _build_score_blocks(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            e.event_id,
            e.season_year,
            sw.season_week_calendar,
            sw.season_week_index,
            p.performance_date,
            p.competition_slug,
            p.competition_name,
            e.event_stage,
            p.class_code,
            p.round,
            s.caption,
            s.subcaption,
            s.judge,
            s.judge_slot,
            s.score
        FROM scores s
        JOIN performances p ON p.performance_key = s.performance_key
        JOIN events e ON e.performance_date = p.performance_date
            AND e.competition_slug = p.competition_slug
        JOIN season_weekends sw ON sw.season_year = e.season_year
            AND sw.weekend_start = e.weekend_start
        WHERE s.role = 'raw_score'
          AND s.judge IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM analysis_excluded_performances aep
              WHERE aep.performance_key = p.performance_key
          )
        ORDER BY e.event_id, p.class_code, p.round, s.caption, s.subcaption, s.judge, s.judge_slot
        """
    ).fetchall()

    grouped: dict[tuple, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        key = (
            row["event_id"],
            row["class_code"],
            row["round"],
            row["caption"],
            row["subcaption"],
            row["judge"],
            row["judge_slot"],
        )
        grouped[key].append(row)

    inserts = []
    for key, block_rows in grouped.items():
        first = block_rows[0]
        scores = [float(r["score"]) for r in block_rows]
        score_min = min(scores)
        score_max = max(scores)
        score_mean = sum(scores) / len(scores)
        block_id = "|".join("" if part is None else str(part) for part in key)
        inserts.append(
            (
                block_id,
                first["event_id"],
                first["season_year"],
                first["season_week_calendar"],
                first["season_week_index"],
                first["performance_date"],
                first["competition_slug"],
                first["competition_name"],
                first["event_stage"],
                first["class_code"],
                first["round"],
                first["caption"],
                first["subcaption"],
                first["judge"],
                first["judge_slot"],
                len(scores),
                score_min,
                score_max,
                score_mean,
                score_max - score_min,
                _stddev(scores),
            )
        )

    conn.executemany(
        """
        INSERT INTO score_blocks
        (score_block_id, event_id, season_year, season_week_calendar,
         season_week_index, performance_date, competition_slug,
         competition_name, event_stage, class_code, round, caption, subcaption, judge,
         judge_slot, score_count, min_score, max_score, mean_score,
         score_range, stddev_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )


def _build_judge_lookup(conn: sqlite3.Connection, judge_rules: dict[str, JudgeRule]) -> None:
    observed = conn.execute(
        """
        SELECT DISTINCT judge
        FROM scores
        WHERE judge IS NOT NULL AND trim(judge) <> ''
        ORDER BY judge
        """
    ).fetchall()

    inserts = []
    for row in observed:
        abbrev = row["judge"]
        rule = judge_rules.get(abbrev)
        full_name = _judge_full_name(abbrev, rule)
        notes = rule.notes if rule else ""
        inserts.append((abbrev, full_name, full_name or abbrev, notes))

    conn.executemany(
        """
        INSERT INTO judge_lookup
        (judge_abbrev, judge_full_name, judge_display_name, notes)
        VALUES (?, ?, ?, ?)
        """,
        inserts,
    )


def _build_judge_block_stats(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            s.id AS score_id,
            s.performance_key,
            s.score,
            s.rank,
            s.judge,
            s.caption,
            s.subcaption,
            ea.canonical_ensemble_id,
            sb.score_block_id,
            sb.mean_score,
            sb.stddev_score,
            sb.score_count,
            sb.score_range
        FROM scores s
        JOIN performances p ON p.performance_key = s.performance_key
        JOIN ensemble_aliases ea ON ea.alias_ensemble_slug = p.ensemble_slug
            AND ea.alias_name = p.ensemble_name
        JOIN events e ON e.performance_date = p.performance_date
            AND e.competition_slug = p.competition_slug
        JOIN score_blocks sb ON sb.event_id = e.event_id
            AND sb.class_code = p.class_code
            AND (sb.round = p.round OR (sb.round IS NULL AND p.round IS NULL))
            AND sb.caption = s.caption
            AND sb.subcaption = s.subcaption
            AND sb.judge = s.judge
            AND (sb.judge_slot = s.judge_slot OR (sb.judge_slot IS NULL AND s.judge_slot IS NULL))
        WHERE s.role = 'raw_score'
          AND s.judge IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM analysis_excluded_performances aep
              WHERE aep.performance_key = s.performance_key
          )
        ORDER BY s.id
        """
    ).fetchall()

    inserts = []
    for row in rows:
        stddev = row["stddev_score"]
        z_score = None
        if stddev and stddev > 0:
            z_score = (row["score"] - row["mean_score"]) / stddev
        inserts.append(
            (
                row["score_id"],
                row["score_block_id"],
                row["performance_key"],
                row["canonical_ensemble_id"],
                row["score"],
                row["rank"],
                row["mean_score"],
                stddev,
                z_score,
                row["score_count"],
                row["score_range"],
                row["judge"],
                row["caption"],
                row["subcaption"],
            )
        )

    conn.executemany(
        """
        INSERT INTO judge_block_stats
        (score_id, score_block_id, performance_key, canonical_ensemble_id,
         score, rank, block_mean_score, block_stddev_score, block_z_score,
         block_score_count, block_score_range, judge, caption, subcaption)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )


def _normalized_name(name: str) -> str:
    return (
        name.lower()
        .replace(" percussion", "")
        .replace(" hs", "")
        .replace(" high school", "")
        .replace("(", "")
        .replace(")", "")
        .replace("-", " ")
        .replace("_", " ")
        .strip()
    )


def _build_duplicate_candidates(conn: sqlite3.Connection) -> None:
    canonical_by_slug = {
        row["alias_ensemble_slug"]: row["canonical_ensemble_id"]
        for row in conn.execute(
            """
            SELECT alias_ensemble_slug, canonical_ensemble_id
            FROM ensemble_aliases
            GROUP BY alias_ensemble_slug, canonical_ensemble_id
            """
        )
    }
    rows = conn.execute(
        """
        SELECT
            ensemble_slug,
            min(ensemble_name) AS ensemble_name
        FROM performances
        GROUP BY ensemble_slug
        ORDER BY ensemble_slug
        """
    ).fetchall()
    inserts = []
    for i, left in enumerate(rows):
        for right in rows[i + 1 :]:
            if (
                canonical_by_slug.get(left["ensemble_slug"])
                == canonical_by_slug.get(right["ensemble_slug"])
            ):
                continue
            left_name = _normalized_name(left["ensemble_name"])
            right_name = _normalized_name(right["ensemble_name"])
            reason = None
            if left_name == right_name:
                reason = "normalized_name_match"
            elif left_name and right_name and (
                left_name.startswith(right_name) or right_name.startswith(left_name)
            ):
                reason = "normalized_name_prefix"
            if not reason:
                continue
            inserts.append(
                (
                    left["ensemble_slug"],
                    left["ensemble_name"],
                    right["ensemble_slug"],
                    right["ensemble_name"],
                    reason,
                )
            )

    conn.executemany(
        """
        INSERT INTO duplicate_ensemble_candidates
        (ensemble_slug_a, ensemble_name_a, ensemble_slug_b, ensemble_name_b, reason)
        VALUES (?, ?, ?, ?, ?)
        """,
        inserts,
    )


_STAGE_PRIORITY: dict[str, int] = {
    "championship_finals": 1,
    "championship_semifinals": 2,
    "mixed_championship": 2,
    "championship": 2,
    "championship_prelims": 3,
    "regular": 4,
}
_CONCERT_CLASSES = {"psca", "psco", "pscw"}
_MARCHING_CLASSES = {"pia", "pio", "piw", "psa", "pso", "psw"}


def _class_format(class_code: str) -> str:
    if class_code in _CONCERT_CLASSES:
        return "concert"
    if class_code == "psj":
        return "junior"
    if class_code in _MARCHING_CLASSES:
        return "marching"
    return "other"


def _build_ensemble_class_season_flags(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        INSERT INTO ensemble_class_season_flags
        WITH class_ranges AS (
            SELECT
                canonical_ensemble_id,
                canonical_ensemble_name,
                season_year,
                class_code,
                min(performance_date) AS first_date,
                max(performance_date) AS last_date,
                count(*) AS performance_count
            FROM v_frontend_ensemble_performances
            GROUP BY canonical_ensemble_id, canonical_ensemble_name, season_year, class_code
        ),
        multi_class AS (
            SELECT
                canonical_ensemble_id,
                canonical_ensemble_name,
                season_year,
                group_concat(upper(class_code)) AS class_codes,
                count(*) AS class_count
            FROM (
                SELECT *
                FROM class_ranges
                ORDER BY canonical_ensemble_id, season_year, class_code
            )
            GROUP BY canonical_ensemble_id, canonical_ensemble_name, season_year
            HAVING count(*) > 1
        ),
        same_date AS (
            SELECT
                canonical_ensemble_id,
                season_year,
                count(*) AS same_date_count
            FROM (
                SELECT canonical_ensemble_id, season_year, performance_date
                FROM v_frontend_ensemble_performances
                GROUP BY canonical_ensemble_id, season_year, performance_date
                HAVING count(DISTINCT class_code) > 1
            )
            GROUP BY canonical_ensemble_id, season_year
        )
        SELECT
            mc.canonical_ensemble_id,
            mc.canonical_ensemble_name,
            mc.season_year,
            mc.class_codes,
            mc.class_count,
            COALESCE(sd.same_date_count, 0) AS same_date_count,
            CASE
                WHEN COALESCE(sd.same_date_count, 0) > 0 THEN 'multi_ensemble_likely'
                ELSE 'class_change_candidate'
            END AS signal
        FROM multi_class mc
        LEFT JOIN same_date sd
            ON sd.canonical_ensemble_id = mc.canonical_ensemble_id
            AND sd.season_year = mc.season_year;

        INSERT INTO ensemble_multi_group_seasons
        SELECT
            canonical_ensemble_id,
            season_year,
            lower(class_codes) AS class_codes
        FROM ensemble_class_season_flags
        WHERE signal = 'multi_ensemble_likely';
        """
    )


def _build_ensemble_class_tracks(
    conn: sqlite3.Connection, track_rules: dict[str, list[TrackRule]]
) -> None:
    rows = conn.execute(
        """
        SELECT
            canonical_ensemble_id,
            canonical_ensemble_name,
            season_year,
            class_code,
            min(performance_date) AS first_date,
            max(performance_date) AS last_date
        FROM v_frontend_ensemble_performances
        GROUP BY canonical_ensemble_id, canonical_ensemble_name, season_year, class_code
        ORDER BY canonical_ensemble_id, first_date, class_code
        """
    ).fetchall()

    by_ensemble: dict[str, list[sqlite3.Row]] = defaultdict(list)
    names: dict[str, str] = {}
    for row in rows:
        cid = row["canonical_ensemble_id"]
        by_ensemble[cid].append(row)
        names[cid] = row["canonical_ensemble_name"]

    multi_line_formats = {
        (row["canonical_ensemble_id"], row["class_format"])
        for row in conn.execute(
            """
            WITH classified AS (
                SELECT
                    canonical_ensemble_id,
                    season_year,
                    performance_date,
                    display_stage,
                    class_code,
                    CASE
                        WHEN class_code IN ('psca','psco','pscw') THEN 'concert'
                        WHEN class_code = 'psj' THEN 'junior'
                        WHEN class_code IN ('pia','pio','piw','psa','pso','psw') THEN 'marching'
                        ELSE 'other'
                    END AS class_format
                FROM v_frontend_ensemble_performances
            ),
            same_date AS (
                SELECT canonical_ensemble_id, class_format
                FROM classified
                GROUP BY canonical_ensemble_id, season_year, performance_date, class_format
                HAVING COUNT(DISTINCT class_code) > 1
            ),
            multiple_prelims AS (
                SELECT canonical_ensemble_id, class_format
                FROM classified
                WHERE display_stage = 'championship_prelims'
                GROUP BY canonical_ensemble_id, season_year, class_format
                HAVING COUNT(DISTINCT class_code) > 1
            )
            SELECT canonical_ensemble_id, class_format FROM same_date
            UNION
            SELECT canonical_ensemble_id, class_format FROM multiple_prelims
            """
        )
    }

    inserts = []
    assignment_inserts = []
    for cid, ensemble_rows in by_ensemble.items():
        manual_rules = track_rules.get(cid, [])
        if manual_rules:
            for display_order, rule in enumerate(manual_rules, start=1):
                label = rule.track_label or rule.track_id
                inserts.append(
                    (
                        cid,
                        names[cid],
                        rule.track_id,
                        label,
                        rule.class_codes,
                        rule.season_years,
                        display_order,
                        "manual",
                        rule.notes,
                    )
                )
                assignments = rule.assignments or tuple(
                    (class_code, int(season_year))
                    for class_code in rule.class_codes.split(",")
                    for season_year in rule.season_years.split(",")
                )
                assignment_inserts.extend(
                    (cid, rule.track_id, class_code, season_year)
                    for class_code, season_year in assignments
                )
            continue

        rows_by_format: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in ensemble_rows:
            rows_by_format[_class_format(row["class_code"])].append(row)

        display_order = 0
        for class_format, format_rows in sorted(rows_by_format.items()):
            class_codes = sorted({row["class_code"] for row in format_rows})
            season_years = sorted({str(row["season_year"]) for row in format_rows})
            latest_class = max(
                format_rows, key=lambda row: (row["last_date"], row["class_code"])
            )["class_code"]

            if len(class_codes) == 1:
                cls = class_codes[0]
                track_id = f"class:{cls}"
                display_order += 1
                inserts.append(
                    (
                        cid,
                        names[cid],
                        track_id,
                        cls.upper(),
                        cls,
                        ",".join(season_years),
                        display_order,
                        "auto_single_class",
                        None,
                    )
                )
                assignment_inserts.extend(
                    (cid, track_id, cls, int(year)) for year in season_years
                )
                continue

            if (cid, class_format) in multi_line_formats:
                for cls in class_codes:
                    years = sorted(
                        {
                            str(row["season_year"])
                            for row in format_rows
                            if row["class_code"] == cls
                        }
                    )
                    track_id = f"class:{cls}"
                    display_order += 1
                    inserts.append(
                        (
                            cid,
                            names[cid],
                            track_id,
                            cls.upper(),
                            cls,
                            ",".join(years),
                            display_order,
                            "auto_multi_ensemble_class",
                            None,
                        )
                    )
                    assignment_inserts.extend(
                        (cid, track_id, cls, int(year)) for year in years
                    )
                continue

            track_id = f"track:{class_format}"
            display_order += 1
            inserts.append(
                (
                    cid,
                    names[cid],
                    track_id,
                    latest_class.upper(),
                    ",".join(class_codes),
                    ",".join(season_years),
                    display_order,
                    "auto_class_change",
                    "Continuous line inferred because no season shows evidence "
                    f"of multiple {class_format} ensembles.",
                )
            )
            assignment_inserts.extend(
                (cid, track_id, row["class_code"], row["season_year"])
                for row in format_rows
            )

    conn.executemany(
        """
        INSERT INTO ensemble_class_tracks
        (canonical_ensemble_id, canonical_ensemble_name, track_id, track_label,
         class_codes, season_years, display_order, source, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )
    conn.executemany(
        """
        INSERT INTO ensemble_track_assignments
        (canonical_ensemble_id, track_id, class_code, season_year)
        VALUES (?, ?, ?, ?)
        """,
        assignment_inserts,
    )

    mixed_format_tracks = conn.execute(
        """
        SELECT canonical_ensemble_id, track_id
        FROM ensemble_track_assignments
        GROUP BY canonical_ensemble_id, track_id
        HAVING COUNT(DISTINCT CASE
            WHEN class_code IN ('psca','psco','pscw') THEN 'concert'
            WHEN class_code = 'psj' THEN 'junior'
            WHEN class_code IN ('pia','pio','piw','psa','pso','psw') THEN 'marching'
            ELSE 'other'
        END) > 1
        """
    ).fetchall()
    if mixed_format_tracks:
        details = ", ".join(
            f"{row['canonical_ensemble_id']}:{row['track_id']}"
            for row in mixed_format_tracks
        )
        raise ValueError(f"Tracks cannot cross marching/Concert formats: {details}")


def _build_ensemble_track_season_flags(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO ensemble_track_season_flags
        WITH assigned AS (
            SELECT DISTINCT
                v.canonical_ensemble_id,
                v.canonical_ensemble_name,
                eta.track_id,
                v.season_year,
                v.performance_date,
                v.class_code,
                CASE v.class_code
                    WHEN 'pia' THEN 1 WHEN 'pio' THEN 2 WHEN 'piw' THEN 3
                    WHEN 'psa' THEN 1 WHEN 'pso' THEN 2 WHEN 'psw' THEN 3
                    WHEN 'psca' THEN 1 WHEN 'psco' THEN 2 WHEN 'pscw' THEN 3
                    ELSE 1
                END AS class_level
            FROM v_frontend_ensemble_performances v
            JOIN ensemble_track_assignments eta
              ON eta.canonical_ensemble_id = v.canonical_ensemble_id
             AND eta.class_code = v.class_code
             AND eta.season_year = v.season_year
        ),
        transitions AS (
            SELECT
                *,
                lag(class_level) OVER (
                    PARTITION BY canonical_ensemble_id, track_id, season_year
                    ORDER BY performance_date, class_code
                ) AS previous_level
            FROM assigned
        )
        SELECT
            canonical_ensemble_id,
            canonical_ensemble_name,
            track_id,
            season_year,
            group_concat(DISTINCT lower(class_code)) AS class_codes,
            count(DISTINCT class_code) AS class_count,
            'midseason_promotion' AS signal
        FROM transitions
        GROUP BY
            canonical_ensemble_id,
            canonical_ensemble_name,
            track_id,
            season_year
        HAVING count(DISTINCT class_code) > 1
           AND sum(CASE WHEN class_level > previous_level THEN 1 ELSE 0 END) > 0
           AND sum(CASE WHEN class_level < previous_level THEN 1 ELSE 0 END) = 0
        """
    )


def _create_frontend_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE v_frontend_season_leaderboard (
            season_year              INTEGER NOT NULL,
            class_code               TEXT NOT NULL,
            standing_order           INTEGER NOT NULL,
            canonical_ensemble_id    TEXT NOT NULL,
            canonical_ensemble_name  TEXT NOT NULL,
            performance_date         TEXT,
            event_stage              TEXT,
            round                    INTEGER,
            total_score              REAL,
            total_rank               INTEGER,
            placement                INTEGER,
            performance_key          TEXT
        );

        CREATE TABLE ensemble_class_season_flags (
            canonical_ensemble_id    TEXT NOT NULL,
            canonical_ensemble_name  TEXT NOT NULL,
            season_year              INTEGER NOT NULL,
            class_codes              TEXT NOT NULL,
            class_count              INTEGER NOT NULL,
            same_date_count          INTEGER NOT NULL,
            signal                   TEXT NOT NULL,
            PRIMARY KEY (canonical_ensemble_id, season_year)
        );

        CREATE TABLE ensemble_multi_group_seasons (
            canonical_ensemble_id    TEXT NOT NULL,
            season_year              INTEGER NOT NULL,
            class_codes              TEXT NOT NULL,
            PRIMARY KEY (canonical_ensemble_id, season_year)
        );

        CREATE TABLE ensemble_class_tracks (
            canonical_ensemble_id    TEXT NOT NULL,
            canonical_ensemble_name  TEXT NOT NULL,
            track_id                 TEXT NOT NULL,
            track_label              TEXT NOT NULL,
            class_codes              TEXT NOT NULL,
            season_years             TEXT NOT NULL,
            display_order            INTEGER NOT NULL,
            source                   TEXT NOT NULL,
            notes                    TEXT,
            PRIMARY KEY (canonical_ensemble_id, track_id)
        );

        CREATE TABLE ensemble_track_assignments (
            canonical_ensemble_id TEXT NOT NULL,
            track_id              TEXT NOT NULL,
            class_code           TEXT NOT NULL,
            season_year          INTEGER NOT NULL,
            PRIMARY KEY (canonical_ensemble_id, class_code, season_year),
            FOREIGN KEY (canonical_ensemble_id, track_id)
                REFERENCES ensemble_class_tracks(canonical_ensemble_id, track_id)
        );

        CREATE TABLE ensemble_track_season_flags (
            canonical_ensemble_id    TEXT NOT NULL,
            canonical_ensemble_name  TEXT NOT NULL,
            track_id                 TEXT NOT NULL,
            season_year              INTEGER NOT NULL,
            class_codes              TEXT NOT NULL,
            class_count              INTEGER NOT NULL,
            signal                   TEXT NOT NULL,
            PRIMARY KEY (canonical_ensemble_id, track_id, season_year),
            FOREIGN KEY (canonical_ensemble_id, track_id)
                REFERENCES ensemble_class_tracks(canonical_ensemble_id, track_id)
        );
        """
    )


def _build_frontend_season_leaderboard(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            season_year,
            class_code,
            canonical_ensemble_id,
            canonical_ensemble_name,
            performance_date,
            event_stage,
            round,
            total_score,
            total_rank,
            placement,
            performance_key
        FROM v_performances_canonical
        WHERE total_score IS NOT NULL
        ORDER BY season_year, class_code, canonical_ensemble_id, performance_date
        """
    ).fetchall()

    by_season_class: dict[tuple, dict[str, sqlite3.Row]] = defaultdict(dict)
    for row in rows:
        sc_key = (row["season_year"], row["class_code"])
        cid = row["canonical_ensemble_id"]
        existing = by_season_class[sc_key].get(cid)
        if existing is None:
            by_season_class[sc_key][cid] = row
        else:
            ep = _STAGE_PRIORITY.get(existing["event_stage"], 5)
            rp = _STAGE_PRIORITY.get(row["event_stage"], 5)
            if rp < ep:
                by_season_class[sc_key][cid] = row
            elif rp == ep:
                e_rank = existing["total_rank"] if existing["total_rank"] is not None else 9999
                r_rank = row["total_rank"] if row["total_rank"] is not None else 9999
                e_score = existing["total_score"] or 0
                r_score = row["total_score"] or 0
                if (r_rank, -r_score) < (e_rank, -e_score):
                    by_season_class[sc_key][cid] = row

    inserts = []
    for sc_key in sorted(by_season_class.keys()):
        season_year, class_code = sc_key
        ensemble_map = by_season_class[sc_key]

        by_stage: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in ensemble_map.values():
            stage_p = _STAGE_PRIORITY.get(row["event_stage"], 5)
            by_stage[stage_p].append(row)

        all_entries: list[sqlite3.Row] = []
        for stage_p in sorted(by_stage.keys()):
            if stage_p == 1:
                # championship_finals: use official rank order, then placement
                stage_entries = sorted(
                    by_stage[stage_p],
                    key=lambda r: (
                        r["total_rank"] if r["total_rank"] is not None else 9999,
                        r["placement"] if r["placement"] is not None else 9999,
                    ),
                )
            else:
                # non-finals stages: sort by score DESC (group is locked below finals)
                stage_entries = sorted(
                    by_stage[stage_p],
                    key=lambda r: -(r["total_score"] or 0),
                )
            all_entries.extend(stage_entries)

        for i, row in enumerate(all_entries, start=1):
            inserts.append(
                (
                    season_year,
                    class_code,
                    i,
                    row["canonical_ensemble_id"],
                    row["canonical_ensemble_name"],
                    row["performance_date"],
                    row["event_stage"],
                    row["round"],
                    row["total_score"],
                    row["total_rank"],
                    row["placement"],
                    row["performance_key"],
                )
            )

    conn.executemany(
        """
        INSERT INTO v_frontend_season_leaderboard
        (season_year, class_code, standing_order, canonical_ensemble_id,
         canonical_ensemble_name, performance_date, event_stage, round,
         total_score, total_rank, placement, performance_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )


def _create_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE VIEW v_performances_canonical AS
        SELECT
            p.*,
            ea.canonical_ensemble_id,
            ce.display_name AS canonical_ensemble_name,
            e.event_id,
            e.season_year,
            e.weekend_start,
            e.event_stage,
            e.is_championship,
            e.is_finals,
            sw.season_week_calendar,
            sw.season_week_index
        FROM performances p
        JOIN ensemble_aliases ea ON ea.alias_ensemble_slug = p.ensemble_slug
            AND ea.alias_name = p.ensemble_name
        JOIN canonical_ensembles ce ON ce.canonical_ensemble_id = ea.canonical_ensemble_id
        JOIN events e ON e.performance_date = p.performance_date
            AND e.competition_slug = p.competition_slug
        JOIN season_weekends sw ON sw.season_year = e.season_year
            AND sw.weekend_start = e.weekend_start;

        CREATE VIEW v_score_blocks AS
        SELECT * FROM score_blocks;

        CREATE VIEW v_judge_block_stats AS
        SELECT
            jbs.*,
            jl.judge_full_name,
            jl.judge_display_name,
            vpc.performance_date,
            vpc.competition_name,
            vpc.class_code,
            vpc.round,
            vpc.ensemble_name,
            vpc.canonical_ensemble_name,
            vpc.season_year,
            vpc.season_week_calendar,
            vpc.season_week_index,
            vpc.event_stage
        FROM judge_block_stats jbs
        LEFT JOIN judge_lookup jl
            ON jl.judge_abbrev = jbs.judge
        JOIN v_performances_canonical vpc
            ON vpc.performance_key = jbs.performance_key;

        CREATE VIEW v_frontend_show_performances AS
        SELECT
            p.performance_key,
            e.event_id,
            e.season_year,
            p.performance_date,
            p.competition_name,
            p.competition_slug,
            sw.season_week_calendar,
            sw.season_week_index,
            p.class_code,
            p.round,
            e.event_stage,
            CASE
                WHEN e.event_stage = 'mixed_championship'
                    AND lower(p.competition_name) LIKE '%psj%final%'
                    AND p.class_code = 'psj'
                    THEN 'championship_finals'
                WHEN e.event_stage = 'mixed_championship'
                    AND p.class_code IN ('psa', 'psca')
                    THEN 'championship_semifinals'
                WHEN e.event_stage = 'mixed_championship'
                    THEN 'championship_prelims'
                ELSE e.event_stage
            END AS display_stage,
            ea.canonical_ensemble_id,
            ce.display_name AS canonical_ensemble_name,
            p.ensemble_name,
            p.subtotal_score,
            p.penalty_score,
            p.total_score,
            p.total_rank,
            p.placement
        FROM performances p
        JOIN ensemble_aliases ea
            ON ea.alias_ensemble_slug = p.ensemble_slug
            AND ea.alias_name = p.ensemble_name
        JOIN canonical_ensembles ce
            ON ce.canonical_ensemble_id = ea.canonical_ensemble_id
        JOIN events e
            ON e.performance_date = p.performance_date
            AND e.competition_slug = p.competition_slug
        JOIN season_weekends sw
            ON sw.season_year = e.season_year
            AND sw.weekend_start = e.weekend_start;

        CREATE VIEW v_frontend_show_scores AS
        SELECT
            vfsp.performance_key,
            vfsp.event_id,
            vfsp.season_year,
            vfsp.performance_date,
            vfsp.competition_name,
            vfsp.competition_slug,
            vfsp.season_week_calendar,
            vfsp.season_week_index,
            vfsp.class_code,
            vfsp.round,
            vfsp.event_stage,
            vfsp.display_stage,
            vfsp.canonical_ensemble_id,
            vfsp.canonical_ensemble_name,
            vfsp.ensemble_name,
            vfsp.subtotal_score,
            vfsp.penalty_score,
            vfsp.total_score,
            vfsp.total_rank,
            vfsp.placement,
            s.caption,
            s.subcaption,
            s.role,
            s.score,
            s.rank,
            s.judge,
            jl.judge_full_name,
            jl.judge_display_name,
            s.judge_slot
        FROM v_frontend_show_performances vfsp
        JOIN scores s ON s.performance_key = vfsp.performance_key
        LEFT JOIN judge_lookup jl
            ON jl.judge_abbrev = s.judge;

        CREATE VIEW v_frontend_ensemble_performances AS
        SELECT
            ea.canonical_ensemble_id,
            ce.display_name AS canonical_ensemble_name,
            p.class_code,
            e.season_year,
            p.performance_date,
            p.competition_name,
            e.event_stage,
            CASE
                WHEN e.event_stage = 'mixed_championship'
                    AND lower(p.competition_name) LIKE '%psj%final%'
                    AND p.class_code = 'psj'
                    THEN 'championship_finals'
                WHEN e.event_stage = 'mixed_championship'
                    AND p.class_code IN ('psa', 'psca')
                    THEN 'championship_semifinals'
                WHEN e.event_stage = 'mixed_championship'
                    THEN 'championship_prelims'
                ELSE e.event_stage
            END AS display_stage,
            p.round,
            sw.season_week_calendar,
            sw.season_week_index,
            CASE WHEN sw.season_week_calendar = max_sw.max_cal THEN 1 ELSE 0 END
                AS season_week_final,
            sw.season_week_calendar - max_sw.max_cal AS week_from_final,
            p.total_score,
            p.total_rank,
            p.placement,
            p.performance_key
        FROM performances p
        JOIN ensemble_aliases ea
            ON ea.alias_ensemble_slug = p.ensemble_slug
            AND ea.alias_name = p.ensemble_name
        JOIN canonical_ensembles ce
            ON ce.canonical_ensemble_id = ea.canonical_ensemble_id
        JOIN events e
            ON e.performance_date = p.performance_date
            AND e.competition_slug = p.competition_slug
        JOIN season_weekends sw
            ON sw.season_year = e.season_year
            AND sw.weekend_start = e.weekend_start
        JOIN (
            SELECT season_year, max(season_week_calendar) AS max_cal
            FROM season_weekends
            GROUP BY season_year
        ) max_sw ON max_sw.season_year = e.season_year;
        """
    )


def rebuild(db_path: Path, aliases_path: Path, tracks_path: Path, judges_path: Path) -> None:
    alias_rules = _load_alias_rules(aliases_path)
    track_rules = _load_track_rules(tracks_path)
    judge_rules = _load_judge_rules(judges_path)
    with _connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _reset_derived_objects(conn)
        _create_tables(conn)
        _build_analysis_exclusions(conn)
        _build_ensembles(conn, alias_rules)
        _build_events(conn)
        _build_season_weekends(conn)
        _build_score_blocks(conn)
        _build_judge_lookup(conn, judge_rules)
        _build_judge_block_stats(conn)
        _build_duplicate_candidates(conn)
        _create_views(conn)
        _create_frontend_tables(conn)
        _build_ensemble_class_season_flags(conn)
        _build_ensemble_class_tracks(conn, track_rules)
        _build_ensemble_track_season_flags(conn)
        _build_frontend_season_leaderboard(conn)

    print(f"rebuilt derived tables in {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild canonical lookup tables and analysis views."
    )
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    parser.add_argument(
        "--aliases",
        default=str(ALIASES_PATH),
        help="CSV file with manual ensemble alias rules",
    )
    parser.add_argument(
        "--tracks",
        default=str(TRACKS_PATH),
        help="CSV file with manual ensemble class-track rules",
    )
    parser.add_argument(
        "--judges",
        default=str(JUDGES_PATH),
        help="CSV file with manual judge display-name rules",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop and recreate derived tables/views",
    )
    args = parser.parse_args()

    if not args.rebuild:
        parser.error("Only --rebuild is currently supported")

    rebuild(Path(args.db), Path(args.aliases), Path(args.tracks), Path(args.judges))


if __name__ == "__main__":
    main()
