/**
 * Cloudflare Worker — SCI Case Status Proxy
 *
 * Deploy this on Cloudflare Workers and set your worker URL
 * as WORKER_URL in case-status.html.
 *
 * Routes handled:
 *   GET  /api/sci/init        — fresh SCI session + CAPTCHA data
 *   POST /api/sci/captcha-img — proxy the CAPTCHA image
 *   POST /api/sci/search      — proxy the case-status form submission
 */

const SCI = 'https://www.sci.gov.in';
const UA  = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36';

// Restrict this to your domain in production, e.g. 'https://onecourt.in'
const ALLOWED_ORIGIN = '*';

const CORS = {
  'Access-Control-Allow-Origin':  ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    const url  = new URL(request.url);
    const path = url.pathname;

    try {
      if (path.endsWith('/init') && request.method === 'GET') {
        return handleInit();
      }
      if (path.endsWith('/captcha-img') && request.method === 'POST') {
        return handleCaptchaImg(request);
      }
      if (path.endsWith('/search') && request.method === 'POST') {
        return handleSearch(request);
      }
      return new Response('Not found', { status: 404 });
    } catch (e) {
      return jsonResp({ error: e.message }, 500);
    }
  },
};

// ── helpers ──────────────────────────────────────────────────────────────────

function jsonResp(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json' },
  });
}

function sciHeaders(extra = {}) {
  return {
    'User-Agent':      UA,
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    ...extra,
  };
}

function extractCookies(resp) {
  // Cloudflare Workers exposes getAll() for set-cookie
  let cookies = [];
  try { cookies = resp.headers.getAll('set-cookie'); } catch (_) {
    const h = resp.headers.get('set-cookie');
    if (h) cookies = [h];
  }
  return cookies.map(c => c.split(';')[0].trim()).filter(Boolean).join('; ');
}

function extractHiddenFields(html) {
  const fields = {};
  // Match both name-before-value and value-before-name attribute orders
  const re = /<input[^>]+type=["']hidden["'][^>]*>/gi;
  let m;
  while ((m = re.exec(html)) !== null) {
    const tag  = m[0];
    const name = (tag.match(/\bname=["']([^"']+)["']/)  || [])[1];
    const val  = (tag.match(/\bvalue=["']([^"']*)["']/) || [])[1] ?? '';
    if (name) fields[name] = val;
  }
  return fields;
}

// ── route handlers ────────────────────────────────────────────────────────────

async function handleInit() {
  const resp = await fetch(`${SCI}/case-status-case-no/`, {
    headers: sciHeaders({
      'Accept':  'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Referer': SCI + '/',
    }),
    redirect: 'follow',
  });

  if (!resp.ok) {
    return jsonResp({ error: `SCI returned HTTP ${resp.status}` }, 502);
  }

  const cookieStr    = extractCookies(resp);
  const html         = await resp.text();
  const hiddenFields = extractHiddenFields(html);
  const scid         = hiddenFields['scid'] || '';

  if (!scid) {
    return jsonResp({ error: 'Could not extract CAPTCHA session from SCI page.' }, 502);
  }

  return jsonResp({
    token:        btoa(cookieStr),   // base-64 encoded SCI cookies — opaque to the browser
    scid,
    hiddenFields,
  });
}

async function handleCaptchaImg(request) {
  const { token, scid } = await request.json();
  if (!token || !scid) {
    return new Response('Missing token or scid', { status: 400, headers: CORS });
  }

  const cookieStr = atob(token);
  const resp = await fetch(`${SCI}/?_siwp_captcha&id=${encodeURIComponent(scid)}`, {
    headers: sciHeaders({
      'Accept':  'image/webp,image/apng,image/*,*/*;q=0.8',
      'Referer': `${SCI}/case-status-case-no/`,
      'Cookie':  cookieStr,
    }),
  });

  if (!resp.ok) {
    return new Response('CAPTCHA fetch failed', { status: 502, headers: CORS });
  }

  const buf = await resp.arrayBuffer();
  return new Response(buf, {
    headers: {
      ...CORS,
      'Content-Type':  resp.headers.get('content-type') || 'image/png',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
    },
  });
}

async function handleSearch(request) {
  const { token, hiddenFields, caseType, caseNo, year, captchaAnswer } = await request.json();

  if (!token || !caseType || !caseNo || !captchaAnswer) {
    return jsonResp({ error: 'Missing required fields.' }, 400);
  }

  const cookieStr = atob(token);
  const form = new URLSearchParams();

  // Hidden WordPress/CAPTCHA fields first
  for (const [k, v] of Object.entries(hiddenFields || {})) {
    form.append(k, v);
  }
  form.append('case_type',          caseType);
  form.append('case_no',            caseNo);
  form.append('year',               year || new Date().getFullYear().toString());
  form.append('siwp_captcha_value', captchaAnswer);
  form.append('action',             'get_case_status_case_no');
  form.append('language',           'en');

  const resp = await fetch(`${SCI}/wp-admin/admin-ajax.php`, {
    method: 'POST',
    headers: sciHeaders({
      'Content-Type':    'application/x-www-form-urlencoded; charset=UTF-8',
      'Accept':          'application/json, text/javascript, */*; q=0.01',
      'Referer':         `${SCI}/case-status-case-no/`,
      'Origin':          SCI,
      'Cookie':          cookieStr,
      'X-Requested-With': 'XMLHttpRequest',
    }),
    body: form.toString(),
  });

  if (!resp.ok) {
    return jsonResp({ success: false, error: `SCI returned HTTP ${resp.status}` }, 502);
  }

  let result;
  try {
    result = await resp.json();
  } catch (_) {
    return jsonResp({ success: false, error: 'SCI returned non-JSON response.' }, 502);
  }

  return jsonResp(result);
}
