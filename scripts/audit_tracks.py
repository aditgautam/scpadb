#!/usr/bin/env python3
"""Generate a Markdown audit of ambiguous ensemble class tracks."""

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

MARCHING_LADDERS = {
    "independent": {"pia": 1, "pio": 2, "piw": 3},
    "scholastic": {"psa": 1, "pso": 2, "psw": 3},
}
CONCERT_LADDER = {"psca": 1, "psco": 2, "pscw": 3}
CLASS_ORDER = {
    code: (format_name, level)
    for format_name, ladder in (
        *MARCHING_LADDERS.items(),
        ("concert", CONCERT_LADDER),
    )
    for code, level in ladder.items()
}
CONFIRMED_MANUAL_PROGRAMS = {
    "arcadia_hs",
    "etiwanda_hs",
    "rancho_cucamonga_hs",
    "vista_murrieta_hs",
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="scores.db")
    parser.add_argument("--out", default="docs/TRACK_AUDIT.md")
    return parser.parse_args()


def load_records(conn):
    return conn.execute(
        """
        SELECT
            v.canonical_ensemble_id,
            v.canonical_ensemble_name,
            v.performance_key,
            v.season_year,
            v.performance_date,
            p.competition_name,
            v.display_stage,
            v.class_code,
            v.round,
            p.subtotal_score,
            ect.track_id,
            ect.source AS track_source
        FROM v_frontend_ensemble_performances v
        JOIN performances p USING (performance_key)
        LEFT JOIN ensemble_track_assignments eta
          ON eta.canonical_ensemble_id = v.canonical_ensemble_id
         AND eta.class_code = v.class_code
         AND eta.season_year = v.season_year
        LEFT JOIN ensemble_class_tracks ect
          ON ect.canonical_ensemble_id = eta.canonical_ensemble_id
         AND ect.track_id = eta.track_id
        ORDER BY
            v.canonical_ensemble_name,
            v.season_year,
            v.performance_date,
            v.class_code,
            COALESCE(v.round, 0),
            v.performance_key
        """
    ).fetchall()


def classify_season(rows):
    reasons = []
    statuses = set()
    classes = {row["class_code"] for row in rows}
    formats = {CLASS_ORDER.get(code, ("other", 0))[0] for code in classes}

    if len(formats) > 1:
        statuses.add("separate_ensembles")
        reasons.append("marching/Concert or incompatible division classes coexist")

    by_date = defaultdict(set)
    prelim_classes = set()
    for row in rows:
        by_date[row["performance_date"]].add(row["class_code"])
        if row["display_stage"] == "championship_prelims":
            prelim_classes.add(row["class_code"])

    same_date = {
        date: sorted(codes)
        for date, codes in by_date.items()
        if len(codes) > 1
    }
    if same_date:
        statuses.add("separate_ensembles")
        details = "; ".join(f"{date}: {','.join(codes).upper()}" for date, codes in same_date.items())
        reasons.append(f"same-date multi-class records ({details})")

    prelim_by_format = defaultdict(set)
    for code in prelim_classes:
        prelim_by_format[CLASS_ORDER.get(code, ("other", 0))[0]].add(code)
    multi_prelims = {
        format_name: codes
        for format_name, codes in prelim_by_format.items()
        if len(codes) > 1
    }
    if multi_prelims:
        statuses.add("separate_ensembles")
        details = "; ".join(
            f"{format_name}: {','.join(sorted(codes)).upper()}"
            for format_name, codes in multi_prelims.items()
        )
        reasons.append(f"multiple prelims classes provide separate-line evidence ({details})")

    for format_name, ladder in (*MARCHING_LADDERS.items(), ("concert", CONCERT_LADDER)):
        format_rows = [row for row in rows if row["class_code"] in ladder]
        if len({row["class_code"] for row in format_rows}) < 2:
            continue
        levels = [ladder[row["class_code"]] for row in format_rows]
        has_decrease = any(current < previous for previous, current in zip(levels, levels[1:]))
        has_increase = any(current > previous for previous, current in zip(levels, levels[1:]))
        if has_decrease:
            if "separate_ensembles" not in statuses:
                statuses.add("midseason_reclassification")
                statuses.add("needs_review")
            reasons.append(
                f"{format_name} class sequence decreases; review whether this is "
                "a downward reclassification or evidence of separate ensembles"
            )
        elif has_increase and "separate_ensembles" not in statuses:
            statuses.add("midseason_promotion")
            statuses.add("needs_review")
            reasons.append(f"monotonic in-season {format_name} promotion")

    missing_prelims = sorted(classes - prelim_classes)
    if rows[0]["season_year"] != 2020 and missing_prelims:
        statuses.add("prelims_exception")
        reasons.append(
            "no prelims record for " + ",".join(code.upper() for code in missing_prelims)
        )

    ambiguous_mapping = any(row["track_id"] is None for row in rows)
    duplicate_mapping = len(rows) != len({row["performance_key"] for row in rows})
    if ambiguous_mapping:
        statuses.add("needs_review")
        reasons.append("one or more records do not map to a track")
    if duplicate_mapping:
        statuses.add("needs_review")
        reasons.append("one or more records map to multiple tracks")

    if not statuses:
        return None
    if statuses == {"prelims_exception"} and len(classes) == 1:
        return None
    if "needs_review" not in statuses:
        statuses.add("confirmed")
    return sorted(statuses), reasons


