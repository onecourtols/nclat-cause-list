/* NCLAT Cause List — frontend logic */
'use strict';

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  selectedDate: null,
  selectedCourt: null,
  cache: {},          // key: `${date}|${courtKey}` → parsed data
  courts: [],         // populated from DOM
  searchTerm: '',
};

// ─── DOM refs ────────────────────────────────────────────────────────────────
const datePills    = document.getElementById('date-pills');
const searchInput  = document.getElementById('search-input');
const matchCount   = document.getElementById('match-count');
const btnClear     = document.getElementById('btn-clear-search');
const btnRefresh   = document.getElementById('btn-refresh');
const lastUpdated  = document.getElementById('last-updated');

// ─── Helpers ─────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Wrap every occurrence of `term` in <mark> inside `text`. */
function highlight(text, term) {
  if (!term) return esc(text);
  const safe = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return esc(text).replace(new RegExp(safe, 'gi'), m => `<mark>${m}</mark>`);
}

function formatDate(isoDate) {
  if (!isoDate) return '';
  const [y, m, d] = isoDate.split('-');
  const dt = new Date(+y, +m - 1, +d);
  return dt.toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' });
}

function showEl(el)  { el.hidden = false; }
function hideEl(el)  { el.hidden = true; }

// ─── Date Pills ──────────────────────────────────────────────────────────────

async function loadDates() {
  try {
    const res = await fetch('/api/dates');
    const { dates } = await res.json();

    datePills.innerHTML = '';

    if (!dates || dates.length === 0) {
      datePills.innerHTML = '<span class="pills-loading">No dates available yet — scrape runs 4–8 PM IST.</span>';
      // Hide all loading spinners and show empty state
      document.querySelectorAll('.panel-loading').forEach(el => hideEl(el));
      document.querySelectorAll('.panel-empty').forEach(el => showEl(el));
      return;
    }

    dates.forEach(({ date, label }) => {
      const btn = document.createElement('button');
      btn.className = 'date-pill';
      btn.dataset.date = date;
      btn.textContent = label
        ? `${label} (${formatDate(date)})`
        : formatDate(date);
      btn.addEventListener('click', () => selectDate(date));
      datePills.appendChild(btn);
    });

    // Auto-select the first date
    selectDate(dates[0].date);
  } catch (e) {
    datePills.innerHTML = '<span class="pills-loading">Failed to load dates.</span>';
    console.error(e);
  }
}

function selectDate(date) {
  state.selectedDate = date;

  // Update pill active state
  document.querySelectorAll('.date-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.date === date);
  });

  // Reload current court panel, refresh all badges
  loadCourtData(state.selectedCourt);
  refreshAllBadges();
}

// ─── Court Tabs ──────────────────────────────────────────────────────────────

function initTabs() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  state.courts = Array.from(tabBtns).map(b => b.dataset.court);

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.court;
      activateTab(key);
      loadCourtData(key);
    });
  });

  // Default active court from DOM
  const firstActive = document.querySelector('.tab-btn.active');
  state.selectedCourt = firstActive?.dataset.court ?? state.courts[0];
}

function activateTab(courtKey) {
  state.selectedCourt = courtKey;

  document.querySelectorAll('.tab-btn').forEach(b => {
    const active = b.dataset.court === courtKey;
    b.classList.toggle('active', active);
    b.setAttribute('aria-selected', active ? 'true' : 'false');
  });

  document.querySelectorAll('.tab-panel').forEach(p => {
    const active = p.dataset.court === courtKey;
    p.classList.toggle('active', active);
    if (active) {
      p.removeAttribute('hidden');
    } else {
      p.setAttribute('hidden', '');
    }
  });

  // Re-apply search filter to newly visible panel
  applySearch();
}

// ─── Data loading ─────────────────────────────────────────────────────────────

