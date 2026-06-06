// ============================================================
// Formatting helpers
// ============================================================

const fmt = {
    score: v => (v == null ? '--' : formatScore(v)),
    int:   v => (v == null ? '--' : String(v)),
    str:   v => (v == null || v === '' ? '--' : String(v)),
    date:  (v, includeYear = false) => formatDate(v, includeYear),
    classCode: v => (v == null ? '--' : String(v).toUpperCase()),
};

function formatScore(value) {
    const n = Number(value);
    if (Number.isNaN(n)) return '--';
    return n.toFixed(3).replace(/\.?0+$/, '');
}

function formatDate(value, includeYear = false) {
    if (value == null || value === '') return '--';
    const [year, month, day] = String(value).split('-').map(Number);
    if (!year || !month || !day) return String(value);
    return includeYear
        ? `${month}/${day}/${String(year).slice(-2)}`
        : `${month}/${day}`;
}

// ============================================================
// Chart tooltip
// ============================================================

const _tooltip = {
    _pinned: false,
    _el: null,

    el() {
        return this._el || (this._el = document.getElementById('chart-tooltip'));
    },

    hover(clientX, clientY, html) {
        if (this._pinned) return;
        const el = this.el();
        el.innerHTML = html;
        el.style.left = `${clientX + 14}px`;
        el.style.top = `${clientY - 14}px`;
        el.classList.add('visible');
    },

    move(clientX, clientY) {
        if (this._pinned) return;
        const el = this.el();
        el.style.left = `${clientX + 14}px`;
        el.style.top = `${clientY - 14}px`;
    },

    hide() {
        if (this._pinned) return;
        this.el().classList.remove('visible');
    },

    pin(clientX, clientY, html) {
        const el = this.el();
        el.innerHTML = html;
        el.style.left = `${clientX + 14}px`;
        el.style.top = `${clientY - 14}px`;
        el.classList.add('visible', 'pinned');
        this._pinned = true;
        setTimeout(() => {
            const handler = (e) => {
                if (!el.contains(e.target)) {
                    this.dismiss();
                    document.removeEventListener('click', handler, { capture: true });
                }
            };
            document.addEventListener('click', handler, { capture: true });
        }, 0);
    },

    dismiss() {
        this._pinned = false;
        const el = this.el();
        el.classList.remove('visible', 'pinned');
    },

    isPinned() { return this._pinned; },
};

function buildTooltipHtml(r) {
    return `<div class="tt-date">${fmt.date(r.performance_date, true)}</div>` +
           `<div class="tt-show">${escapeHtml(r.competition_name)}</div>` +
           `<div class="tt-score">${fmt.score(r.total_score)}</div>` +
           `<div class="tt-meta">${fmt.classCode(r.class_code)} · ${fmtStage(r.display_stage || r.event_stage)}</div>`;
}

// ============================================================
// DB query helpers
// ============================================================

function toRows(result) {
    if (!result) return [];
    const { columns, values } = result;
    return values.map(row =>
        Object.fromEntries(columns.map((col, i) => [col, row[i]]))
    );
}

function query(db, sql, params = []) {
    return toRows(db.exec(sql, params)[0]);
}

// ============================================================
// Query functions
// ============================================================

function getSeasons(db) {
    return query(db, 'SELECT DISTINCT season_year FROM events ORDER BY season_year DESC')
        .map(r => r.season_year);
}

function getSeasonLeaderboard(db, season) {
    return query(db,
        `SELECT * FROM v_frontend_season_leaderboard
         WHERE season_year = ?
         ORDER BY class_code, standing_order`,
        [season]
    );
}

function getShowDays(db, season) {
    return query(db,
        `SELECT
            performance_date,
            CASE
                WHEN COUNT(DISTINCT competition_name) > 1
                     AND SUM(CASE WHEN competition_name LIKE '%Championship Finals%' THEN 1 ELSE 0 END) > 0
                    THEN 'Championship Finals'
                WHEN COUNT(DISTINCT competition_name) > 1
                    THEN GROUP_CONCAT(DISTINCT competition_name)
                ELSE MIN(competition_name)
            END AS competition_name
         FROM v_frontend_show_performances
         WHERE season_year = ?
         GROUP BY performance_date
         ORDER BY performance_date DESC`,
        [season]
    );
}

function getShowPerformances(db, season, date) {
    return query(db,
        `SELECT * FROM v_frontend_show_performances
         WHERE season_year = ? AND performance_date = ?
         ORDER BY class_code, round, total_rank, placement, total_score DESC`,
        [season, date]
    );
}

function getShowCaptionTotals(db, season, date) {
    // caption_total rows only exist for championship_finals. For all other stages
    // (prelims, semis, regular) the highest level summary is judge_total where
    // subcaption='total'. Use COALESCE so finals use their explicit caption_total
    // and non-finals derive the caption total by averaging per-judge totals.
    return query(db,
        `SELECT performance_key, caption,
            COALESCE(
                MAX(CASE WHEN role='caption_total' THEN score END),
                AVG(CASE WHEN role='judge_total' AND subcaption='total' THEN score END)
            ) AS score
         FROM v_frontend_show_scores
         WHERE season_year = ? AND performance_date = ?
           AND (role = 'caption_total' OR (role = 'judge_total' AND subcaption = 'total'))
         GROUP BY performance_key, caption
         ORDER BY performance_key, caption`,
        [season, date]
    );
}

function getShowJudgeTotals(db, season, date) {
    return query(db,
        `SELECT performance_key, caption, judge, judge_slot, score
         FROM v_frontend_show_scores
         WHERE season_year = ? AND performance_date = ? AND role = 'judge_total'
         ORDER BY performance_key, caption, judge_slot`,
        [season, date]
    );
}

function getShowRawScores(db, season, date) {
    return query(db,
        `SELECT *
         FROM v_frontend_show_scores
         WHERE season_year = ? AND performance_date = ?
         ORDER BY performance_key, caption, judge_slot, role, subcaption`,
        [season, date]
    );
}

function getCanonicalEnsembles(db, search) {
    const term = `%${search}%`;
    return query(db,
        `SELECT canonical_ensemble_id, display_name
         FROM canonical_ensembles
         WHERE LOWER(display_name) LIKE LOWER(?)
         ORDER BY display_name
         LIMIT 20`,
        [term]
    );
}

function getAllCanonicalEnsembles(db) {
    return query(db,
        `SELECT canonical_ensemble_id, display_name
         FROM canonical_ensembles
         ORDER BY display_name`
    );
}

function getEnsembleTracks(db, canonicalId) {
    return query(db,
        `SELECT
            t.*,
            GROUP_CONCAT(a.class_code || ':' || a.season_year) AS assignment_pairs
         FROM ensemble_class_tracks t
         JOIN ensemble_track_assignments a
           ON a.canonical_ensemble_id = t.canonical_ensemble_id
          AND a.track_id = t.track_id
         WHERE t.canonical_ensemble_id = ?
         GROUP BY t.canonical_ensemble_id, t.track_id
         ORDER BY t.display_order, t.track_label`,
        [canonicalId]
    ).map(trackFromRow);
}

function trackFromRow(row) {
    return {
        ...row,
        classCodes: splitCsv(row.class_codes),
        seasonYears: splitCsv(row.season_years).map(Number),
        assignments: splitCsv(row.assignment_pairs).map(pair => {
            const [classCode, seasonYear] = pair.split(':');
            return { classCode, seasonYear: Number(seasonYear) };
        }),
    };
}

function splitCsv(value) {
    return String(value || '')
        .split(',')
        .map(v => v.trim())
        .filter(Boolean);
}

function selectedTrack() {
    return _ensState.tracks.find(t => t.track_id === _ensState.trackId) || null;
}

function trackWhere(track, alias = '') {
    const prefix = alias ? `${alias}.` : '';
    const clauses = track.assignments.map(
        () => `(${prefix}class_code = ? AND ${prefix}season_year = ?)`
    );
    return {
        sql: ` AND (${clauses.join(' OR ')})`,
        params: track.assignments.flatMap(a => [a.classCode, a.seasonYear]),
    };
}

function getRecentScores(db, canonicalId, track) {
    const filter = trackWhere(track);
    return query(db,
        `SELECT *
         FROM v_frontend_ensemble_performances
         WHERE canonical_ensemble_id = ?
           ${filter.sql}
         ORDER BY performance_date DESC
         LIMIT 5`,
        [canonicalId, ...filter.params]
    );
}

function getEnsembleTrend(db, canonicalId, track, seasons) {
    if (!seasons.length) return [];
    const placeholders = seasons.map(() => '?').join(',');
    const filter = trackWhere(track);
    return query(db,
        `SELECT *
         FROM v_frontend_ensemble_performances
         WHERE canonical_ensemble_id = ?
           ${filter.sql}
           AND season_year IN (${placeholders})
         ORDER BY season_year, season_week_calendar, performance_date`,
        [canonicalId, ...filter.params, ...seasons]
    );
}

function getSeasonEnsemblePerformances(db, canonicalId, track, season) {
    const filter = trackWhere(track);
    return query(db,
        `SELECT *
         FROM v_frontend_show_performances
         WHERE canonical_ensemble_id = ?
           ${filter.sql}
           AND season_year = ?
         ORDER BY performance_date, class_code`,
        [canonicalId, ...filter.params, season]
    );
}

function getEnsembleClassSeasonFlags(db, canonicalId) {
    return query(db,
        `SELECT *
         FROM ensemble_class_season_flags
         WHERE canonical_ensemble_id = ?
         ORDER BY season_year DESC`,
        [canonicalId]
    );
}

function getLeaderboardPlacement(db, canonicalId, track, season) {
    const classCode = getTrackLastClassForSeason(db, canonicalId, track, season);
    if (!classCode) return null;
    const rows = query(db,
        `SELECT standing_order
         FROM v_frontend_season_leaderboard
         WHERE canonical_ensemble_id = ?
           AND class_code = ?
           AND season_year = ?
         LIMIT 1`,
        [canonicalId, classCode, season]
    );
    return rows.length ? rows[0].standing_order : null;
}

function getTrackLastClassForSeason(db, canonicalId, track, season) {
    const filter = trackWhere(track);
    const rows = query(db,
        `SELECT class_code
         FROM v_frontend_ensemble_performances
         WHERE canonical_ensemble_id = ?
           ${filter.sql}
           AND season_year = ?
         ORDER BY performance_date DESC, season_week_calendar DESC
         LIMIT 1`,
        [canonicalId, ...filter.params, season]
    );
    return rows.length ? rows[0].class_code : null;
}

function getPromotedSeasonRows(db) {
    return query(db,
        `SELECT
            canonical_ensemble_id,
            track_id,
            season_year,
            class_codes
         FROM ensemble_track_season_flags
         WHERE signal = 'midseason_promotion'`
    );
}

