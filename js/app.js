// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  selectedCourts: new Set(Object.keys(COURTS)),
  currentView: 'calendar',
};

let fcCalendar = null;

// ─── Entry point ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  renderCourtList();
  initCalendar();
  renderOverlaps();
  renderList();
  initViewTabs();
});

// ─── Date utilities ──────────────────────────────────────────────────────────

// Returns array of 'YYYY-MM-DD' strings for every day in [start, endInclusive].
function expandDates(start, endInclusive) {
  const result = [];
  const cur = parseDateUTC(start);
  const last = parseDateUTC(endInclusive || start);
  while (cur <= last) {
    result.push(toYMD(cur));
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  return result;
}

function parseDateUTC(ymd) {
  const [y, m, d] = ymd.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function toYMD(d) {
  return d.toISOString().split('T')[0];
}

function addOneDayExclusive(ymd) {
  const d = parseDateUTC(ymd);
  d.setUTCDate(d.getUTCDate() + 1);
  return toYMD(d);
}

function formatDateDisplay(ymd) {
  const d = parseDateUTC(ymd);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}

function formatMonthDay(ymd) {
  const d = parseDateUTC(ymd);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
}

function dayOfWeek(ymd) {
  const d = parseDateUTC(ymd);
  return d.toLocaleDateString('en-IN', { weekday: 'short', timeZone: 'UTC' });
}

// ─── FullCalendar events builder ─────────────────────────────────────────────

function buildFCEvents() {
  const events = [];

  Object.values(COURTS).forEach(court => {
    if (!state.selectedCourts.has(court.id)) return;

    // Holidays
    court.holidays.forEach(h => {
      const ev = {
        id: `${court.id}-h-${h.start}`,
        title: `${court.shortName}: ${h.name}`,
        start: h.start,
        allDay: true,
        backgroundColor: court.color,
        borderColor: court.color,
        textColor: court.textColor,
        extendedProps: { courtId: court.id, courtName: court.name, type: 'holiday', note: h.note || null },
      };
      if (h.end) ev.end = addOneDayExclusive(h.end);
      events.push(ev);
    });

    // Vacations – background bands (no title, just color)
    court.vacations.forEach(v => {
      const [r, g, b] = hexToRgb(court.color);
      const bg = v.type === 'full'
        ? `rgba(${r},${g},${b},0.18)`
        : `rgba(251,146,60,0.22)`;
      events.push({
        id: `${court.id}-v-${v.start}`,
        title: '',
        start: v.start,
        end: addOneDayExclusive(v.end),
        display: 'background',
        color: bg,
        extendedProps: { courtId: court.id, courtName: court.name, type: 'vacation', vacationType: v.type, note: v.note || null, displayName: v.name },
      });
    });

    // Special sitting days
    court.specialDays.forEach(s => {
      events.push({
        id: `${court.id}-s-${s.start}`,
        title: `${court.shortName}: ${s.name}`,
        start: s.start,
        allDay: true,
        backgroundColor: '#7C3AED',
        borderColor: '#7C3AED',
        textColor: '#fff',
        extendedProps: { courtId: court.id, courtName: court.name, type: 'special', note: s.note || null },
      });
    });
  });

  return events;
}

function hexToRgb(hex) {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

// ─── FullCalendar init ────────────────────────────────────────────────────────

function initCalendar() {
  const el = document.getElementById('calendar');
  fcCalendar = new FullCalendar.Calendar(el, {
    initialView: 'dayGridMonth',
    headerToolbar: {
      left: 'prev,next today',
      center: 'title',
      right: 'dayGridMonth,dayGridYear',
    },
    height: 'auto',
    firstDay: 0,
    events: buildFCEvents(),
    eventClick(info) {
      if (info.event.display !== 'background') showTooltip(info);
    },
    eventDidMount(info) {
      if (info.event.display !== 'background') {
        info.el.title = info.event.title;
      }
    },
    dayCellDidMount(info) {
      // Inject vacation label on the first day of each vacation
      const ymd = toYMD(info.date);
      Object.values(COURTS).forEach(court => {
        if (!state.selectedCourts.has(court.id)) return;
        court.vacations.forEach(v => {
          if (v.start === ymd) {
            const label = document.createElement('div');
            label.className = 'vac-label';
            label.style.cssText = `font-size:10px;font-weight:600;color:${court.color};opacity:0.85;padding:1px 4px;line-height:1.4;pointer-events:none;`;
            label.textContent = `${court.shortName}: ${v.name}`;
            info.el.querySelector('.fc-daygrid-day-frame')?.appendChild(label);
          }
        });
      });
    },
  });
  fcCalendar.render();
}

function refreshCalendar() {
  if (!fcCalendar) return;
  fcCalendar.removeAllEvents();
  buildFCEvents().forEach(e => fcCalendar.addEvent(e));
}

// ─── Tooltip ──────────────────────────────────────────────────────────────────

function showTooltip(info) {
  const ep = info.event.extendedProps;
  const court = COURTS[ep.courtId];
  const header = document.getElementById('tooltipHeader');
  const body = document.getElementById('tooltipBody');
  const tooltip = document.getElementById('tooltip');

  header.style.background = court.color;
  header.textContent = info.event.title;

  let html = `<div class="tt-row"><span class="tt-label">Court</span><span>${court.name}</span></div>`;
  html += `<div class="tt-row"><span class="tt-label">Type</span><span class="tt-badge tt-badge--${ep.type}">${ep.type}</span></div>`;

  const start = info.event.startStr;
  const end = info.event.endStr;
  if (end && end !== addOneDayExclusive(start)) {
    const endDisplay = toYMD(new Date(parseDateUTC(end).getTime() - 86400000));
    html += `<div class="tt-row"><span class="tt-label">Period</span><span>${formatDateDisplay(start)} – ${formatDateDisplay(endDisplay)}</span></div>`;
  } else {
    html += `<div class="tt-row"><span class="tt-label">Date</span><span>${formatDateDisplay(start)}</span></div>`;
  }

  if (ep.note) {
    html += `<div class="tt-note">${ep.note}</div>`;
  }
  html += `<button class="tt-close" onclick="document.getElementById('tooltip').classList.add('hidden')">Close</button>`;
  body.innerHTML = html;
  tooltip.classList.remove('hidden');
}

document.addEventListener('click', e => {
  const tooltip = document.getElementById('tooltip');
  if (!tooltip.contains(e.target) && !e.target.closest('.fc-event')) {
    tooltip.classList.add('hidden');
  }
});

// ─── Court list sidebar ───────────────────────────────────────────────────────

function renderCourtList() {
  const container = document.getElementById('courtList');
  container.innerHTML = '';
  Object.values(COURTS).forEach(court => {
    const checked = state.selectedCourts.has(court.id);
    const item = document.createElement('label');
    item.className = 'court-item';
    item.innerHTML = `
      <input type="checkbox" ${checked ? 'checked' : ''} data-court="${court.id}">
      <span class="court-dot" style="background:${court.color}"></span>
      <span class="court-label">${court.name}</span>
    `;
    item.querySelector('input').addEventListener('change', e => {
      if (e.target.checked) state.selectedCourts.add(court.id);
      else state.selectedCourts.delete(court.id);
      refreshCalendar();
      renderOverlaps();
      renderList();
    });
    container.appendChild(item);
  });
}

// ─── View switching ───────────────────────────────────────────────────────────

function initViewTabs() {
  document.querySelectorAll('.view-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.view;
      state.currentView = view;
      document.querySelectorAll('.view-tab').forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
      if (view === 'calendar' && fcCalendar) fcCalendar.updateSize();
    });
  });
}