async function loadCourtData(courtKey) {
  if (!state.selectedDate || !courtKey) return;

  const cacheKey = `${state.selectedDate}|${courtKey}`;
  if (state.cache[cacheKey]) {
    renderPanel(courtKey, state.cache[cacheKey]);
    return;
  }

  // Show loading state
  showLoading(courtKey);

  try {
    const res = await fetch(
      `/api/cause-list?date=${encodeURIComponent(state.selectedDate)}&court_key=${encodeURIComponent(courtKey)}`
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    state.cache[cacheKey] = data;
    renderPanel(courtKey, data);
  } catch (e) {
    hideLoading(courtKey);
    showEmpty(courtKey);
    console.error('Failed to load court data:', e);
  }
}

function showLoading(courtKey) {
  showEl(document.getElementById(`loading-${courtKey}`));
  hideEl(document.getElementById(`content-${courtKey}`));
  hideEl(document.getElementById(`empty-${courtKey}`));
}

function hideLoading(courtKey) {
  hideEl(document.getElementById(`loading-${courtKey}`));
}

function showEmpty(courtKey) {
  showEl(document.getElementById(`empty-${courtKey}`));
  hideEl(document.getElementById(`content-${courtKey}`));
}

// ─── Rendering ───────────────────────────────────────────────────────────────

/**
 * Returns the canonical list of column definitions to render.
 * Keys must match what pdf_parser.py emits.
 * Adjust here if the PDF parser column names change.
 */
function getColumns(items) {
  if (!items || items.length === 0) return [];

  // Detect which columns are actually present in the data
  const known = [
    { key: 'sno',               label: 'S.No.',      cls: 'sno'     },
    { key: 'case_no',           label: 'Case No.',   cls: 'case-no' },
    { key: 'parties',           label: 'Parties',    cls: 'parties' },
    { key: 'counsel_appellant', label: 'Counsel (Appellant)',  cls: 'counsel' },
    { key: 'counsel_respondent',label: 'Counsel (Respondent)', cls: 'counsel' },
    { key: 'remarks',           label: 'Remarks',    cls: 'counsel' },
    { key: 'coram',             label: 'Coram',      cls: 'counsel' },
  ];

  const presentKeys = new Set(items.flatMap(r => Object.keys(r)));
  return known.filter(c => presentKeys.has(c.key));
}

function buildTable(items, columns, term) {
  if (!items.length) return '<p class="panel-empty-inline">No items in this list.</p>';

  const headerCells = columns.map(c => `<th>${esc(c.label)}</th>`).join('');

  const rows = items.map(item => {
    const cells = columns.map(c => {
      const val = item[c.key] ?? '';
      return `<td class="${c.cls}">${highlight(val, term)}</td>`;
    }).join('');
    return `<tr data-search="${esc(JSON.stringify(item)).toLowerCase()}">${cells}</tr>`;
  }).join('');

  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderPanel(courtKey, data) {
  hideLoading(courtKey);

  const { supplementary = [], main = [], pdf_urls = {} } = data;

  if (!supplementary.length && !main.length) {
    showEmpty(courtKey);
    return;
  }

  const term = state.searchTerm;
  const contentEl = document.getElementById(`content-${courtKey}`);
  let html = '';

  // ── Supplementary list (shown first, per spec) ──
  if (supplementary.length) {
    const cols = getColumns(supplementary);
    const pdfLink = pdf_urls.supplementary
      ? `<a class="section-pdf-link" href="${esc(pdf_urls.supplementary)}" target="_blank" rel="noreferrer">📄 PDF</a>`
      : '';
    html += `
      <div class="list-section supplementary">
        <div class="section-header">
          <span class="section-title">
            ⭐ Supplementary List
            <span class="section-badge">${supplementary.length} items</span>
          </span>
          ${pdfLink}
        </div>
        ${buildTable(supplementary, cols, term)}
      </div>`;
  }

  // ── Main list ──
  if (main.length) {
    const cols = getColumns(main);
    const pdfLink = pdf_urls.main
      ? `<a class="section-pdf-link" href="${esc(pdf_urls.main)}" target="_blank" rel="noreferrer">📄 PDF</a>`
      : '';
    html += `
      <div class="list-section main">
        <div class="section-header">
          <span class="section-title">
            Daily Cause List
            <span class="section-badge">${main.length} items</span>
          </span>
          ${pdfLink}
        </div>
        ${buildTable(main, cols, term)}
      </div>`;
  }

  contentEl.innerHTML = html;
  showEl(contentEl);
  hideEl(document.getElementById(`empty-${courtKey}`));

  // Update tab badge
  const badge = document.getElementById(`badge-${courtKey}`);
  const total = supplementary.length + main.length;
  if (total > 0) {
    badge.textContent = total;
    showEl(badge);
  }

  applySearch();
}

// ─── Badges for all courts (background prefetch) ──────────────────────────────

async function refreshAllBadges() {
  if (!state.selectedDate) return;
  for (const key of state.courts) {
    if (key === state.selectedCourt) continue; // already loaded
    const cacheKey = `${state.selectedDate}|${key}`;
    if (state.cache[cacheKey]) continue;
    // Fire-and-forget; badge updates happen inside renderPanel
    loadCourtDataBackground(key);
  }
}

async function loadCourtDataBackground(courtKey) {
  const cacheKey = `${state.selectedDate}|${courtKey}`;
  try {
    const res = await fetch(
      `/api/cause-list?date=${encodeURIComponent(state.selectedDate)}&court_key=${encodeURIComponent(courtKey)}`
    );
    if (!res.ok) return;
    const data = await res.json();
    state.cache[cacheKey] = data;

    // Update badge only (don't re-render the panel if it's not active)
    const total = (data.supplementary?.length ?? 0) + (data.main?.length ?? 0);
    const badge = document.getElementById(`badge-${courtKey}`);
    if (badge && total > 0) {
      badge.textContent = total;
      showEl(badge);
    }
  } catch { /* silent */ }
}

// ─── Search ───────────────────────────────────────────────────────────────────

function applySearch() {
  const term = state.searchTerm.trim().toLowerCase();
  const panel = document.querySelector('.tab-panel.active');
  if (!panel) return;

  const rows = panel.querySelectorAll('tbody tr');
  let visible = 0;

  rows.forEach(row => {
    const text = row.dataset.search ?? row.textContent.toLowerCase();
    const match = !term || text.includes(term);
    row.classList.toggle('hidden-row', !match);
    row.classList.toggle('highlight', !!(term && match));
    if (match) visible++;
  });

  // Update highlights in cells
  if (term) {
    panel.querySelectorAll('td').forEach(td => {
      const rawText = td.dataset.raw ?? td.textContent;
      td.dataset.raw = rawText;
      td.innerHTML = highlight(rawText, term);
    });
  } else {
    panel.querySelectorAll('td[data-raw]').forEach(td => {
      td.innerHTML = esc(td.dataset.raw);
      delete td.dataset.raw;
    });
  }

  // Match counter
  if (term && rows.length > 0) {
    matchCount.textContent = `${visible} of ${rows.length}`;
    showEl(matchCount);
  } else {
    hideEl(matchCount);
  }

  // Clear button
  if (term) showEl(btnClear); else hideEl(btnClear);
}

searchInput.addEventListener('input', () => {
  state.searchTerm = searchInput.value;
  applySearch();
});

btnClear.addEventListener('click', () => {
  searchInput.value = '';
  state.searchTerm = '';
  applySearch();
  searchInput.focus();
});

// ─── Manual Refresh ───────────────────────────────────────────────────────────

btnRefresh.addEventListener('click', async () => {
  if (btnRefresh.classList.contains('loading')) return;
  btnRefresh.classList.add('loading');
  btnRefresh.textContent = '↻ Scraping…';

  try {
    const res = await fetch('/api/scrape', { method: 'POST' });
    const data = await res.json();
    if (data.error) {
      alert(`Scrape error: ${data.error}`);
    } else {
      // Clear cache and reload
      state.cache = {};
      await loadDates();
      loadCourtData(state.selectedCourt);
    }
  } catch (e) {
    alert('Scrape request failed. Is the server running?');
  } finally {
    btnRefresh.classList.remove('loading');
    btnRefresh.textContent = '↻ Refresh';
  }
});

// ─── Status / last updated ────────────────────────────────────────────────────

async function loadStatus() {
  try {
    const res = await fetch('/api/status');
    const { last_scrape } = await res.json();
    if (last_scrape?.finished_at) {
      const d = new Date(last_scrape.finished_at + 'Z');
      lastUpdated.textContent = `Last scraped: ${d.toLocaleTimeString('en-IN')}`;
    }
  } catch { /* silent */ }
}

// ─── Boot ─────────────────────────────────────────────────────────────────────

(async function boot() {
  initTabs();
  await loadDates();
  loadStatus();
})();