def find_cross_season_candidates(records):
    by_program_class = defaultdict(set)
    names = {}
    for row in records:
        code = row["class_code"]
        format_name, level = CLASS_ORDER.get(code, ("other", 0))
        if format_name not in MARCHING_LADDERS:
            continue
        key = (row["canonical_ensemble_id"], format_name, code, level)
        by_program_class[key].add(row["season_year"])
        names[row["canonical_ensemble_id"]] = row["canonical_ensemble_name"]

    by_program_format = defaultdict(list)
    for (canonical_id, format_name, code, level), years in by_program_class.items():
        by_program_format[(canonical_id, format_name)].append(
            (level, code, sorted(years))
        )

    candidates = []
    for (canonical_id, format_name), class_histories in by_program_format.items():
        if canonical_id in CONFIRMED_MANUAL_PROGRAMS:
            continue
        for lower_level, lower_code, lower_years in class_histories:
            for upper_level, upper_code, upper_years in class_histories:
                if upper_level <= lower_level:
                    continue
                if set(lower_years) & set(upper_years):
                    continue
                lower_last = max(lower_years)
                upper_first = min(upper_years)
                if 0 < upper_first - lower_last <= 4:
                    relevant_years = {lower_last, upper_first}
                    relevant_rows = [
                        row
                        for row in records
                        if row["canonical_ensemble_id"] == canonical_id
                        and row["season_year"] in relevant_years
                        and row["class_code"] in {lower_code, upper_code}
                    ]
                    candidates.append(
                        (
                            canonical_id,
                            names[canonical_id],
                            format_name,
                            lower_code,
                            upper_code,
                            lower_last,
                            upper_first,
                            relevant_rows,
                            "up",
                        )
                    )
                upper_last = max(upper_years)
                lower_first = min(lower_years)
                if 0 < lower_first - upper_last <= 4:
                    relevant_years = {upper_last, lower_first}
                    relevant_rows = [
                        row
                        for row in records
                        if row["canonical_ensemble_id"] == canonical_id
                        and row["season_year"] in relevant_years
                        and row["class_code"] in {lower_code, upper_code}
                    ]
                    candidates.append(
                        (
                            canonical_id,
                            names[canonical_id],
                            format_name,
                            upper_code,
                            lower_code,
                            upper_last,
                            lower_first,
                            relevant_rows,
                            "down",
                        )
                    )
    return candidates