// ─── Overlap computation ──────────────────────────────────────────────────────

function getClosedDateMap() {
  // Returns Map<date, [{courtId, courtName, color, eventName, type}]>
  const map = new Map();

  const activeCourts = Object.values(COURTS).filter(c => state.selectedCourts.has(c.id));

  activeCourts.forEach(court => {
    const seen = new Set();

    const addDate = (date, eventName, type) => {
      if (!map.has(date)) map.set(date, []);
      if (!seen.has(date)) {
        map.get(date).push({ courtId: court.id, courtName: court.name, color: court.color, eventName, type });
        seen.add(date);
      }
    };

    court.holidays.forEach(h => {
      expandDates(h.start, h.end || h.start).forEach(d => addDate(d, h.name, 'holiday'));
    });

    court.vacations.filter(v => v.type === 'full').forEach(v => {
      expandDates(v.start, v.end).forEach(d => addDate(d, v.name, 'vacation'));
    });
  });

  return map;
}

function computeHolidayOverlaps() {
  const map = getClosedDateMap();
  const result = [];
  map.forEach((entries, date) => {
    const courts = new Set(entries.map(e => e.courtId));
    if (courts.size >= 2) result.push({ date, entries });
  });
  return result.sort((a, b) => a.date.localeCompare(b.date));
}

