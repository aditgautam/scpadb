// ============================================================
// Formatting helpers
// ============================================================

const fmt = {
    score: v => (v == null ? '--' : Number(v).toFixed(3)),
    int:   v => (v == null ? '--' : String(v)),
    str:   v => (v == null || v === '' ? '--' : String(v)),
    date:  (v, includeYear = false) => formatDate(v, includeYear),
    classCode: v => (v == null ? '--' : String(v).toUpperCase()),
};

function formatDate(value, includeYear = false) {
    if (value == null || value === '') return '--';
    const [year, month, day] = String(value).split('-').map(Number);
    if (!year || !month || !day) return String(value);
    return includeYear
        ? `${month}/${day}/${String(year).slice(-2)}`
        : `${month}/${day}`;
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

function getEnsembleTracks(db, canonicalId) {
    return query(db,
        `SELECT *
         FROM ensemble_class_tracks
         WHERE canonical_ensemble_id = ?
         ORDER BY display_order, track_label`,
        [canonicalId]
    ).map(trackFromRow);
}

function trackFromRow(row) {
    return {
        ...row,
        classCodes: splitCsv(row.class_codes),
        seasonYears: splitCsv(row.season_years).map(Number),
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
    const classPlaceholders = track.classCodes.map(() => '?').join(',');
    const seasonPlaceholders = track.seasonYears.map(() => '?').join(',');
    return {
        sql: ` AND ${prefix}class_code IN (${classPlaceholders})
               AND ${prefix}season_year IN (${seasonPlaceholders})`,
        params: [...track.classCodes, ...track.seasonYears],
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
            p.canonical_ensemble_id,
            p.season_year,
            GROUP_CONCAT(DISTINCT p.class_code) AS class_codes
         FROM v_frontend_ensemble_performances p
         WHERE EXISTS (
            SELECT 1
            FROM ensemble_class_tracks t
            WHERE t.canonical_ensemble_id = p.canonical_ensemble_id
              AND t.class_codes LIKE '%,%'
         )
         GROUP BY p.canonical_ensemble_id, p.season_year
         HAVING COUNT(DISTINCT p.class_code) > 1`
    );
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
    const hrow = document.createElement('tr');
    headers.forEach(h => {
        const th = document.createElement('th');
        th.textContent = typeof h === 'object' ? h.label : h;
        if (typeof h === 'object' && h.num) th.className = 'num';
        hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach(row => {
        const cells = Array.isArray(row) ? row : row.cells;
        const tr = document.createElement('tr');
        if (!Array.isArray(row) && row.className) tr.className = row.className;
        if (!Array.isArray(row) && row.rowId) tr.id = row.rowId;
        cells.forEach((cell, i) => {
            const td = document.createElement('td');
            const hdr = headers[i];
            const isNum = typeof hdr === 'object' && hdr.num;
            if (cell && typeof cell === 'object' && 'html' in cell) {
                td.innerHTML = cell.html;
            } else {
                td.textContent = cell ?? '--';
            }
            td.className = isNum ? 'num' : '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
}

function wrapTable(table) {
    const w = makeTableWrap();
    w.appendChild(table);
    return w;
}

const _showSortState = {};

function buildSortableTable(headers, rows, tableKey) {
    const table = document.createElement('table');
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

    const thead = document.createElement('thead');
    const hrow = document.createElement('tr');
    headers.forEach(h => {
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
                let next = { key: h.key, direction: 'asc' };
                if (current.key === h.key && current.direction === 'asc') {
                    next = { key: h.key, direction: 'desc' };
                } else if (current.key === h.key && current.direction === 'desc') {
                    next = { key: null, direction: null };
                }
                _showSortState[tableKey] = next;
                renderShowRecords(_db);
            });
        }
        hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    renderedRows.forEach(row => {
        const tr = document.createElement('tr');
        if (row.className) tr.className = row.className;
        if (row.rowId) tr.id = row.rowId;
        row.cells.forEach((cell, i) => {
            const td = document.createElement('td');
            if (headers[i].num) td.className = 'num';
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
    setSelectValue('lb-season', season);
    renderLeaderboard(_db);
    if (classCode) highlightBySelector(`#leaderboard-${classCode}`);
}

function routeToShowRecords(season, date, performanceKey = null) {
    switchTab('show-records');
    setSelectValue('sr-season', season);
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
}

function bindGlobalRoutes() {
    document.addEventListener('click', event => {
        const jump = event.target.closest('[data-jump-target]');
        if (jump) {
            event.preventDefault();
            highlightBySelector(jump.dataset.jumpTarget);
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
    const sel = document.getElementById('lb-season');
    const buttons = document.getElementById('lb-season-buttons');
    const seasons = getSeasons(db);
    sel.innerHTML = '';
    buttons.innerHTML = '';
    seasons.forEach(y => {
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        sel.appendChild(opt);

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'season-button';
        btn.dataset.season = y;
        btn.textContent = y;
        btn.addEventListener('click', () => {
            sel.value = y;
            renderLeaderboard(db);
        });
        buttons.appendChild(btn);
    });
    sel.addEventListener('change', () => renderLeaderboard(db));
    renderLeaderboard(db);
}

function renderLeaderboard(db) {
    const season = Number(document.getElementById('lb-season').value);
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
            lookup.add(`${row.canonical_ensemble_id}|${row.season_year}|${cls}`);
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
    const seasonSel = document.getElementById('sr-season');
    const dateSel = document.getElementById('sr-date');
    const combineChk = document.getElementById('sr-combine');
    const detailChk = document.getElementById('sr-detail');

    const seasons = getSeasons(db);
    seasonSel.innerHTML = '';
    seasons.forEach(y => {
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        seasonSel.appendChild(opt);
    });

    seasonSel.addEventListener('change', () => populateShowDates(db));
    dateSel.addEventListener('change', () => renderShowRecords(db));
    combineChk.addEventListener('change', () => renderShowRecords(db));
    detailChk.addEventListener('change', () => renderShowRecords(db));
    populateShowDates(db);
}

function populateShowDates(db) {
    const seasonSel = document.getElementById('sr-season');
    const dateSel = document.getElementById('sr-date');
    const season = Number(seasonSel.value);
    const selected = dateSel.value;
    const days = getShowDays(db, season);
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
    const season = Number(document.getElementById('sr-season').value);
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
            const columns = getColumnsForPerfs(allPerfs, scoreModel);
            section.appendChild(buildShowTable(allPerfs, scoreModel, columns, false, `${season}:${date}:${cls}:combined`));
        } else {
            rounds.forEach(round => {
                if (hasMultipleRounds) {
                    const label = round === '__none__' ? 'Block' : `Block ${round}`;
                    section.appendChild(el('div', 'block-heading', label));
                }
                const columns = getColumnsForPerfs(byRound[round], scoreModel);
                section.appendChild(buildShowTable(byRound[round], scoreModel, columns, true, `${season}:${date}:${cls}:${round}`));
            });
        }

        container.appendChild(section);
    });
}

function buildCaptionScoreModel(captionRows, captionMap) {
    const columns = [...new Set(captionRows.map(r => r.caption))]
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
            const slot = hideJudgeSlots || row.judge_slot == null ? '' : ` J${row.judge_slot}`;
            key = `raw:${row.caption}:${row.subcaption}:${row.judge_slot ?? ''}`;
            label = `${fmtCaption(row.subcaption)}${slot}`;
        } else if (row.role === 'judge_total' && row.subcaption === 'total') {
            const slot = hideJudgeSlots || row.judge_slot == null ? '' : ` J${row.judge_slot}`;
            key = `judge:${row.caption}:${row.judge_slot ?? ''}`;
            label = `${fmtCaption(row.caption)} Total${slot}`;
        } else if (row.role === 'caption_total') {
            key = `cap:${row.caption}`;
            label = fmtCaption(row.caption);
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
                columnMap.set(key, {
                    key,
                    label: fmtCaption(caption),
                    caption,
                    role: 'caption_total',
                    judgeSlot: 100,
                    subcaption: 'total',
                });
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
    return { columns, scores };
}

function getColumnsForPerfs(perfs, scoreModel) {
    const keys = new Set();
    perfs.forEach(p => {
        const scores = scoreModel.scores[p.performance_key] || {};
        Object.keys(scores).forEach(key => keys.add(key));
    });
    return scoreModel.columns.filter(col => keys.has(col.key));
}

function buildShowTable(perfs, scoreModel, scoreColumns, showSubtotals, tableKey) {
    const headers = [
        { label: '#', key: 'rank' },
        { label: 'Ensemble', key: 'ensemble' },
        ...scoreColumns.map(c => ({ label: c.label, key: c.key, num: true, sortable: true })),
    ];
    if (showSubtotals) {
        headers.push({ label: 'Subtotal', key: 'subtotal', num: true, sortable: true });
        headers.push({ label: 'Penalty', key: 'penalty', num: true, sortable: true });
    }
    headers.push({ label: 'Total', key: 'total', num: true, sortable: true });

    const sorted = [...perfs].sort((a, b) => {
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
            p.placement ?? p.total_rank ?? '--',
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
            cells.push(fmt.score(p.penalty_score));
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
    return raw
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
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
            noteEl.hidden = true;
            populateEnsembleSeasons(db);
            renderEnsembleView(db);
        } else {
            document.getElementById('ens-content').hidden = true;
        }
    });

    detailChk.addEventListener('change', () => renderEnsembleView(db));
}

function selectEnsemble(db, canonicalId, displayName, options = {}) {
    document.getElementById('ens-content').hidden = true;

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
    const noteEl = document.getElementById('ens-class-note');

    searchEl.value = displayName;
    dropdown.hidden = true;
    noteEl.hidden = true;
    noteEl.textContent = '';

    const tracks = _ensState.tracks;
    const contextualTrack = chooseTrackForContext(tracks, options.season, options.classCode);
    const needsChoice = tracks.length > 1 && !contextualTrack;
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

    renderRecentScores(db, canonicalId, track);
    renderTrendChart(db, canonicalId, track, [...selectedSeasons].sort());
    renderSeasonDetails(db, canonicalId, track, detailSeasons.slice().sort((a,b) => b-a));
}

function renderRecentScores(db, canonicalId, track) {
    const rows = getRecentScores(db, canonicalId, track);
    const container = document.getElementById('ens-recent');
    container.innerHTML = '';

    if (!rows.length) {
        container.appendChild(el('p', 'empty-msg', 'No recent scores.'));
        return;
    }

    const table = buildTable(
        [
            'Date',
            'Season',
            'Week',
            'Competition',
            ...(track.classCodes.length > 1 ? ['Class'] : []),
            'Stage',
            { label: 'Total', num: true },
            { label: 'Rank', num: true },
        ],
        rows.map(r => [
            fmt.date(r.performance_date),
            fmt.int(r.season_year),
            fmt.int(r.season_week_calendar),
            {
                html: routeButtonHtml('show', escapeHtml(r.competition_name), {
                    season: r.season_year,
                    date: r.performance_date,
                    performanceKey: r.performance_key,
                }),
            },
            ...(track.classCodes.length > 1 ? [fmt.classCode(r.class_code)] : []),
            fmtStage(r.display_stage || r.event_stage),
            fmt.score(r.total_score),
            fmt.int(r.total_rank),
        ])
    );
    container.appendChild(wrapTable(table));
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

    const shell = el('div', 'chart-shell');
    const plot = el('div', 'chart-plot');
    const menu = el('div', 'chart-season-menu');
    shell.appendChild(plot);
    shell.appendChild(menu);
    container.appendChild(shell);

    const allSeasons = _ensState.detailSeasons.slice().sort((a, b) => b - a);
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

    sortedSeasons.forEach(season => {
        const sData = bySeason[season];
        if (!sData) return;
        const color = colorScale(season);

        g.append('path')
            .datum(sData)
            .attr('fill', 'none')
            .attr('stroke', color)
            .attr('stroke-width', 2)
            .attr('d', line);

        g.selectAll(null)
            .data(sData.filter(r => r.total_score != null))
            .enter()
            .append('circle')
            .attr('cx', r => x(r.season_week_calendar))
            .attr('cy', r => y(r.total_score))
            .attr('r', 5)
            .attr('fill', color)
            .attr('stroke', '#fff')
            .attr('stroke-width', 1.5);

        g.selectAll(null)
            .data(sData.filter(r => r.total_score != null))
            .enter()
            .append('circle')
            .attr('cx', r => x(r.season_week_calendar))
            .attr('cy', r => y(r.total_score))
            .attr('r', 11)
            .attr('fill', 'transparent')
            .append('title')
            .text(r =>
                `${fmt.date(r.performance_date)}\n${r.competition_name}\n${fmt.score(r.total_score)}\n${fmt.classCode(r.class_code)} · ${fmtStage(r.display_stage || r.event_stage)}`
            );
    });

    menu.querySelectorAll('.chart-season-button').forEach(btn => {
        const season = Number(btn.textContent);
        btn.style.setProperty('--season-color', allSeasonColorScale(season));
    });
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

    const jumps = el('nav', 'ensemble-season-jumps');
    seasonData.forEach(({ season }) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'jump-button';
        btn.dataset.jumpTarget = `#ensemble-season-${season}`;
        btn.textContent = season;
        jumps.appendChild(btn);
    });
    container.appendChild(jumps);

    const detailed = document.getElementById('ens-detail').checked;

    seasonData.forEach(({ season, perfs }) => {
        const block = el('div', 'season-detail-block');
        block.id = `ensemble-season-${season}`;
        const placement = getLeaderboardPlacement(db, canonicalId, track, season);
        const placementText = placement == null ? '' : ` - Final ranking #${placement}`;
        const lastClass = getTrackLastClassForSeason(db, canonicalId, track, season);
        const heading = el('h4');
        heading.innerHTML = `${routeButtonHtml('leaderboard', String(season), {
            season,
            classCode: lastClass,
        })} - ${escapeHtml(_ensState.canonicalName)}${escapeHtml(placementText)}`;
        block.appendChild(heading);

        const captionRows = querySeasonEnsembleCaptions(db, canonicalId, track, season);
        const captionMap = {};
        captionRows.forEach(r => {
            if (!captionMap[r.performance_key]) captionMap[r.performance_key] = {};
            captionMap[r.performance_key][r.caption] = r.score;
        });
        const scoreModel = detailed
            ? buildDetailedScoreModel(getSeasonEnsembleRawScores(db, canonicalId, track, season), captionMap, false)
            : buildCaptionScoreModel(captionRows, captionMap);
        const scoreColumns = getColumnsForPerfs(perfs, scoreModel);

        const headers = [
            'Date',
            'Week',
            'Competition',
            ...(track.classCodes.length > 1 ? ['Class'] : []),
            'Stage',
            ...scoreColumns.map(c => ({ label: c.label, num: true })),
            { label: 'Total', num: true },
            { label: 'Rank', num: true },
        ];
        const rows = perfs.map(p => {
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

        block.appendChild(wrapTable(buildTable(headers, rows)));
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
    statusBar.textContent = 'Ready';

    document.getElementById('app').hidden = false;

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
    bindGlobalRoutes();

    initLeaderboard(db);
    initShowRecords(db);
    initEnsembleView(db);
})();