function getEnsembleStats(db, canonicalId, track) {
    const filter = trackWhere(track, 'p');
    const rows = query(db,
        `WITH selected AS (
            SELECT p.*
            FROM v_frontend_ensemble_performances p
            WHERE p.canonical_ensemble_id = ?
              ${filter.sql}
              AND p.total_score IS NOT NULL
         ),
         bounds AS (
            SELECT MIN(season_year) AS earliest_year FROM events
         ),
         finals AS (
            SELECT COUNT(DISTINCT season_year) AS finals_appearances
            FROM selected
            WHERE display_stage = 'championship_finals'
         ),
         high_score AS (
            SELECT total_score, competition_name, performance_date, class_code
            FROM selected
            ORDER BY total_score DESC, performance_date DESC
            LIMIT 1
         )
         SELECT
            bounds.earliest_year,
            finals.finals_appearances,
            high_score.total_score AS highest_score,
            high_score.competition_name AS highest_score_show,
            high_score.performance_date AS highest_score_date,
            high_score.class_code AS highest_score_class
         FROM bounds
         CROSS JOIN finals
         LEFT JOIN high_score ON 1 = 1`,
        [canonicalId, ...filter.params]
    );
    return rows[0] || null;
}

function getEnsembleSeasonStats(db, canonicalId, track) {
    const filter = trackWhere(track, 'p');
    return query(db,
        `WITH selected AS (
            SELECT p.*
            FROM v_frontend_ensemble_performances p
            WHERE p.canonical_ensemble_id = ?
              ${filter.sql}
              AND p.total_score IS NOT NULL
         ),
         first_rows AS (
            SELECT *
            FROM (
                SELECT selected.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY season_year
                        ORDER BY performance_date, season_week_calendar, performance_key
                    ) AS rn
                FROM selected
            )
            WHERE rn = 1
         ),
         last_rows AS (
            SELECT *
            FROM (
                SELECT selected.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY season_year
                        ORDER BY performance_date DESC, season_week_calendar DESC, performance_key DESC
                    ) AS rn
                FROM selected
            )
            WHERE rn = 1
         )
         SELECT
            f.season_year,
            f.total_score AS first_score,
            f.season_week_calendar AS first_week,
            f.performance_date AS first_date,
            l.total_score AS last_score,
            l.season_week_calendar AS last_week,
            l.performance_date AS last_date,
            l.total_score - f.total_score AS score_differential,
            CASE
                WHEN l.season_week_calendar = f.season_week_calendar THEN NULL
                ELSE (l.total_score - f.total_score) * 1.0 /
                     (l.season_week_calendar - f.season_week_calendar)
            END AS mean_weekly_improvement
         FROM first_rows f
         JOIN last_rows l ON l.season_year = f.season_year
         ORDER BY f.season_year DESC`,
        [canonicalId, ...filter.params]
    );
}

function getJudgeDirectory(db) {
    return query(db,
        `SELECT
            jl.judge_abbrev,
            jl.judge_full_name,
            jl.judge_display_name,
            CASE WHEN jl.judge_full_name IS NULL OR trim(jl.judge_full_name) = ''
                THEN 'needs full name'
                ELSE 'mapped'
            END AS mapping_status,
            COUNT(s.id) AS score_rows,
            COUNT(DISTINCT s.performance_key) AS performance_count
         FROM judge_lookup jl
         LEFT JOIN scores s ON s.judge = jl.judge_abbrev
         GROUP BY jl.judge_abbrev, jl.judge_full_name, jl.judge_display_name
         ORDER BY jl.judge_abbrev`
    );
}

function getSchemaObjects(db) {
    return query(db,
        `SELECT type, name
         FROM sqlite_master
         WHERE type IN ('table', 'view')
           AND name NOT LIKE 'sqlite_%'
         ORDER BY type, name`
    );
}

function runReadOnlySql(db, sql, limit = 500) {
    const text = sql.trim();
    if (!/^(select|with)\b/i.test(text)) {
        throw new Error('Only read-only SELECT or WITH queries are allowed.');
    }
    if (/\b(insert|update|delete|drop|alter|create|replace|pragma|attach|detach|vacuum|reindex)\b/i.test(text)) {
        throw new Error('Mutation and database-control statements are not allowed.');
    }
    const result = db.exec(text)[0];
    const rows = toRows(result);
    return {
        rows: rows.slice(0, limit),
        totalRows: rows.length,
        truncated: rows.length > limit,
    };
}

function getSeasonEnsembleRawScores(db, canonicalId, track, season) {
    const filter = trackWhere(track);
    return query(db,
        `SELECT *
         FROM v_frontend_show_scores
         WHERE canonical_ensemble_id = ?
           ${filter.sql}
           AND season_year = ?
         ORDER BY performance_key, caption, judge_slot, role, subcaption`,
        [canonicalId, ...filter.params, season]
    );
}

// ============================================================
// Table rendering utilities
// ============================================================

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

function makeTableWrap() {
    return el('div', 'table-wrap');
}