function computeVacationOverlaps() {
  const activeCourts = Object.values(COURTS).filter(c => state.selectedCourts.has(c.id));
  const overlaps = [];

  for (let i = 0; i < activeCourts.length; i++) {
    for (let j = i + 1; j < activeCourts.length; j++) {
      const a = activeCourts[i];
      const b = activeCourts[j];

      a.vacations.forEach(av => {
        b.vacations.forEach(bv => {
          const overlapStart = av.start > bv.start ? av.start : bv.start;
          const overlapEnd = av.end < bv.end ? av.end : bv.end;
          if (overlapStart <= overlapEnd) {
            overlaps.push({
              start: overlapStart,
              end: overlapEnd,
              entries: [
                { courtId: a.id, courtName: a.name, color: a.color, eventName: av.name, type: av.type },
                { courtId: b.id, courtName: b.name, color: b.color, eventName: bv.name, type: bv.type },
              ],
            });
          }
        });
      });
    }
  }

  return overlaps.sort((a, b) => a.start.localeCompare(b.start));
}

// ─── Overlaps view renderer ───────────────────────────────────────────────────

function renderOverlaps() {
  const container = document.getElementById('overlapsContent');
  const activeCourts = Object.values(COURTS).filter(c => state.selectedCourts.has(c.id));

  if (activeCourts.length < 2) {
    container.innerHTML = '<div class="empty-state">Select at least 2 courts to see overlaps.</div>';
    return;
  }

  const holidayOverlaps = computeHolidayOverlaps();
  const vacationOverlaps = computeVacationOverlaps();

  let html = '';

  // ── Summary cards ──
  html += `<div class="summary-cards">
    <div class="summary-card">
      <div class="summary-num">${holidayOverlaps.length}</div>
      <div class="summary-label">Common Closed Days</div>
    </div>
    <div class="summary-card">
      <div class="summary-num">${vacationOverlaps.length}</div>
      <div class="summary-label">Vacation Period Overlaps</div>
    </div>
  </div>`;

  // ── Common holidays ──
  html += `<div class="section-block">
    <h3 class="section-block-title">Common Closed Days</h3>
    <p class="section-block-desc">Days where all selected courts are closed (holiday or vacation).</p>`;

  if (holidayOverlaps.length === 0) {
    html += '<div class="empty-state">No common closed days found.</div>';
  } else {
    // Group into consecutive runs
    const groups = groupConsecutive(holidayOverlaps);
    html += '<div class="overlap-list">';
    groups.forEach(group => {
      const startDate = group[0].date;
      const endDate = group[group.length - 1].date;
      const isSingle = startDate === endDate;
      const dateDisplay = isSingle
        ? `${formatMonthDay(startDate)} (${dayOfWeek(startDate)})`
        : `${formatMonthDay(startDate)} – ${formatMonthDay(endDate)}`;

      // Collect unique reasons per court
      const courtMap = {};
      group.forEach(day => {
        day.entries.forEach(e => {
          if (!courtMap[e.courtId]) courtMap[e.courtId] = { ...e, reasons: new Set() };
          courtMap[e.courtId].reasons.add(e.eventName);
        });
      });

      html += `<div class="overlap-row">
        <div class="overlap-date">${dateDisplay}</div>
        <div class="overlap-courts">`;
      Object.values(courtMap).forEach(c => {
        html += `<span class="court-pill" style="background:${c.color}20;border-color:${c.color};color:${c.color}">
          <span class="pill-dot" style="background:${c.color}"></span>
          ${c.courtName}: ${[...c.reasons].join(', ')}
        </span>`;
      });
      html += `</div></div>`;
    });
    html += '</div>';
  }
  html += '</div>';

  // ── Vacation overlaps ──
  html += `<div class="section-block">
    <h3 class="section-block-title">Vacation Period Overlaps</h3>
    <p class="section-block-desc">Periods where multiple courts are on vacation or in recess simultaneously.</p>`;

  if (vacationOverlaps.length === 0) {
    html += '<div class="empty-state">No overlapping vacation periods found.</div>';
  } else {
    html += '<div class="overlap-list">';
    vacationOverlaps.forEach(ov => {
      html += `<div class="overlap-row">
        <div class="overlap-date">${formatMonthDay(ov.start)} – ${formatMonthDay(ov.end)}</div>
        <div class="overlap-courts">`;
      ov.entries.forEach(e => {
        const typeLabel = e.type === 'full' ? 'Fully Closed' : 'Partial Working Days';
        html += `<span class="court-pill" style="background:${e.color}20;border-color:${e.color};color:${e.color}">
          <span class="pill-dot" style="background:${e.color}"></span>
          ${e.courtName}: ${e.eventName} <em>(${typeLabel})</em>
        </span>`;
      });
      html += `</div></div>`;
    });
    html += '</div>';
  }
  html += '</div>';

  // ── Court-exclusive closures ──
  html += `<div class="section-block">
    <h3 class="section-block-title">Court-Exclusive Closures</h3>
    <p class="section-block-desc">Holidays observed by only one court — the other courts remain open.</p>`;

  const map = getClosedDateMap();
  const exclusives = {};
  map.forEach((entries, date) => {
    const courts = new Set(entries.map(e => e.courtId));
    if (courts.size === 1) {
      const e = entries[0];
      if (!exclusives[e.courtId]) exclusives[e.courtId] = [];
      exclusives[e.courtId].push({ date, eventName: e.eventName });
    }
  });

  if (Object.keys(exclusives).length === 0) {
    html += '<div class="empty-state">No court-exclusive closures found.</div>';
  } else {
    Object.keys(exclusives).forEach(courtId => {
      const court = COURTS[courtId];
      html += `<div class="exclusive-block">
        <div class="exclusive-header" style="border-left:4px solid ${court.color}">
          <span class="court-dot" style="background:${court.color}"></span>
          ${court.name} only
        </div>
        <div class="exclusive-list">`;
      exclusives[courtId].forEach(item => {
        html += `<div class="exclusive-row">
          <span class="exclusive-date">${formatMonthDay(item.date)} (${dayOfWeek(item.date)})</span>
          <span class="exclusive-name">${item.eventName}</span>
        </div>`;
      });
      html += `</div></div>`;
    });
  }
  html += '</div>';

  container.innerHTML = html;
}