def render_table(rows):
    lines = [
        "| Date | Competition | Stage | Class | Round | Subtotal | Current track | Source |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        score = "" if row["subtotal_score"] is None else f"{row['subtotal_score']:.3f}".rstrip("0").rstrip(".")
        values = dict(row)
        values.update(
            score=score,
            round="" if row["round"] is None else row["round"],
            track_id=row["track_id"] or "**UNMAPPED**",
            track_source=row["track_source"] or "",
        )
        lines.append(
            "| {performance_date} | {competition_name} | {display_stage} | "
            "{class_code} | {round} | {score} | {track_id} | {track_source} |".format(
                **values
            )
        )
    return lines


def main():
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    records = load_records(conn)
    conn.close()

    by_season = defaultdict(list)
    for row in records:
        by_season[
            (
                row["canonical_ensemble_id"],
                row["canonical_ensemble_name"],
                row["season_year"],
            )
        ].append(row)

    findings = []
    for key, rows in by_season.items():
        classification = classify_season(rows)
        if classification:
            statuses, reasons = classification
            if key[0] in CONFIRMED_MANUAL_PROGRAMS:
                statuses = [
                    status
                    for status in statuses
                    if status not in {"needs_review", "prelims_exception"}
                ]
                if "confirmed" not in statuses:
                    statuses.insert(0, "confirmed")
            findings.append((key, rows, statuses, reasons))
    cross_season_candidates = find_cross_season_candidates(records)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Ensemble Track Audit",
        "",
        "Generated by `uv run python scripts/audit_tracks.py`.",
        "",
        "## Rules",
        "",
        "- Marching and Concert ensembles never share a track.",
        "- Marching promotion ladders are PIA -> PIO -> PIW and PSA -> PSO -> PSW.",
        "- Cross-season upward or downward reclassification remains one track when "
        "there is no evidence of multiple ensembles.",
        "- Same-date multi-class records or multiple prelims classes indicate separate ensembles.",
        "- Without evidence of multiple ensembles in a format, class changes remain one continuing track.",
        "- Mid-season promotions remain one historical track but are excluded from primary modeling.",
        "- Missing prelims are flagged as exceptions, not treated as proof that an ensemble did not exist.",
        "",
        f"## Findings ({len(findings)} program-seasons)",
        "",
    ]
    for (_, name, year), rows, statuses, reasons in findings:
        owner_decision = (
            "confirmed by explicit manual mapping"
            if rows[0]["canonical_ensemble_id"] in CONFIRMED_MANUAL_PROGRAMS
            else ("review required" if "needs_review" in statuses else "confirmed by rules")
        )
        lines.extend(
            [
                f"### {name} - {year}",
                "",
                f"**Status:** {', '.join(f'`{status}`' for status in statuses)}",
                "",
                "**Why flagged:** " + "; ".join(reasons) + ".",
                "",
                *render_table(rows),
                "",
                f"**Owner decision:** {owner_decision}",
                "",
            ]
        )

    lines.extend(
        [
            f"## Auto-Connected Cross-Season Reclassifications ({len(cross_season_candidates)})",
            "",
            "These programs stop appearing in a lower marching class and begin appearing "
            "in a different marching class without evidence of multiple marching ensembles "
            "in the same season. They are connected automatically under the owner-approved "
            "continuity rule, including both upward and downward moves.",
            "",
        ]
    )
    for (
        _,
        name,
        _,
        from_code,
        to_code,
        from_year,
        to_year,
        rows,
        direction,
    ) in cross_season_candidates:
        lines.extend(
            [
                f"### {name}: {from_code.upper()} {from_year} -> {to_code.upper()} {to_year}",
                "",
                f"**Status:** `confirmed`, `cross_season_reclassification`, `{direction}`",
                "",
                *render_table(rows),
                "",
                "**Owner decision:** confirmed by continuity rule",
                "",
            ]
        )

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(findings)} findings to {out}")


if __name__ == "__main__":
    main()