function buildTable(headers, rows) {
    const table = document.createElement('table');

    const thead = document.createElement('thead');
    const hObj = h => typeof h === 'object' ? h : { label: h };
    const hasJudgeGroups = headers.some(h => typeof h === 'object' && h.judgeGroup !== undefined);
    const hasCaptionGroups = headers.some(h => typeof h === 'object' && h.captionGroup != null);

    if (hasJudgeGroups) {
        const row1 = document.createElement('tr');
        const row2 = document.createElement('tr');
        const row3 = document.createElement('tr');
        table.classList.add('detail-table-3level');
        let i = 0;
        while (i < headers.length) {
            const h = hObj(headers[i]);
            if (!h.captionGroup) {
                const th = document.createElement('th');
                th.textContent = h.label;
                th.rowSpan = 3;
                if (h.num) th.className = 'num';
                row1.appendChild(th);
                i++;
                continue;
            }
            const cg = h.captionGroup;
            const cgStart = i;
            while (i < headers.length && hObj(headers[i]).captionGroup === cg) i++;
            const cgCols = headers.slice(cgStart, i).map(hObj);
            const cgTh = document.createElement('th');
            cgTh.textContent = fmtCaptionFull(cg);
            cgTh.colSpan = cgCols.length;
            cgTh.classList.add('header-caption-group');
            row1.appendChild(cgTh);
            let j = 0;
            while (j < cgCols.length) {
                const col = cgCols[j];
                if (col.judgeGroup === null) {
                    const th = document.createElement('th');
                    th.textContent = col.label;
                    th.rowSpan = 2;
                    th.classList.add('header-caption-total');
                    if (col.num) th.classList.add('num');
                    row2.appendChild(th);
                    j++;
                } else {
                    const jg = col.judgeGroup;
                    const jgStart = j;
                    while (j < cgCols.length && cgCols[j].judgeGroup === jg) j++;
                    const jgCols = cgCols.slice(jgStart, j);
                    const jTh = document.createElement('th');
                    jTh.textContent = jgCols[0]?.judgeLabel || `J${jg}`;
                    jTh.colSpan = jgCols.length;
                    jTh.classList.add('header-judge-group');
                    row2.appendChild(jTh);
                    jgCols.forEach(c => {
                        const th = document.createElement('th');
                        th.textContent = c.label;
                        if (c.num) th.className = 'num';
                        if (c.role === 'judge_total') th.classList.add('header-judge-total-col');
                        row3.appendChild(th);
                    });
                }
            }
        }
        thead.appendChild(row1);
        thead.appendChild(row2);
        thead.appendChild(row3);
    } else if (hasCaptionGroups) {
        const groupRow = document.createElement('tr');
        const subRow = document.createElement('tr');
        let i = 0;
        while (i < headers.length) {
            const h = hObj(headers[i]);
            if (!h.captionGroup) {
                const th = document.createElement('th');
                th.textContent = h.label;
                th.rowSpan = 2;
                if (h.num) th.className = 'num';
                groupRow.appendChild(th);
                i++;
            } else {
                const grp = h.captionGroup;
                const start = i;
                while (i < headers.length && hObj(headers[i]).captionGroup === grp) i++;
                const groupTh = document.createElement('th');
                groupTh.textContent = fmtCaptionFull(grp);
                groupTh.colSpan = i - start;
                groupTh.classList.add('caption-group-header');
                groupRow.appendChild(groupTh);
                for (let k = start; k < i; k++) {
                    const sh = hObj(headers[k]);
                    const th = document.createElement('th');
                    th.textContent = sh.label;
                    if (sh.num) th.className = 'num';
                    subRow.appendChild(th);
                }
            }
        }
        thead.appendChild(groupRow);
        thead.appendChild(subRow);
    } else {
        const hrow = document.createElement('tr');
        headers.forEach(h => {
            const ho = hObj(h);
            const th = document.createElement('th');
            th.textContent = ho.label;
            if (ho.num) th.className = 'num';
            hrow.appendChild(th);
        });
        thead.appendChild(hrow);
    }
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach(row => {
        const cells = Array.isArray(row) ? row : row.cells;
        const tr = document.createElement('tr');
        if (!Array.isArray(row) && row.className) tr.className = row.className;
        if (!Array.isArray(row) && row.rowId) tr.id = row.rowId;
        cells.forEach((cell, i) => {
            const td = document.createElement('td');
            const hdr = hObj(headers[i]);
            td.className = hdr.num ? 'num' : '';
            if (hdr.role === 'judge_total') td.classList.add('col-judge-total');
            else if (hdr.role === 'caption_total') td.classList.add('col-caption-total');
            if (cell && typeof cell === 'object' && 'html' in cell) {
                td.innerHTML = cell.html;
            } else {
                td.textContent = cell ?? '--';
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
}

function applyTableZoom(wrap) {
    let scale = 1;
    let lastDist = null;
    let lastTap = 0;

    wrap.addEventListener('touchstart', e => {
        if (e.touches.length === 2) {
            lastDist = Math.hypot(
                e.touches[0].clientX - e.touches[1].clientX,
                e.touches[0].clientY - e.touches[1].clientY
            );
        } else if (e.touches.length === 1) {
            const now = Date.now();
            if (now - lastTap < 300) {
                scale = 1;
                wrap.style.transform = '';
                wrap.classList.remove('table-zoomed');
                lastTap = 0;
            } else {
                lastTap = now;
            }
        }
    }, { passive: true });

    wrap.addEventListener('touchmove', e => {
        if (e.touches.length !== 2 || lastDist === null) return;
        const newDist = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY
        );
        scale = Math.min(3, Math.max(1, scale * (newDist / lastDist)));
        lastDist = newDist;
        wrap.style.transform = scale > 1 ? `scale(${scale.toFixed(3)})` : '';
        wrap.classList.toggle('table-zoomed', scale > 1);
        e.preventDefault();
    }, { passive: false });

    wrap.addEventListener('touchend', () => {
        lastDist = null;
    }, { passive: true });
}

function wrapTable(table) {
    const w = makeTableWrap();
    w.appendChild(table);
    applyTableZoom(w);
    return w;
}

const _showSortState = {};

function buildSortableTable(headers, rows, tableKey) {
    const table = document.createElement('table');
    table.classList.add('show-table');
    if (headers.length > 8) table.classList.add('compact-score-table');
    const sort = _showSortState[tableKey] || { key: null, direction: null };
    let renderedRows = rows.slice();

    if (sort.key && sort.direction) {
        renderedRows.sort((a, b) => {
            const av = a.sortValues[sort.key];
            const bv = b.sortValues[sort.key];
            const an = av == null || Number.isNaN(Number(av));
            const bn = bv == null || Number.isNaN(Number(bv));
            if (an && bn) return a.defaultOrder - b.defaultOrder;
            if (an) return 1;
            if (bn) return -1;
            const delta = Number(av) - Number(bv);
            return sort.direction === 'asc' ? delta : -delta;
        });
    }

    const makeSortTh = (h) => {
        const th = document.createElement('th');
        th.textContent = h.label;
        if (h.num) th.className = 'num';
        if (h.sortable) {
            th.classList.add('sortable');
            if (sort.key === h.key && sort.direction) {
                th.textContent = `${h.label} ${sort.direction === 'asc' ? '▲' : '▼'}`;
            }
            th.addEventListener('click', () => {
                const current = _showSortState[tableKey] || { key: null, direction: null };
                let next = { key: h.key, direction: 'desc' };
                if (current.key === h.key && current.direction === 'desc') {
                    next = { key: h.key, direction: 'asc' };
                } else if (current.key === h.key && current.direction === 'asc') {
                    next = { key: null, direction: null };
                }
                _showSortState[tableKey] = next;
                renderShowRecords(_db);
            });
        }
        return th;
    };

    const thead = document.createElement('thead');
    const hasJudgeGroups = headers.some(h => h.judgeGroup !== undefined);
    const hasCaptionGroups = headers.some(h => h.captionGroup != null);

    if (hasJudgeGroups) {
        // 3-level header: caption group → judge group → score type
        const row1 = document.createElement('tr');
        const row2 = document.createElement('tr');
        const row3 = document.createElement('tr');
        table.classList.add('detail-table-3level');

        let i = 0;
        while (i < headers.length) {
            const h = headers[i];
            if (!h.captionGroup) {
                const th = makeSortTh(h);
                th.rowSpan = 3;
                row1.appendChild(th);
                i++;
                continue;
            }
            // Collect this caption group's columns
            const cg = h.captionGroup;
            const cgStart = i;
            while (i < headers.length && headers[i].captionGroup === cg) i++;
            const cgCols = headers.slice(cgStart, i);

            const cgTh = document.createElement('th');
            cgTh.textContent = fmtCaptionFull(cg);
            cgTh.colSpan = cgCols.length;
            cgTh.classList.add('header-caption-group');
            row1.appendChild(cgTh);

            let j = 0;
            while (j < cgCols.length) {
                const col = cgCols[j];
                if (col.judgeGroup === null) {
                    // Caption total: rowspan=2, placed in row2
                    const th = makeSortTh(col);
                    th.rowSpan = 2;
                    th.classList.add('header-caption-total');
                    row2.appendChild(th);
                    j++;
                } else {
                    const jg = col.judgeGroup;
                    const jgStart = j;
                    while (j < cgCols.length && cgCols[j].judgeGroup === jg) j++;
                    const jgCols = cgCols.slice(jgStart, j);
                    const jTh = document.createElement('th');
                    jTh.textContent = jgCols[0]?.judgeLabel || `J${jg}`;
                    jTh.colSpan = jgCols.length;
                    jTh.classList.add('header-judge-group');
                    row2.appendChild(jTh);
                    jgCols.forEach(c => {
                        const th = makeSortTh(c);
                        if (c.role === 'judge_total') th.classList.add('header-judge-total-col');
                        row3.appendChild(th);
                    });
                }
            }
        }
        thead.appendChild(row1);
        thead.appendChild(row2);
        thead.appendChild(row3);

    } else if (hasCaptionGroups) {
        const captionHeaders = headers.filter(h => h.captionGroup);
        const hasJudgeNames = captionHeaders.some(h => h.judgeLabel != null);

        if (hasJudgeNames) {
            // 3-level: caption group → judge name → score type
            const groupRow = document.createElement('tr');
            const judgeRow = document.createElement('tr');
            const subRow = document.createElement('tr');
            table.classList.add('detail-table-3level');
            let i = 0;
            while (i < headers.length) {
                const h = headers[i];
                if (!h.captionGroup) {
                    const th = makeSortTh(h);
                    th.rowSpan = 3;
                    groupRow.appendChild(th);
                    i++;
                } else {
                    const grp = h.captionGroup;
                    const start = i;
                    while (i < headers.length && headers[i].captionGroup === grp) i++;
                    const cols = headers.slice(start, i);

                    const groupTh = document.createElement('th');
                    groupTh.textContent = fmtCaptionFull(grp);
                    groupTh.colSpan = cols.length;
                    groupTh.classList.add('header-caption-group');
                    groupRow.appendChild(groupTh);

                    const judgeTh = document.createElement('th');
                    judgeTh.colSpan = cols.length;
                    judgeTh.classList.add('header-judge-group');
                    if (grp !== 'timing_penalties') {
                        judgeTh.textContent = cols.find(c => c.judgeLabel)?.judgeLabel || '';
                    }
                    judgeRow.appendChild(judgeTh);

                    cols.forEach(c => subRow.appendChild(makeSortTh(c)));
                }
            }
            thead.appendChild(groupRow);
            thead.appendChild(judgeRow);
            thead.appendChild(subRow);
        } else {
            // 2-level: caption group → score type
            const groupRow = document.createElement('tr');
            const subRow = document.createElement('tr');
            let i = 0;
            while (i < headers.length) {
                const h = headers[i];
                if (!h.captionGroup) {
                    const th = makeSortTh(h);
                    th.rowSpan = 2;
                    groupRow.appendChild(th);
                    i++;
                } else {
                    const grp = h.captionGroup;
                    const start = i;
                    while (i < headers.length && headers[i].captionGroup === grp) i++;
                    const groupTh = document.createElement('th');
                    groupTh.textContent = fmtCaptionFull(grp);
                    groupTh.colSpan = i - start;
                    groupTh.classList.add('caption-group-header');
                    groupRow.appendChild(groupTh);
                    for (let k = start; k < i; k++) {
                        subRow.appendChild(makeSortTh(headers[k]));
                    }
                }
            }
            thead.appendChild(groupRow);
            thead.appendChild(subRow);
        }
    } else {
        const hrow = document.createElement('tr');
        headers.forEach(h => hrow.appendChild(makeSortTh(h)));
        thead.appendChild(hrow);
    }
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    renderedRows.forEach(row => {
        const tr = document.createElement('tr');
        if (row.className) tr.className = row.className;
        if (row.rowId) tr.id = row.rowId;
        row.cells.forEach((cell, i) => {
            const td = document.createElement('td');
            const hdr = headers[i];
            td.className = hdr.num ? 'num' : '';
            if (hdr.role === 'judge_total') td.classList.add('col-judge-total');
            else if (hdr.role === 'caption_total') td.classList.add('col-caption-total');
            if (cell && typeof cell === 'object' && 'html' in cell) {
                td.innerHTML = cell.html;
            } else {
                td.textContent = cell ?? '--';
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return wrapTable(table);
}

// ============================================================
// Tab routing
// ============================================================

let _db = null;
let _activeTab = 'leaderboard';
let _pendingHighlight = null;
let _leaderboardSeason = null;
let _showRecordsSeason = null;

function switchTab(tabId) {
    _activeTab = tabId;
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.hidden = panel.id !== `tab-${tabId}`;
    });
}

function highlightElement(target) {
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.remove('target-highlight');
    void target.offsetWidth;
    target.classList.add('target-highlight');
    window.setTimeout(() => target.classList.remove('target-highlight'), 1800);
}

function highlightBySelector(selector) {
    window.setTimeout(() => highlightElement(document.querySelector(selector)), 80);
}

function setSelectValue(selectId, value) {
    const el = document.getElementById(selectId);
    if (!el) return;
    el.value = String(value);
}

function routeToLeaderboard(season, classCode = null) {
    switchTab('leaderboard');
    _leaderboardSeason = Number(season);
    renderLeaderboard(_db);
    if (classCode) highlightBySelector(`#leaderboard-${classCode}`);
}

function routeToShowRecords(season, date, performanceKey = null) {
    switchTab('show-records');
    _showRecordsSeason = Number(season);
    populateShowDates(_db);
    setSelectValue('sr-date', date);
    document.getElementById('sr-detail').checked = Boolean(performanceKey);
    _pendingHighlight = performanceKey ? { type: 'performance', key: performanceKey } : null;
    renderShowRecords(_db);
    if (performanceKey) highlightBySelector(`#performance-${cssSafe(performanceKey)}`);
}

function routeToEnsemble(canonicalId, displayName, season = null, classCode = null) {
    switchTab('ensemble');
    selectEnsemble(_db, canonicalId, displayName, { season, classCode });
    if (season) {
        _ensState.selectedSeasons = new Set([Number(season)]);
        renderEnsembleView(_db);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function bindGlobalRoutes() {
    document.addEventListener('click', event => {
        const jump = event.target.closest('[data-jump-target]');
        if (jump) {
            event.preventDefault();
            const jumpEl = document.querySelector(jump.dataset.jumpTarget);
            if (jumpEl) {
                if (jump.dataset.jumpScroll === 'start') {
                    jumpEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
                } else {
                    highlightElement(jumpEl);
                }
            }
            return;
        }

        const target = event.target.closest('[data-route]');
        if (!target) return;
        event.preventDefault();
        const route = target.dataset.route;
        if (route === 'ensemble') {
            routeToEnsemble(
                target.dataset.canonicalId,
                target.dataset.ensembleName,
                target.dataset.season ? Number(target.dataset.season) : null,
                target.dataset.classCode || null
            );
        } else if (route === 'show') {
            routeToShowRecords(
                Number(target.dataset.season),
                target.dataset.date,
                target.dataset.performanceKey || null
            );
        } else if (route === 'leaderboard') {
            routeToLeaderboard(Number(target.dataset.season), target.dataset.classCode || null);
        }
    });
}

// ============================================================
// Season Leaderboard
// ============================================================

const CLASS_ORDER = ['piw', 'psw', 'pio', 'pso', 'pia', 'psa', 'pscw', 'psco', 'psca'];

function orderedClassCodes(classCodes) {
    return classCodes.slice().sort((a, b) => {
        const ai = CLASS_ORDER.indexOf(a);
        const bi = CLASS_ORDER.indexOf(b);
        if (ai !== -1 || bi !== -1) {
            if (ai === -1) return 1;
            if (bi === -1) return -1;
            return ai - bi;
        }
        return a.localeCompare(b);
    });
}

function initLeaderboard(db) {
    const buttons = document.getElementById('lb-season-buttons');
    const seasons = getSeasons(db);
    buttons.innerHTML = '';
    _leaderboardSeason = seasons[0] ?? null;
    seasons.forEach(y => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'season-button';
        btn.dataset.season = y;
        btn.textContent = y;
        btn.addEventListener('click', () => {
            _leaderboardSeason = Number(y);
            renderLeaderboard(db);
        });
        buttons.appendChild(btn);
    });
    renderLeaderboard(db);
}

function renderLeaderboard(db) {
    const season = Number(_leaderboardSeason);
    const rows = getSeasonLeaderboard(db, season);
    const container = document.getElementById('lb-content');
    container.innerHTML = '';
    document.querySelectorAll('#lb-season-buttons .season-button').forEach(btn => {
        btn.classList.toggle('active', Number(btn.dataset.season) === season);
    });

    if (!rows.length) {
        container.appendChild(el('p', 'empty-msg', 'No data for selected season.'));
        return;
    }

    const byClass = {};
    rows.forEach(r => {
        if (!byClass[r.class_code]) byClass[r.class_code] = [];
        byClass[r.class_code].push(r);
    });

    const promotedSeasons = getPromotedSeasonRows(db);
    const promotionLookup = buildPromotionLookup(promotedSeasons);
    container.appendChild(buildLeaderboardLegend());

    const classCodes = orderedClassCodes(Object.keys(byClass));
    const jumps = el('nav', 'leaderboard-jumps');
    classCodes.forEach(cls => {
        const link = document.createElement('a');
        link.href = `#leaderboard-${cls}`;
        link.dataset.jumpTarget = `#leaderboard-${cls}`;
        link.textContent = fmt.classCode(cls);
        jumps.appendChild(link);
    });
    container.appendChild(jumps);

    const grid = el('div', 'leaderboard-grid');
    classCodes.forEach(cls => {
        const entries = byClass[cls];
        const section = el('div', 'class-section');
        section.id = `leaderboard-${cls}`;
        section.appendChild(el('div', 'class-heading', fmt.classCode(cls)));

        const table = buildTable(
            [
                '#',
                'Ensemble',
                { label: 'Total Score', num: true },
            ],
            leaderboardRows(entries, season, promotionLookup)
        );
        table.classList.add('leaderboard-table');
        section.appendChild(wrapTable(table));
        grid.appendChild(section);
    });
    container.appendChild(grid);
}

function buildLeaderboardLegend() {
    const legend = el('div', 'leaderboard-legend');
    legend.innerHTML = `
        <span><span class="regular-dot"></span>No prelims appearance</span>
        <span><span class="promotion-marker">↑</span>Promoted/reclassified group</span>
        <span><span class="legend-line solid"></span>Finals cutoff</span>
        <span><span class="legend-line dashed"></span>Prelims cutoff</span>
    `;
    return legend;
}

function buildPromotionLookup(rows) {
    const lookup = new Set();
    rows.forEach(row => {
        splitCsv(row.class_codes).forEach(cls => {
            lookup.add(`${row.canonical_ensemble_id}|${row.season_year}|${cls.toLowerCase()}`);
        });
    });
    return lookup;
}

function isPromotedRow(row, season, lookup) {
    return lookup.has(`${row.canonical_ensemble_id}|${season}|${row.class_code}`);
}

function sourcePerformanceTitle(row) {
    return `Score pulled from ${fmt.date(row.performance_date)} ${row.canonical_ensemble_name} ${fmt.classCode(row.class_code)} ${fmtStage(row.event_stage)}`;
}

function leaderboardRows(entries, season, promotionLookup) {
    const lastFinal = lastIndexWhere(entries, e => e.event_stage === 'championship_finals');
    const lastSemis = lastIndexWhere(entries, e =>
        e.event_stage === 'championship_semifinals' || e.event_stage === 'mixed_championship'
    );

    return entries.map((e, i) => {
        let className = '';
        if (i === lastFinal) className = 'stage-cutoff-final';
        if (i === lastSemis) className = 'stage-cutoff-semis';
        const promoted = isPromotedRow(e, season, promotionLookup);
        const sourceTitle = sourcePerformanceTitle(e);
        return {
            className,
            cells: [
                e.standing_order,
                {
                    html: routeButtonHtml('ensemble', escapeHtml(e.canonical_ensemble_name), {
                        canonicalId: e.canonical_ensemble_id,
                        ensembleName: e.canonical_ensemble_name,
                        season,
                        classCode: e.class_code,
                    })
                        + (promoted ? ` <span class="promotion-marker" title="Promoted or reclassified group">↑</span>` : '')
                        + (e.event_stage === 'regular' ? ` <span class="regular-dot" title="${escapeHtml(sourceTitle)}"></span>` : ''),
                },
                {
                    html: routeButtonHtml('show', fmt.score(e.total_score), {
                        season,
                        date: e.performance_date,
                        performanceKey: e.performance_key || '',
                    }),
                },
            ],
        };
    });
}

function routeButtonHtml(route, label, data) {
    const attrs = Object.entries(data)
        .filter(([, value]) => value != null && value !== '')
        .map(([key, value]) => ` data-${toKebab(key)}="${escapeHtml(value)}"`)
        .join('');
    return `<button type="button" class="link-button" data-route="${route}"${attrs}>${label}</button>`;
}

function toKebab(value) {
    return value.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`);
}

function lastIndexWhere(rows, predicate) {
    for (let i = rows.length - 1; i >= 0; i--) {
        if (predicate(rows[i])) return i;
    }
    return -1;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function cssSafe(value) {
    return String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

// ============================================================
// Show Records
// ============================================================

function initShowRecords(db) {
    const dateSel = document.getElementById('sr-date');
    const combineChk = document.getElementById('sr-combine');
    const detailChk = document.getElementById('sr-detail');
    const buttons = document.getElementById('sr-season-buttons');

    const seasons = getSeasons(db);
    buttons.innerHTML = '';
    _showRecordsSeason = seasons[0] ?? null;
    seasons.forEach(y => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'season-button';
        btn.dataset.season = y;
        btn.textContent = y;
        btn.addEventListener('click', () => {
            _showRecordsSeason = Number(y);
            populateShowDates(db);
        });
        buttons.appendChild(btn);
    });

    dateSel.addEventListener('change', () => renderShowRecords(db));
    combineChk.addEventListener('change', () => renderShowRecords(db));
    detailChk.addEventListener('change', () => renderShowRecords(db));
    populateShowDates(db);
}

function populateShowDates(db) {
    const dateSel = document.getElementById('sr-date');
    const season = Number(_showRecordsSeason);
    const selected = dateSel.value;
    const days = getShowDays(db, season);
    document.querySelectorAll('#sr-season-buttons .season-button').forEach(btn => {
        btn.classList.toggle('active', Number(btn.dataset.season) === season);
    });
    dateSel.innerHTML = '';
    if (!days.length) {
        dateSel.innerHTML = '<option value="">No shows found</option>';
        return;
    }
    days.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.performance_date;
        opt.textContent = `${fmt.date(d.performance_date)} - ${d.competition_name}`;
        dateSel.appendChild(opt);
    });
    if ([...dateSel.options].some(opt => opt.value === selected)) {
        dateSel.value = selected;
    }
    renderShowRecords(db);
}

function renderShowRecords(db) {
    const season = Number(_showRecordsSeason);
    const date = document.getElementById('sr-date').value;
    const combine = document.getElementById('sr-combine').checked;
    const detailed = document.getElementById('sr-detail').checked;
    const container = document.getElementById('sr-content');
    container.innerHTML = '';

    if (!date) return;

    const performances = getShowPerformances(db, season, date);
    if (!performances.length) {
        container.appendChild(el('p', 'empty-msg', 'No performances found.'));
        return;
    }

    const captionRows = getShowCaptionTotals(db, season, date);
    const rawRows = detailed ? getShowRawScores(db, season, date) : [];
    const captionMap = {};
    captionRows.forEach(r => {
        if (!captionMap[r.performance_key]) captionMap[r.performance_key] = {};
        captionMap[r.performance_key][r.caption] = r.score;
    });

    const scoreModel = detailed
        ? buildDetailedScoreModel(rawRows, captionMap, combine)
        : buildCaptionScoreModel(captionRows, captionMap);

    const byClass = {};
    performances.forEach(p => {
        if (!byClass[p.class_code]) byClass[p.class_code] = {};
        const round = p.round ?? '__none__';
        if (!byClass[p.class_code][round]) byClass[p.class_code][round] = [];
        byClass[p.class_code][round].push(p);
    });

    Object.entries(byClass).forEach(([cls, byRound]) => {
        const section = el('div', 'class-section');
        const heading = el('div', 'class-heading');
        heading.innerHTML = routeButtonHtml('leaderboard', fmt.classCode(cls), {
            season,
            classCode: cls,
        });
        section.appendChild(heading);

        const rounds = Object.keys(byRound).sort((a, b) => {
            if (a === '__none__') return -1;
            if (b === '__none__') return 1;
            return Number(a) - Number(b);
        });

        const hasMultipleRounds = rounds.length > 1;

        if (combine && hasMultipleRounds) {
            const allPerfs = rounds.flatMap(r => byRound[r]);
            appendShowTables(
                section,
                allPerfs,
                scoreModel,
                detailed,
                false,
                `${season}:${date}:${cls}:combined`,
                true
            );
        } else {
            rounds.forEach(round => {
                if (hasMultipleRounds) {
                    const label = round === '__none__' ? 'Block' : `Block ${round}`;
                    section.appendChild(el('div', 'block-heading', label));
                }
                appendShowTables(section, byRound[round], scoreModel, detailed, true, `${season}:${date}:${cls}:${round}`);
            });
        }

        container.appendChild(section);
    });
}

function appendShowTables(
    section,
    perfs,
    scoreModel,
    detailed,
    showSubtotals,
    tableKey,
    combinedRanking = false
) {
    const groups = detailed
        ? groupPerfsByPanelStructure(perfs, scoreModel)
        : [{ label: '', perfs }];
    const combinedRanks = combinedRanking ? buildCombinedRanks(perfs) : null;
    groups.forEach((group, index) => {
        if (groups.length > 1) {
            section.appendChild(el('div', 'block-heading', group.label || `Panel ${index + 1}`));
        }
        const columns = getColumnsForPerfs(group.perfs, scoreModel);
        const wrapped = buildShowTable(
            group.perfs,
            scoreModel,
            columns,
            showSubtotals,
            `${tableKey}:${index}`,
            combinedRanks
        );
        section.appendChild(wrapped);
        const tbl = wrapped.querySelector('table');
        if (tbl) applyStickyColumns(tbl, 2);
    });
}

function groupPerfsByPanelStructure(perfs, scoreModel) {
    const groups = new Map();
    perfs.forEach(perf => {
        const keys = Object.keys(scoreModel.scores[perf.performance_key] || {})
            .filter(key => !key.startsWith('cap:'))
            .sort();
        const signature = `${perf.display_stage || perf.event_stage || 'stage'}|${keys.join('|') || 'caption-only'}`;
        if (!groups.has(signature)) {
            const panelCount = Math.max(1, ...keys.map(key => {
                const parts = key.split(':');
                return Number(parts[3]) || 1;
            }));
            const stage = fmtStage(perf.display_stage || perf.event_stage);
            groups.set(signature, {
                label: `${stage} ${panelCount > 1 ? 'double panel' : 'single panel'}`,
                perfs: [],
            });
        }
        groups.get(signature).perfs.push(perf);
    });
    return [...groups.values()];
}

function buildCaptionScoreModel(captionRows, captionMap) {
    const columns = [...new Set(captionRows.map(r => r.caption))]
        .filter(c => c !== 'total')
        .sort()
        .map(caption => ({
            key: `cap:${caption}`,
            label: fmtCaption(caption),
        }));
    const scores = {};
    Object.entries(captionMap).forEach(([performanceKey, captions]) => {
        scores[performanceKey] = {};
        Object.entries(captions).forEach(([caption, score]) => {
            scores[performanceKey][`cap:${caption}`] = score;
        });
    });
    return { columns, scores };
}

function buildDetailedScoreModel(scoreRows, captionMap, hideJudgeSlots) {
    const columnMap = new Map();
    const scores = {};

    scoreRows.forEach(row => {
        if (!scores[row.performance_key]) scores[row.performance_key] = {};
        let key = null;
        let label = null;
        if (row.role === 'raw_score') {
            key = `raw:${row.caption}:${row.subcaption}:${row.judge_slot ?? ''}`;
            label = fmtCaption(row.subcaption);
        } else if (row.role === 'judge_total' && row.subcaption === 'total') {
            key = `judge:${row.caption}:${row.judge_slot ?? ''}`;
            label = 'Tot';
        } else if (row.role === 'caption_total') {
            key = `cap:${row.caption}`;
            label = 'Tot';
        }
        if (!key) return;
        scores[row.performance_key][key] = row.score;
        if (!columnMap.has(key)) {
            columnMap.set(key, {
                key,
                label,
                caption: row.caption,
                role: row.role,
                judgeSlot: row.judge_slot ?? 99,
                judgeLabel: hideJudgeSlots
                    ? null
                    : (row.judge_display_name || row.judge || null),
                subcaption: row.subcaption,
            });
        }
    });

    Object.entries(captionMap).forEach(([performanceKey, captions]) => {
        if (!scores[performanceKey]) scores[performanceKey] = {};
        Object.entries(captions).forEach(([caption, score]) => {
            const key = `cap:${caption}`;
            scores[performanceKey][key] = score;
            if (!columnMap.has(key)) {
                // Suppress caption_total column when exactly one judge covers this caption
                // (single-judge: caption_total === judge_total, redundant display)
                const judgeTotalsForCap = [...columnMap.values()].filter(
                    c => c.caption === caption && c.role === 'judge_total'
                ).length;
                if (judgeTotalsForCap !== 1) {
                    columnMap.set(key, {
                        key,
                        label: fmtCaption(caption),
                        caption,
                        role: 'caption_total',
                        judgeSlot: 100,
                        subcaption: 'total',
                    });
                }
            }
        });
    });

    const roleOrder = { raw_score: 1, judge_total: 2, caption_total: 3 };
    const columns = [...columnMap.values()].sort((a, b) => {
        if (a.caption !== b.caption) return a.caption.localeCompare(b.caption);
        if (a.judgeSlot !== b.judgeSlot) return a.judgeSlot - b.judgeSlot;
        const ar = roleOrder[a.role] || 9;
        const br = roleOrder[b.role] || 9;
        if (ar !== br) return ar - br;
        return a.subcaption.localeCompare(b.subcaption);
    });
    return { columns, scores, hideJudgeSlots };
}

function getColumnsForPerfs(perfs, scoreModel) {
    const keys = new Set();
    perfs.forEach(p => {
        const scores = scoreModel.scores[p.performance_key] || {};
        Object.keys(scores).forEach(key => keys.add(key));
    });
    return scoreModel.columns.filter(col => keys.has(col.key));
}

function colJudgeGroup(col) {
    if (col.role === 'caption_total') return null;
    if (col.judgeSlot == null || col.judgeSlot >= 50) return null;
    return col.judgeSlot;
}

function compareCombinedScores(a, b) {
    const as = a.total_score == null ? Number.NEGATIVE_INFINITY : Number(a.total_score);
    const bs = b.total_score == null ? Number.NEGATIVE_INFINITY : Number(b.total_score);
    if (as !== bs) return bs - as;

    const ar = a.total_rank ?? a.placement ?? 9999;
    const br = b.total_rank ?? b.placement ?? 9999;
    if (ar !== br) return ar - br;
    return String(a.canonical_ensemble_name).localeCompare(String(b.canonical_ensemble_name));
}

function buildCombinedRanks(perfs) {
    return new Map(
        [...perfs]
            .sort(compareCombinedScores)
            .map((perf, index) => [perf.performance_key, index + 1])
    );
}

function buildShowTable(
    perfs,
    scoreModel,
    scoreColumns,
    showSubtotals,
    tableKey,
    combinedRanks = null
) {
    const useGroups = scoreColumns.length > 0 && scoreColumns[0].caption != null;
    const useJudgeGroups = useGroups
        && !scoreModel.hideJudgeSlots
        && scoreColumns.some(c => (colJudgeGroup(c) ?? 0) > 1);
    const headers = [
        { label: '#', key: 'rank' },
        { label: 'Ensemble', key: 'ensemble' },
        ...scoreColumns.map(c => ({
            label: c.label, key: c.key, num: true, sortable: true,
            captionGroup: useGroups ? c.caption : null,
            judgeGroup: useJudgeGroups ? colJudgeGroup(c) : undefined,
            judgeLabel: useGroups && !scoreModel.hideJudgeSlots ? (c.judgeLabel || null) : null,
            role: useGroups ? c.role : null,
        })),
    ];
    if (showSubtotals) {
        headers.push({ label: 'Subtotal', key: 'subtotal', num: true, sortable: true });
        headers.push({ label: 'Penalty', key: 'penalty', num: true, sortable: true });
    }
    headers.push({ label: 'Total', key: 'total', num: true, sortable: true });

    const sorted = [...perfs].sort(combinedRanks
        ? compareCombinedScores
        : (a, b) => {
            const ra = a.total_rank ?? 9999;
            const rb = b.total_rank ?? 9999;
            if (ra !== rb) return ra - rb;
            const pa = a.placement ?? 9999;
            const pb = b.placement ?? 9999;
            if (pa !== pb) return pa - pb;
            return (b.total_score ?? 0) - (a.total_score ?? 0);
        });

    const rows = sorted.map((p, defaultOrder) => {
        const scores = scoreModel.scores[p.performance_key] || {};
        const sortValues = {
            subtotal: p.subtotal_score,
            penalty: p.penalty_score,
            total: p.total_score,
        };
        scoreColumns.forEach(c => { sortValues[c.key] = scores[c.key]; });
        const cells = [
            combinedRanks?.get(p.performance_key) ?? p.placement ?? p.total_rank ?? '--',
            {
                html: routeButtonHtml('ensemble', escapeHtml(p.canonical_ensemble_name), {
                    canonicalId: p.canonical_ensemble_id,
                    ensembleName: p.canonical_ensemble_name,
                    season: p.season_year,
                    classCode: p.class_code,
                }),
            },
            ...scoreColumns.map(c => fmt.score(scores[c.key])),
        ];
        if (showSubtotals) {
            cells.push(fmt.score(p.subtotal_score));
            const penVal = p.penalty_score;
            cells.push((penVal != null && penVal !== 0)
                ? { html: `<span class="penalty-nonzero">${escapeHtml(fmt.score(penVal))}</span>` }
                : fmt.score(penVal));
        }
        cells.push(fmt.score(p.total_score));
        return {
            cells,
            sortValues,
            defaultOrder,
            className: _pendingHighlight?.type === 'performance' && _pendingHighlight.key === p.performance_key
                ? 'target-highlight'
                : '',
            rowId: `performance-${cssSafe(p.performance_key)}`,
        };
    });

    return buildSortableTable(headers, rows, tableKey);
}

function fmtCaption(raw) {
    const labels = {
        effect_music: 'Eff Mus',
        effect_visual: 'Eff Vis',
        music: 'Mus',
        visual: 'Vis',
        effect: 'Eff',
        artistry: 'Art',
        musicianship: 'Mus',
        composition: 'Comp',
        performance: 'Perf',
        overall: 'Ovr',
        progression: 'Prog',
        fulfillment: 'Ful',
        total: 'Tot',
    };
    return labels[raw] || String(raw)
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

function fmtCaptionFull(raw) {
    const labels = {
        effect_music: 'Effect Music',
        effect_visual: 'Effect Visual',
        music: 'Music',
        visual: 'Visual',
        effect: 'Effect',
        artistry: 'Artistry',
        musicianship: 'Musicianship',
        composition: 'Composition',
        performance: 'Performance',
        overall: 'Overall',
        progression: 'Progression',
        fulfillment: 'Fulfillment',
    };
    return labels[raw] || String(raw)
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

function applyStickyColumns(table, n) {
    requestAnimationFrame(() => {
        const firstRowCells = Array.from(table.querySelector('tbody tr')?.children || []);
        if (!firstRowCells.length) return;

        const stickyCount = Math.min(n, firstRowCells.length);
        const widths = firstRowCells.slice(0, stickyCount).map(cell => cell.getBoundingClientRect().width);
        const offsets = widths.map((_, index) =>
            widths.slice(0, index).reduce((sum, width) => sum + width, 0)
        );

        getHeaderLogicalCells(table).forEach(({ th, col }) => {
            if (col >= stickyCount) return;
            applyStickyCell(th, offsets[col], col === stickyCount - 1);
        });

        for (let col = 0; col < stickyCount; col++) {
            table.querySelectorAll(`tbody tr td:nth-child(${col + 1})`).forEach(td => {
                applyStickyCell(td, offsets[col], col === stickyCount - 1);
            });
        }
    });
}

function applyStickyCell(cell, left, isLast) {
    cell.classList.add('sticky-col');
    cell.classList.toggle('sticky-col-last', isLast);
    cell.style.left = `${left}px`;
}

function getHeaderLogicalCells(table) {
    const rows = Array.from(table.querySelectorAll('thead tr'));
    const occupied = [];
    const cells = [];

    rows.forEach((row, rowIndex) => {
        if (!occupied[rowIndex]) occupied[rowIndex] = [];
        let col = 0;
        Array.from(row.children).forEach(th => {
            while (occupied[rowIndex][col]) col++;
            const colSpan = th.colSpan || 1;
            const rowSpan = th.rowSpan || 1;
            cells.push({ th, col, colSpan, rowSpan });
            for (let r = rowIndex; r < rowIndex + rowSpan; r++) {
                if (!occupied[r]) occupied[r] = [];
                for (let c = col; c < col + colSpan; c++) {
                    occupied[r][c] = true;
                }
            }
            col += colSpan;
        });
    });

    return cells;
}

// ============================================================
// Ensemble View
// ============================================================

const _ensState = {
    canonicalId: null,
    canonicalName: null,
    trackId: null,
    tracks: [],
    classFlags: [],
    selectedSeasons: new Set(),
    detailSeasons: [],
    seasonSortDir: 'desc',
};

const TREND_COLORS = [
    '#1a1a1a', '#6b6b6b', '#4a90a4', '#c0392b', '#27ae60',
    '#8e44ad', '#d35400', '#2980b9', '#16a085', '#c0392b',
];

function initEnsembleView(db) {
    const searchEl = document.getElementById('ens-search');
    const dropdown = document.getElementById('ens-dropdown');
    const classEl = document.getElementById('ens-class');
    const noteEl = document.getElementById('ens-class-note');
    const detailChk = document.getElementById('ens-detail');

    let debounceTimer;
    searchEl.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            const term = searchEl.value.trim();
            if (term.length < 2) {
                dropdown.hidden = true;
                return;
            }
            const results = getCanonicalEnsembles(db, term);
            dropdown.innerHTML = '';
            if (!results.length) {
                dropdown.hidden = true;
                return;
            }
            results.forEach(r => {
                const li = document.createElement('li');
                li.textContent = r.display_name;
                li.addEventListener('mousedown', e => {
                    e.preventDefault();
                    selectEnsemble(db, r.canonical_ensemble_id, r.display_name);
                });
                dropdown.appendChild(li);
            });
            dropdown.hidden = false;
        }, 180);
    });

    searchEl.addEventListener('blur', () => {
        setTimeout(() => { dropdown.hidden = true; }, 200);
    });

    classEl.addEventListener('change', () => {
        _ensState.trackId = classEl.value || null;
        _ensState.selectedSeasons.clear();
        if (_ensState.trackId) {
            document.getElementById('ens-class-group').hidden = true;
            noteEl.hidden = true;
            populateEnsembleSeasons(db);
            renderEnsembleView(db);
        } else {
            document.getElementById('ens-content').hidden = true;
        }
    });

    detailChk.addEventListener('change', () => renderEnsembleView(db));

    ['ens-sort-desc', 'ens-sort-asc'].forEach(id => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.addEventListener('click', () => {
            _ensState.seasonSortDir = btn.id === 'ens-sort-desc' ? 'desc' : 'asc';
            document.getElementById('ens-sort-desc').classList.toggle('active', _ensState.seasonSortDir === 'desc');
            document.getElementById('ens-sort-asc').classList.toggle('active', _ensState.seasonSortDir === 'asc');
            renderEnsembleView(db);
        });
    });

    const backBtn = document.getElementById('ens-back-btn');
    if (backBtn) backBtn.addEventListener('click', showEnsembleIndex);

    renderEnsembleIndex(db);
}

function renderEnsembleIndex(db) {
    const container = document.getElementById('ens-index');
    if (!container) return;
    container.hidden = false;
    const rows = getAllCanonicalEnsembles(db);
    const byLetter = {};
    rows.forEach(row => {
        const letter = (row.display_name || '#').trim().charAt(0).toUpperCase();
        const key = /^[A-Z]$/.test(letter) ? letter : '#';
        if (!byLetter[key]) byLetter[key] = [];
        byLetter[key].push(row);
    });
    container.innerHTML = '';
    container.appendChild(el('h3', 'index-title', 'Ensemble Index'));
    const grid = el('div', 'ensemble-index');
    Object.keys(byLetter).sort().forEach(letter => {
        const section = el('section', 'index-letter');
        section.appendChild(el('h4', null, letter));
        const list = el('div', 'index-list');
        byLetter[letter].forEach(row => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'link-button index-link';
            btn.textContent = row.display_name;
            btn.addEventListener('click', () => selectEnsemble(db, row.canonical_ensemble_id, row.display_name));
            list.appendChild(btn);
        });
        section.appendChild(list);
        grid.appendChild(section);
    });
    container.appendChild(grid);
}

function showEnsembleIndex() {
    document.getElementById('ens-content').hidden = true;
    document.getElementById('ens-index').hidden = false;
    document.getElementById('ens-class-group').hidden = true;
    document.getElementById('ens-index-btn-group').hidden = true;
    document.getElementById('ens-search').value = '';
    _ensState.canonicalId = null;
    _ensState.canonicalName = null;
    _ensState.trackId = null;
    _ensState.tracks = [];
    _ensState.classFlags = [];
    _ensState.selectedSeasons.clear();
    _ensState.detailSeasons = [];
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function selectEnsemble(db, canonicalId, displayName, options = {}) {
    document.getElementById('ens-content').hidden = true;
    document.getElementById('ens-index').hidden = true;
    document.getElementById('ens-index-btn-group').hidden = false;

    _ensState.canonicalId = canonicalId;
    _ensState.canonicalName = displayName;
    _ensState.trackId = null;
    _ensState.tracks = getEnsembleTracks(db, canonicalId);
    _ensState.classFlags = getEnsembleClassSeasonFlags(db, canonicalId);
    _ensState.selectedSeasons.clear();
    _ensState.detailSeasons = [];

    const searchEl = document.getElementById('ens-search');
    const dropdown = document.getElementById('ens-dropdown');
    const classEl = document.getElementById('ens-class');
    const classGroup = document.getElementById('ens-class-group');
    const noteEl = document.getElementById('ens-class-note');

    searchEl.value = displayName;
    dropdown.hidden = true;
    noteEl.hidden = true;
    noteEl.textContent = '';

    const tracks = _ensState.tracks;
    const contextualTrack = chooseTrackForContext(tracks, options.season, options.classCode);
    const needsChoice = tracks.length > 1 && !contextualTrack;
    classGroup.hidden = !needsChoice;
    classEl.innerHTML = '';
    classEl.disabled = false;

    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = needsChoice ? '-- select group --' : '';
    classEl.appendChild(blank);

    tracks.forEach(track => {
        const opt = document.createElement('option');
        opt.value = track.track_id;
        opt.textContent = track.track_label;
        classEl.appendChild(opt);
    });

    if (tracks.length === 1 || contextualTrack) {
        const track = contextualTrack || tracks[0];
        classEl.value = track.track_id;
        _ensState.trackId = track.track_id;
        classEl.disabled = tracks.length === 1 && track.source === 'auto_class_change';
        populateEnsembleSeasons(db);
        if (options.season) {
            _ensState.selectedSeasons = new Set([Number(options.season)]);
        }
        renderEnsembleView(db);
    } else {
        noteEl.textContent = 'This program has multiple tracked groups. Select a group to view that line.';
        noteEl.hidden = false;
    }
}

function chooseTrackForContext(tracks, season, classCode) {
    if (!tracks.length || (!season && !classCode)) return null;
    const year = season == null ? null : Number(season);
    const cls = classCode == null ? null : String(classCode).toLowerCase();
    return tracks.find(track =>
        (year == null || track.seasonYears.includes(year))
        && (cls == null || track.classCodes.includes(cls))
    ) || null;
}

function populateEnsembleSeasons(db) {
    const track = selectedTrack();
    const seasons = track ? track.seasonYears.slice().sort((a, b) => b - a) : [];

    if (!seasons.length) {
        return;
    }

    _ensState.selectedSeasons = new Set(seasons);
    _ensState.detailSeasons = seasons.slice();
}

function renderEnsembleView(db) {
    const { canonicalId, selectedSeasons, detailSeasons } = _ensState;
    const track = selectedTrack();
    if (!canonicalId || !track) return;

    const content = document.getElementById('ens-content');
    content.hidden = false;

    renderEnsembleJumps();
    renderEnsembleHeaderAndStats(db, canonicalId, track);
    renderTrendChart(db, canonicalId, track, [...selectedSeasons].sort());
    renderImprovementIndex(db, canonicalId, track);
    const sortedSeasonList = _ensState.seasonSortDir === 'asc'
        ? detailSeasons.slice().sort((a, b) => a - b)
        : detailSeasons.slice().sort((a, b) => b - a);
    renderSeasonDetails(db, canonicalId, track, sortedSeasonList);
}

function renderEnsembleJumps() {
    const nav = document.getElementById('ens-jumps');
    nav.innerHTML = '';
    [
        ['Stats', '#ens-stats-section'],
        ['Score Trend', '#ens-trend-section'],
        ['Improvement Index', '#ens-improvement-section'],
        ['Scores', '#ens-records-section'],
    ].forEach(([label, target]) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'jump-button';
        btn.dataset.jumpTarget = target;
        btn.dataset.jumpScroll = 'start';
        btn.textContent = label;
        nav.appendChild(btn);
    });
}

function renderEnsembleHeaderAndStats(db, canonicalId, track) {
    const title = document.getElementById('ens-title');
    const subtitle = document.getElementById('ens-subtitle');
    const error = document.getElementById('ens-error');
    title.textContent = _ensState.canonicalName || track.canonical_ensemble_name || '';
    error.hidden = true;
    error.textContent = '';

    const classification = resolveTrackClassification(db, canonicalId, track);
    if (classification) {
        subtitle.textContent = fmt.classCode(classification);
    } else {
        subtitle.textContent = '';
        error.textContent = 'Classification could not be resolved from available performance records.';
        error.hidden = false;
    }

    renderEnsembleStats(db, canonicalId, track);
}

function resolveTrackClassification(db, canonicalId, track) {
    if (track.classCodes.length === 1) return track.classCodes[0];
    const rows = getRecentScores(db, canonicalId, track);
    return rows.length ? rows[0].class_code : null;
}

function renderEnsembleStats(db, canonicalId, track) {
    const container = document.getElementById('ens-stats');
    container.innerHTML = '';
    const stats = getEnsembleStats(db, canonicalId, track);
    const seasonStats = getEnsembleSeasonStats(db, canonicalId, track);
    const validWeekly = seasonStats
        .map(r => r.mean_weekly_improvement)
        .filter(v => v != null && !Number.isNaN(Number(v)))
        .map(Number);
    const overallWeekly = validWeekly.length
        ? validWeekly.reduce((sum, v) => sum + v, 0) / validWeekly.length
        : null;

    const cards = el('div', 'stats-grid');
    cards.appendChild(statCard(
        `Finals Appearances`,
        fmt.int(stats?.finals_appearances),
        stats?.earliest_year ? `Since ${stats.earliest_year}` : ''
    ));
    cards.appendChild(statCard(
        `Highest Score`,
        fmt.score(stats?.highest_score),
        stats?.highest_score_show
            ? `${stats.highest_score_show} (${fmt.date(stats.highest_score_date, true)}, ${fmt.classCode(stats.highest_score_class)})`
            : ''
    ));
    cards.appendChild(statCard(
        `Mean Weekly Improvement`,
        fmtSignedScore(overallWeekly),
        `Average of valid seasons`
    ));
    container.appendChild(cards);
}

function renderImprovementIndex(db, canonicalId, track) {
    const container = document.getElementById('ens-improvement');
    container.innerHTML = '';
    const seasonStats = getEnsembleSeasonStats(db, canonicalId, track);
    if (seasonStats.length) {
        const table = buildTable(
            [
                'Season',
                { label: 'First', num: true },
                'First Week',
                { label: 'Final', num: true },
                'Final Week',
                { label: 'Diff', num: true },
                { label: 'Weekly Diff', num: true },
            ],
            seasonStats.map(r => [
                r.season_year,
                fmt.score(r.first_score),
                fmt.int(r.first_week),
                fmt.score(r.last_score),
                fmt.int(r.last_week),
                fmtSignedScore(r.score_differential),
                fmtSignedScore(r.mean_weekly_improvement),
            ])
        );
        table.classList.add('stats-table');
        container.appendChild(wrapTable(table));
    } else {
        container.appendChild(el('p', 'empty-msg', 'No improvement data.'));
    }
}

function statCard(label, value, detail) {
    const card = el('div', 'stat-card');
    card.appendChild(el('div', 'stat-label', label));
    card.appendChild(el('div', 'stat-value', value));
    if (detail) card.appendChild(el('div', 'stat-detail', detail));
    return card;
}

function fmtSignedScore(value) {
    if (value == null || Number.isNaN(Number(value))) return '--';
    const n = Number(value);
    const sign = n > 0 ? '+' : '';
    return `${sign}${formatScore(n)}`;
}

function fmtStage(stage) {
    const map = {
        championship_finals: 'Finals',
        championship_semifinals: 'Semis',
        championship_prelims: 'Prelims',
        mixed_championship: 'Championship',
        regular: 'Regular',
    };
    return map[stage] ?? fmt.str(stage);
}

function renderTrendChart(db, canonicalId, track, seasons) {
    const container = document.getElementById('ens-chart');
    container.innerHTML = '';
    _tooltip.dismiss();

    const shell = el('div', 'chart-shell');
    const plot = el('div', 'chart-plot');
    const menu = el('div', 'chart-season-menu');
    shell.appendChild(plot);
    shell.appendChild(menu);
    container.appendChild(shell);

    const allSeasons = _ensState.detailSeasons.slice().sort((a, b) => b - a);

    const allBtn = document.createElement('button');
    allBtn.type = 'button';
    allBtn.className = 'chart-season-button chart-season-all';
    allBtn.textContent = 'ALL';
    const allActive = allSeasons.every(s => _ensState.selectedSeasons.has(s));
    allBtn.classList.toggle('active', allActive);
    allBtn.addEventListener('click', () => {
        if (allSeasons.every(s => _ensState.selectedSeasons.has(s))) {
            _ensState.selectedSeasons.clear();
        } else {
            allSeasons.forEach(s => _ensState.selectedSeasons.add(s));
        }
        renderEnsembleView(db);
    });
    menu.appendChild(allBtn);

    allSeasons.forEach((season, index) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'chart-season-button';
        btn.classList.toggle('active', _ensState.selectedSeasons.has(season));
        btn.style.setProperty('--season-color', TREND_COLORS[index % TREND_COLORS.length]);
        btn.textContent = season;
        btn.addEventListener('click', () => {
            if (_ensState.selectedSeasons.has(season)) {
                _ensState.selectedSeasons.delete(season);
            } else {
                _ensState.selectedSeasons.add(season);
            }
            renderEnsembleView(db);
        });
        menu.appendChild(btn);
    });

    if (!seasons.length) {
        plot.appendChild(el('p', 'empty-msg', 'Select a season to show the graph.'));
        return;
    }

    const data = getEnsembleTrend(db, canonicalId, track, seasons);
    if (!data.length) {
        plot.appendChild(el('p', 'empty-msg', 'No graph data for selected seasons.'));
        return;
    }

    const bySeason = {};
    data.forEach(r => {
        if (!bySeason[r.season_year]) bySeason[r.season_year] = [];
        bySeason[r.season_year].push(r);
    });

    const sortedSeasons = seasons.slice().sort();
    const allSeasonColorScale = season => TREND_COLORS[allSeasons.indexOf(season) % TREND_COLORS.length];
    const colorScale = season => allSeasonColorScale(season);

    const margin = { top: 16, right: 32, bottom: 48, left: 54 };
    const width = Math.min(720, (plot.offsetWidth || container.parentElement?.offsetWidth || 720)) - margin.left - margin.right;
    const height = 240 - margin.top - margin.bottom;

    const allX = data.map(r => r.season_week_calendar);
    const allY = data.map(r => r.total_score).filter(v => v != null);

    const xMin = 1;
    const xMax = Math.max(...allX);
    const yMin = Math.max(0, Math.min(...allY) - 5);
    const yMax = Math.min(100, Math.max(...allY) + 2);

    const x = d3.scaleLinear().domain([xMin, xMax]).range([0, width]);
    const y = d3.scaleLinear().domain([yMin, yMax]).range([height, 0]).nice();

    const svg = d3.select(plot)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom);

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    g.append('g')
        .attr('class', 'grid')
        .call(d3.axisLeft(y).ticks(5).tickSize(-width).tickFormat(''))
        .select('.domain').remove();

    g.append('g')
        .attr('class', 'axis')
        .attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(x).ticks(xMax).tickFormat(v => Number.isInteger(v) ? `Wk ${v}` : ''));

    g.append('g')
        .attr('class', 'axis')
        .call(d3.axisLeft(y).ticks(5));

    const line = d3.line()
        .x(r => x(r.season_week_calendar))
        .y(r => y(r.total_score))
        .defined(r => r.total_score != null);

    let focusLocked = null;

    const focusSeason = (targetSeason) => {
        if (focusLocked !== null && focusLocked !== targetSeason) return;
        g.selectAll('.season-group').style('opacity', 0.18);
        g.select(`.sg-${targetSeason}`).raise().style('opacity', 1);
    };

    const blurSeason = () => {
        if (focusLocked !== null) return;
        g.selectAll('.season-group').style('opacity', 1);
    };

    const lockFocus = (targetSeason) => {
        focusLocked = targetSeason;
        g.selectAll('.season-group').style('opacity', 0.18);
        g.select(`.sg-${targetSeason}`).raise().style('opacity', 1);
    };

    const clearFocusLock = () => {
        focusLocked = null;
        g.selectAll('.season-group').style('opacity', 1);
    };

    g.insert('rect', ':first-child')
        .attr('width', width)
        .attr('height', height)
        .attr('fill', 'transparent')
        .on('click', () => {
            clearFocusLock();
            _tooltip.dismiss();
        });

    sortedSeasons.forEach(season => {
        const sData = bySeason[season];
        if (!sData) return;
        const color = colorScale(season);
        const filteredData = sData.filter(r => r.total_score != null);

        const group = g.append('g').attr('class', `season-group sg-${season}`);

        group.append('path')
            .datum(sData)
            .attr('class', `season-line sl-${season}`)
            .attr('fill', 'none')
            .attr('stroke', color)
            .attr('stroke-width', 2)
            .attr('d', line);

        group.append('path')
            .datum(sData)
            .attr('fill', 'none')
            .attr('stroke', 'transparent')
            .attr('stroke-width', 10)
            .attr('d', line)
            .style('cursor', 'pointer')
            .on('mouseover', () => focusSeason(season))
            .on('mouseout', () => blurSeason())
            .on('click', (event) => {
                event.stopPropagation();
                if (focusLocked === season) {
                    clearFocusLock();
                    _tooltip.dismiss();
                } else {
                    lockFocus(season);
                }
            });

        const visDots = group.selectAll(null)
            .data(filteredData)
            .enter()
            .append('circle')
            .attr('class', 'chart-dot')
            .attr('cx', r => x(r.season_week_calendar))
            .attr('cy', r => y(r.total_score))
            .attr('r', 5)
            .attr('fill', color)
            .attr('stroke', '#fff')
            .attr('stroke-width', 1.5);

        group.selectAll(null)
            .data(filteredData)
            .enter()
            .append('circle')
            .attr('cx', r => x(r.season_week_calendar))
            .attr('cy', r => y(r.total_score))
            .attr('r', 11)
            .attr('fill', 'transparent')
            .style('cursor', 'pointer')
            .on('mouseover', function(event, r) {
                focusSeason(season);
                visDots.filter(d => d === r)
                    .transition().duration(120)
                    .attr('r', 8).attr('stroke-width', 2);
                _tooltip.hover(event.clientX, event.clientY, buildTooltipHtml(r));
            })
            .on('mousemove', function(event) {
                _tooltip.move(event.clientX, event.clientY);
            })
            .on('mouseout', function(event, r) {
                blurSeason();
                visDots.transition().duration(150).attr('r', 5).attr('stroke-width', 1.5);
                _tooltip.hide();
            })
            .on('click', function(event, r) {
                event.stopPropagation();
                lockFocus(season);
                visDots.filter(d => d === r)
                    .transition().duration(120)
                    .attr('r', 8).attr('stroke-width', 2);
                _tooltip.pin(event.clientX, event.clientY, buildTooltipHtml(r));
            });
    });

    menu.querySelectorAll('.chart-season-button').forEach(btn => {
        const season = Number(btn.textContent);
        if (!isNaN(season)) btn.style.setProperty('--season-color', allSeasonColorScale(season));
    });
}

function buildCaptionMapFromRows(captionRows) {
    const map = {};
    captionRows.forEach(r => {
        if (!map[r.performance_key]) map[r.performance_key] = {};
        map[r.performance_key][r.caption] = r.score;
    });
    return map;
}

function renderSeasonDetails(db, canonicalId, track, seasons) {
    const container = document.getElementById('ens-season-details');
    container.innerHTML = '';
    if (!seasons.length) return;

    const seasonData = seasons
        .map(season => ({
            season,
            perfs: getSeasonEnsemblePerformances(db, canonicalId, track, season),
        }))
        .filter(item => item.perfs.length);

    if (!seasonData.length) return;

    const jumpsNav = document.getElementById('ens-season-jumps-nav');
    if (jumpsNav) {
        jumpsNav.innerHTML = '';
        const jumps = el('nav', 'ensemble-season-jumps');
        seasonData.forEach(({ season }) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'jump-button';
            btn.dataset.jumpTarget = `#ensemble-season-${season}`;
            btn.textContent = season;
            jumps.appendChild(btn);
        });
        jumpsNav.appendChild(jumps);
    }

    const detailed = document.getElementById('ens-detail').checked;

    seasonData.forEach(({ season, perfs }) => {
        const block = el('div', 'season-detail-block');
        block.id = `ensemble-season-${season}`;
        const placement = getLeaderboardPlacement(db, canonicalId, track, season);
        const placementHtml = placement == null
            ? ''
            : ` — Final ranking #<span class="season-ranking-num">${placement}</span>`;
        const lastClass = getTrackLastClassForSeason(db, canonicalId, track, season);
        const heading = el('h4');
        heading.innerHTML = `<span class="season-year-label">${routeButtonHtml('leaderboard', String(season), {
            season,
            classCode: lastClass,
        })}</span> — ${escapeHtml(_ensState.canonicalName)}${placementHtml}`;
        block.appendChild(heading);

        const allCaptionRows = querySeasonEnsembleCaptions(db, canonicalId, track, season);
        const allRawRows = detailed ? getSeasonEnsembleRawScores(db, canonicalId, track, season) : [];

        const FINALS_STAGE = 'championship_finals';
        const finalsPerfs = perfs.filter(p => (p.display_stage || p.event_stage) === FINALS_STAGE);
        const regularPerfs = perfs.filter(p => (p.display_stage || p.event_stage) !== FINALS_STAGE);
        const hasBoth = finalsPerfs.length > 0 && regularPerfs.length > 0;

        const buildSubTable = (subPerfs) => {
            const keys = new Set(subPerfs.map(p => p.performance_key));
            const subCaptionRows = allCaptionRows.filter(r => keys.has(r.performance_key));
            const subRawRows = allRawRows.filter(r => keys.has(r.performance_key));
            const subCaptionMap = buildCaptionMapFromRows(subCaptionRows);
            const scoreModel = detailed
                ? buildDetailedScoreModel(subRawRows, subCaptionMap, false)
                : buildCaptionScoreModel(subCaptionRows, subCaptionMap);
            const scoreColumns = getColumnsForPerfs(subPerfs, scoreModel);
            const useGroups = detailed && scoreColumns.length > 0 && scoreColumns[0].caption != null;
            const isFinalsOnly = subPerfs.every(p => (p.display_stage || p.event_stage) === FINALS_STAGE);
            const useJudgeGroups = useGroups && (
                isFinalsOnly || scoreColumns.some(c => (colJudgeGroup(c) ?? 0) > 1)
            );

            const headers = [
                'Date',
                'Week',
                'Competition',
                ...(track.classCodes.length > 1 ? ['Class'] : []),
                'Stage',
                ...scoreColumns.map(c => ({
                    label: c.label, num: true,
                    captionGroup: useGroups ? c.caption : null,
                    judgeGroup: useJudgeGroups ? colJudgeGroup(c) : undefined,
                    judgeLabel: useJudgeGroups && isFinalsOnly ? (c.judgeLabel || null) : null,
                    role: useGroups ? c.role : null,
                })),
                { label: 'Total', num: true },
                { label: 'Rank', num: true },
            ];
            const rows = subPerfs.map(p => {
                const scores = scoreModel.scores[p.performance_key] || {};
                return [
                    fmt.date(p.performance_date),
                    fmt.int(p.season_week_calendar),
                    {
                        html: routeButtonHtml('show', escapeHtml(p.competition_name), {
                            season: p.season_year,
                            date: p.performance_date,
                            performanceKey: p.performance_key,
                        }),
                    },
                    ...(track.classCodes.length > 1 ? [fmt.classCode(p.class_code)] : []),
                    fmtStage(p.display_stage || p.event_stage),
                    ...scoreColumns.map(c => fmt.score(scores[c.key])),
                    fmt.score(p.total_score),
                    fmt.int(p.total_rank),
                ];
            });
            return buildTable(headers, rows);
        };

        if (hasBoth) {
            block.appendChild(el('div', 'block-heading', 'Regular Season / Prelims'));
            block.appendChild(wrapTable(buildSubTable(regularPerfs)));

            block.appendChild(el('div', 'block-heading', 'Finals'));
            block.appendChild(wrapTable(buildSubTable(finalsPerfs)));
        } else {
            block.appendChild(wrapTable(buildSubTable(perfs)));
        }

        container.appendChild(block);
    });
}

function querySeasonEnsembleCaptions(db, canonicalId, track, season) {
    const filter = trackWhere(track);
    return query(db,
        `SELECT performance_key, caption,
            COALESCE(
                MAX(CASE WHEN role='caption_total' THEN score END),
                AVG(CASE WHEN role='judge_total' AND subcaption='total' THEN score END)
            ) AS score
         FROM v_frontend_show_scores
         WHERE canonical_ensemble_id = ?
           ${filter.sql}
           AND season_year = ?
           AND (role = 'caption_total' OR (role = 'judge_total' AND subcaption = 'total'))
         GROUP BY performance_key, caption
         ORDER BY performance_key, caption`,
        [canonicalId, ...filter.params, season]
    );
}

// ============================================================
// Judge Statistics
// ============================================================

function initJudgeStats(db) {
    renderJudgeStats(db);
}

function renderJudgeStats(db) {
    const container = document.getElementById('judge-content');
    container.innerHTML = '';
    const rows = getJudgeDirectory(db);
    container.appendChild(el('h2', 'section-title', 'Judge Statistics'));
    container.appendChild(el('p', 'section-note', 'Full names are manually maintained in config/judge_names.csv. Raw parsed judge labels remain unchanged.'));
    const table = buildTable(
        [
            'Judge Label',
            'Display Name',
            'Status',
            { label: 'Score Rows', num: true },
            { label: 'Performances', num: true },
        ],
        rows.map(r => [
            r.judge_abbrev,
            r.judge_display_name,
            r.mapping_status,
            fmt.int(r.score_rows),
            fmt.int(r.performance_count),
        ])
    );
    container.appendChild(wrapTable(table));
}

// ============================================================
// SQL Query
// ============================================================

function initSqlTab(db) {
    renderSqlSchema(db);
    document.getElementById('sql-run').addEventListener('click', () => renderSqlResults(db));
    document.getElementById('sql-clear').addEventListener('click', () => {
        document.getElementById('sql-input').value = '';
        document.getElementById('sql-results').innerHTML = '';
        setSqlMessage('');
    });
}

function renderSqlSchema(db) {
    const container = document.getElementById('sql-schema');
    const objects = getSchemaObjects(db);
    const tables = objects.filter(o => o.type === 'table').map(o => o.name);
    const views = objects.filter(o => o.type === 'view').map(o => o.name);
    container.innerHTML = `
        <h3>Schema Reference</h3>
        <p>Read-only queries may start with SELECT or WITH. Display is capped at 500 rows.</p>
        <h4>Tables</h4>
        <p>${tables.map(escapeHtml).join(', ')}</p>
        <h4>Views</h4>
        <p>${views.map(escapeHtml).join(', ')}</p>
        <h4>Examples</h4>
        <pre>SELECT * FROM v_frontend_season_leaderboard WHERE season_year = 2026 LIMIT 20;</pre>
        <pre>SELECT canonical_ensemble_name, total_score FROM v_frontend_ensemble_performances ORDER BY total_score DESC LIMIT 10;</pre>
    `;
}

function renderSqlResults(db) {
    const sql = document.getElementById('sql-input').value;
    const container = document.getElementById('sql-results');
    container.innerHTML = '';
    setSqlMessage('');
    try {
        const result = runReadOnlySql(db, sql);
        if (!result.rows.length) {
            container.appendChild(el('p', 'empty-msg', 'Query returned no rows.'));
            return;
        }
        const columns = Object.keys(result.rows[0]);
        const table = buildTable(
            columns.map(col => ({ label: col, num: result.rows.every(row => isNumericOrEmpty(row[col])) })),
            result.rows.map(row => columns.map(col => formatSqlCell(row[col])))
        );
        container.appendChild(wrapTable(table));
        if (result.truncated) {
            setSqlMessage(`Showing first 500 of ${result.totalRows} rows.`);
        }
    } catch (error) {
        setSqlMessage(error.message);
    }
}

function setSqlMessage(message) {
    const el = document.getElementById('sql-message');
    el.textContent = message;
    el.hidden = !message;
}

function isNumericOrEmpty(value) {
    return value == null || value === '' || !Number.isNaN(Number(value));
}

function formatSqlCell(value) {
    if (value == null) return '--';
    return String(value);
}

// ============================================================
// Main bootstrap
// ============================================================

(async () => {
    const statusBar = document.getElementById('status-bar');

    let SQL;
    try {
        SQL = await initSqlJs({ locateFile: f => `js/${f}` });
    } catch (e) {
        statusBar.textContent = `Failed to load sql.js: ${e.message}`;
        return;
    }

    statusBar.textContent = 'Fetching database…';
    let db;
    try {
        const resp = await fetch('scores.db');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const buf = await resp.arrayBuffer();
        db = new SQL.Database(new Uint8Array(buf));
    } catch (e) {
        statusBar.textContent = `Failed to load database: ${e.message}`;
        return;
    }

    _db = db;
    statusBar.innerHTML = '<span class="db-ready-dot"></span>Database ready';

    document.getElementById('app').hidden = false;

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
    bindGlobalRoutes();

    initLeaderboard(db);
    initShowRecords(db);
    initEnsembleView(db);
    // initJudgeStats(db);   // hidden — dev-branch feature
    // initSqlTab(db);       // hidden — dev-branch feature
})();