function groupConsecutive(items) {
  if (items.length === 0) return [];
  const groups = [[items[0]]];
  for (let i = 1; i < items.length; i++) {
    const prev = parseDateUTC(items[i - 1].date);
    const cur = parseDateUTC(items[i].date);
    const diff = (cur - prev) / 86400000;
    if (diff === 1) groups[groups.length - 1].push(items[i]);
    else groups.push([items[i]]);
  }
  return groups;
}

// ─── Holiday list view ────────────────────────────────────────────────────────

function renderList() {
  const container = document.getElementById('listContent');
  const activeCourts = Object.values(COURTS).filter(c => state.selectedCourts.has(c.id));

  if (activeCourts.length === 0) {
    container.innerHTML = '<div class="empty-state">No courts selected.</div>';
    return;
  }

  const rows = [];

  activeCourts.forEach(court => {
    court.holidays.forEach(h => {
      expandDates(h.start, h.end || h.start).forEach((date, i) => {
        rows.push({
          date,
          name: h.end && h.end !== h.start ? `${h.name}${i === 0 ? ' (start)' : i === expandDates(h.start, h.end).length - 1 ? ' (end)' : ''}` : h.name,
          displayName: h.name,
          court,
          type: 'holiday',
          note: h.note,
          rangeStart: h.start,
          rangeEnd: h.end || h.start,
        });
      });
    });
    court.vacations.forEach(v => {
      rows.push({
        date: v.start,
        name: v.name,
        displayName: v.name,
        court,
        type: 'vacation',
        rangeStart: v.start,
        rangeEnd: v.end,
        note: v.note,
      });
    });
  });

  // Deduplicate by merging same date + same holiday across courts
  const consolidated = {};
  rows.forEach(r => {
    const key = `${r.rangeStart}-${r.rangeEnd}-${r.displayName}`;
    if (!consolidated[key]) {
      consolidated[key] = { ...r, courts: [r.court] };
    } else {
      if (!consolidated[key].courts.find(c => c.id === r.court.id)) {
        consolidated[key].courts.push(r.court);
      }
    }
  });

  const sorted = Object.values(consolidated).sort((a, b) => a.rangeStart.localeCompare(b.rangeStart));

  let html = `<div class="list-filter">
    <span class="filter-label">Filter:</span>
    <button class="filter-btn active" data-filter="all">All</button>
    <button class="filter-btn" data-filter="common">Common</button>
    <button class="filter-btn" data-filter="holiday">Holidays</button>
    <button class="filter-btn" data-filter="vacation">Vacations</button>
  </div>`;

  html += `<div class="holiday-table-wrap"><table class="holiday-table">
    <thead>
      <tr>
        <th>Date / Period</th>
        <th>Holiday / Occasion</th>
        <th>Court(s)</th>
        <th>Type</th>
      </tr>
    </thead>
    <tbody>`;

  sorted.forEach(r => {
    const isMultiDay = r.rangeStart !== r.rangeEnd;
    const dateDisplay = isMultiDay
      ? `${formatMonthDay(r.rangeStart)} – ${formatMonthDay(r.rangeEnd)}`
      : `${formatMonthDay(r.rangeStart)}<br><small>${dayOfWeek(r.rangeStart)}</small>`;

    const isCommon = r.courts.length >= 2 || (activeCourts.length === 1);
    const filterClass = `row-${r.type} ${isCommon && r.courts.length >= 2 ? 'row-common' : ''}`;

    const courtBadges = r.courts.map(c =>
      `<span class="mini-badge" style="background:${c.color}20;border-color:${c.color};color:${c.color}">${c.shortName}</span>`
    ).join('');

    const typeLabel = r.type === 'vacation'
      ? (r.note && r.note.includes('Partial') ? 'Recess (Partial)' : 'Vacation')
      : 'Holiday';

    html += `<tr class="${filterClass}" data-type="${r.type}" data-common="${r.courts.length >= 2}">
      <td>${dateDisplay}</td>
      <td>${r.displayName}${r.note ? `<br><small class="note-text">${r.note}</small>` : ''}</td>
      <td>${courtBadges}</td>
      <td><span class="type-badge type-badge--${r.type}">${typeLabel}</span></td>
    </tr>`;
  });

  html += '</tbody></table></div>';
  container.innerHTML = html;

  // Wire up filter buttons
  container.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const f = btn.dataset.filter;
      container.querySelectorAll('tbody tr').forEach(row => {
        if (f === 'all') row.style.display = '';
        else if (f === 'common') row.style.display = row.dataset.common === 'true' ? '' : 'none';
        else row.style.display = row.dataset.type === f ? '' : 'none';
      });
    });
  });
}
