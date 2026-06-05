(async () => {
    const statusMsg = document.getElementById('status-msg');

    let SQL;
    try {
        SQL = await initSqlJs({ locateFile: (file) => `js/${file}` });
    } catch (e) {
        statusMsg.textContent = `Failed to load sql.js: ${e.message}`;
        return;
    }

    statusMsg.textContent = 'Fetching database…';
    let db;
    try {
        const response = await fetch('cs_parse.db');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const buf = await response.arrayBuffer();
        db = new SQL.Database(new Uint8Array(buf));
    } catch (e) {
        statusMsg.textContent = `Failed to load database: ${e.message}`;
        return;
    }

    statusMsg.textContent = 'Ready.';
    populateFilters(db);

    const debounce = (fn, ms) => {
        let t;
        return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
    };

    document.getElementById('ensemble-search').addEventListener('input', debounce(() => runQuery(db), 200));
    ['class-select', 'year-select', 'caption-select'].forEach((id) => {
        document.getElementById(id).addEventListener('change', () => runQuery(db));
    });

    runQuery(db);
})();

function populateFilters(db) {
    const classSelect = document.getElementById('class-select');
    const result = db.exec(
        "SELECT DISTINCT class_code FROM performances ORDER BY class_code"
    )[0];
    if (result) {
        result.values.forEach(([code]) => {
            const opt = document.createElement('option');
            opt.value = code;
            opt.textContent = code.toUpperCase();
            classSelect.appendChild(opt);
        });
    }

    const yearSelect = document.getElementById('year-select');
    const years = db.exec(
        "SELECT DISTINCT substr(performance_date,1,4) yr FROM performances ORDER BY yr DESC"
    )[0];
    if (years) {
        years.values.forEach(([yr]) => {
            const opt = document.createElement('option');
            opt.value = yr;
            opt.textContent = yr;
            yearSelect.appendChild(opt);
        });
    }

    const captionSelect = document.getElementById('caption-select');
    const captions = db.exec(
        "SELECT DISTINCT caption FROM scores WHERE role='caption_total' ORDER BY caption"
    )[0];
    if (captions) {
        captions.values.forEach(([cap]) => {
            const opt = document.createElement('option');
            opt.value = cap;
            opt.textContent = cap.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
            captionSelect.appendChild(opt);
        });
    }
}

function runQuery(db) {
    const ensemble = document.getElementById('ensemble-search').value.trim();
    const classCode = document.getElementById('class-select').value;
    const year = document.getElementById('year-select').value;

    const conditions = [];
    const params = [];

    if (ensemble) {
        conditions.push('LOWER(p.ensemble_name) LIKE LOWER(?)');
        params.push(`%${ensemble}%`);
    }
    if (classCode) {
        conditions.push('p.class_code = ?');
        params.push(classCode);
    }
    if (year) {
        conditions.push("substr(p.performance_date,1,4) = ?");
        params.push(year);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
    const sql = `
        SELECT p.performance_date, p.ensemble_name, p.class_code,
               p.competition_name, p.total_score, p.total_rank, p.placement
        FROM performances p
        ${where}
        ORDER BY p.performance_date DESC, p.total_score DESC
        LIMIT 500
    `;

    const result = db.exec(sql, params)[0];
    renderTable(result);

    if (ensemble && classCode) {
        renderTrajectory(db, ensemble, classCode);
    } else {
        document.getElementById('charts').hidden = true;
    }
}

function renderTable(result) {
    const section = document.getElementById('results');
    const tbody = document.getElementById('results-body');
    const countSpan = document.getElementById('result-count');

    tbody.innerHTML = '';
    section.hidden = false;

    if (!result || !result.values.length) {
        countSpan.textContent = '(0)';
        return;
    }

    countSpan.textContent = `(${result.values.length})`;

    result.values.forEach((row) => {
        const tr = document.createElement('tr');
        row.forEach((cell, i) => {
            const td = document.createElement('td');
            if (i === 4 && cell != null) {
                td.textContent = Number(cell).toFixed(3);
            } else {
                td.textContent = cell ?? '—';
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function renderTrajectory(db, ensemble, classCode) {
    const result = db.exec(
        `SELECT performance_date, total_score, competition_name
         FROM performances
         WHERE LOWER(ensemble_name) LIKE LOWER(?) AND class_code = ?
         ORDER BY performance_date`,
        [`%${ensemble}%`, classCode]
    )[0];

    const chartsSection = document.getElementById('charts');

    if (!result || result.values.length < 2) {
        chartsSection.hidden = true;
        return;
    }

    const data = result.values.map(([date, score, comp]) => ({
        date: new Date(date),
        score: +score,
        comp,
    }));

    const svg = d3.select('#trajectory-chart');
    svg.selectAll('*').remove();

    const margin = { top: 20, right: 30, bottom: 50, left: 55 };
    const width = Math.min(700, window.innerWidth - 40) - margin.left - margin.right;
    const height = 280 - margin.top - margin.bottom;

    const g = svg
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom)
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3.scaleTime().domain(d3.extent(data, (d) => d.date)).range([0, width]);
    const y = d3.scaleLinear().domain([0, 100]).range([height, 0]).nice();

    g.append('g')
        .attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(x).ticks(5).tickFormat(d3.timeFormat('%b %Y')))
        .selectAll('text')
        .attr('transform', 'rotate(-30)')
        .style('text-anchor', 'end');

    g.append('g').call(d3.axisLeft(y).ticks(5));

    const line = d3.line()
        .x((d) => x(d.date))
        .y((d) => y(d.score));

    g.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', '#4a90d9')
        .attr('stroke-width', 2)
        .attr('d', line);

    g.selectAll('circle')
        .data(data)
        .enter()
        .append('circle')
        .attr('cx', (d) => x(d.date))
        .attr('cy', (d) => y(d.score))
        .attr('r', 4)
        .attr('fill', '#4a90d9')
        .attr('stroke', '#fff')
        .attr('stroke-width', 1.5)
        .append('title')
        .text((d) => `${d.comp}\n${d.score.toFixed(3)}`);

    chartsSection.hidden = false;
}
