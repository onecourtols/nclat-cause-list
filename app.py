"""
Flask application entry-point for NCLAT Cause List Viewer.

Run:
    cd nclat
    pip install -r requirements.txt
    python app.py

Or with gunicorn (production):
    gunicorn -w 2 -b 0.0.0.0:5001 app:app
"""

import logging
import os
import time
import uuid
from datetime import datetime

import requests as _http
from bs4 import BeautifulSoup
from flask import Flask, jsonify, make_response, render_template, request

from database import init_db, get_available_dates, get_cause_list, get_last_scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")

# ---------------------------------------------------------------------------
# Scheduler — started once at import time (not inside each worker)
# ---------------------------------------------------------------------------
_scheduler = None

def _init_scheduler():
    global _scheduler
    if _scheduler is None:
        from scheduler import start_scheduler
        _scheduler = start_scheduler()

# ---------------------------------------------------------------------------
# Court metadata (UI labels and order)
# ---------------------------------------------------------------------------
COURTS = [
    {"key": "chairperson", "label": "Chairperson Court",  "city": "Delhi"},
    {"key": "court_ii",    "label": "Court II",           "city": "Delhi"},
    {"key": "court_iii",   "label": "Court III",          "city": "Delhi"},
    {"key": "court_iv",    "label": "Court IV",           "city": "Delhi"},
    {"key": "chennai",     "label": "Chennai Bench",      "city": "Chennai"},
    {"key": "registrar",   "label": "Registrar Court",    "city": "Delhi"},
]

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", courts=COURTS)


@app.route("/api/dates")
def api_dates():
    """Return available dates from the DB."""
    dates = get_available_dates()
    return jsonify({"dates": dates})


@app.route("/api/cause-list")
def api_cause_list():
    """
    Query params:
      date       YYYY-MM-DD (required)
      court_key  one of the court keys (required)
    Returns:
      { supplementary: [...], main: [...], pdf_urls: {...} }
    """
    date_param = request.args.get("date", "").strip()
    court_key  = request.args.get("court_key", "").strip()

    if not date_param or not court_key:
        return jsonify({"error": "date and court_key are required"}), 400

    valid_keys = {c["key"] for c in COURTS}
    if court_key not in valid_keys:
        return jsonify({"error": f"Unknown court_key: {court_key}"}), 400

    data = get_cause_list(date_param, court_key)
    return jsonify(data)


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """
    Manually trigger a scrape (useful for testing or immediate refresh).
    This blocks until the scrape completes — use only from trusted clients.
    """
    from scraper import run_scrape
    summary = run_scrape()
    return jsonify(summary)


@app.route("/api/status")
def api_status():
    last = get_last_scrape()
    return jsonify({
        "last_scrape": last,
        "server_time": datetime.utcnow().isoformat() + "Z",
        "courts": COURTS,
    })


# ---------------------------------------------------------------------------
# SCI Case Status proxy
# ---------------------------------------------------------------------------

_SCI_SESSIONS: dict = {}
_SCI_INIT_URL = "https://www.sci.gov.in/case-status-case-no/"
_SCI_AJAX_URL = "https://www.sci.gov.in/wp-admin/admin-ajax.php"
_SCI_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_SCI_SESSION_TTL = 300  # 5 minutes


def _sci_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def _sci_purge_old():
    cutoff = time.time() - _SCI_SESSION_TTL
    for k in [k for k, v in _SCI_SESSIONS.items() if v.get("ts", 0) < cutoff]:
        _SCI_SESSIONS.pop(k, None)


@app.route("/api/sci/init", methods=["GET", "OPTIONS"])
def sci_init():
    if request.method == "OPTIONS":
        return _sci_cors(make_response("", 204))
    try:
        _sci_purge_old()
        sess = _http.Session()
        resp = sess.get(
            _SCI_INIT_URL,
            headers={"User-Agent": _SCI_UA, "Accept": "text/html"},
            timeout=15,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        form = soup.find("form", id="sciapi-services-case-status-case-no")
        if not form:
            return _sci_cors(jsonify({"error": "SCI form not found on page"})), 500

        hidden = {}
        scid = ""
        for inp in form.find_all("input"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if not name:
                continue
            if name == "scid":
                scid = value
            hidden[name] = value

        token = str(uuid.uuid4())
        _SCI_SESSIONS[token] = {
            "cookies": dict(sess.cookies),
            "hidden": hidden,
            "scid": scid,
            "captcha_url": f"https://www.sci.gov.in/?_siwp_captcha&id={scid}" if scid else "",
            "ts": time.time(),
        }

        return _sci_cors(jsonify({"token": token, "scid": scid, "hiddenFields": hidden}))
    except Exception as e:
        logger.exception("sci_init error")
        return _sci_cors(jsonify({"error": str(e)})), 500


@app.route("/api/sci/captcha-img", methods=["POST", "OPTIONS"])
def sci_captcha_img():
    if request.method == "OPTIONS":
        return _sci_cors(make_response("", 204))
    try:
        data = request.json or {}
        token = data.get("token", "")
        sd = _SCI_SESSIONS.get(token)
        if not sd:
            return _sci_cors(jsonify({"error": "Session not found or expired"})), 404

        img_resp = _http.get(
            sd["captcha_url"],
            cookies=sd["cookies"],
            headers={"User-Agent": _SCI_UA, "Referer": _SCI_INIT_URL},
            timeout=10,
        )
        img_resp.raise_for_status()

        response = make_response(img_resp.content)
        response.headers["Content-Type"] = img_resp.headers.get("Content-Type", "image/png")
        return _sci_cors(response)
    except Exception as e:
        logger.exception("sci_captcha_img error")
        return _sci_cors(jsonify({"error": str(e)})), 500


@app.route("/api/sci/search", methods=["POST", "OPTIONS"])
def sci_search():
    if request.method == "OPTIONS":
        return _sci_cors(make_response("", 204))
    try:
        data = request.json or {}
        token = data.get("token", "")
        sd = _SCI_SESSIONS.get(token)
        if not sd:
            return _sci_cors(jsonify({
                "success": False,
                "data": {"message": "Session expired — please refresh the CAPTCHA."},
            }))

        form_data = dict(sd["hidden"])
        form_data.update(data.get("hiddenFields", {}))
        form_data["action"] = "get_case_status_case_no"
        form_data["es_ajax_request"] = "1"
        form_data["case_type"] = str(data.get("caseType", ""))
        form_data["case_no"] = str(data.get("caseNo", ""))
        form_data["year"] = str(data.get("year", ""))
        form_data["siwp_captcha_value"] = str(data.get("captchaAnswer", ""))
        form_data["submit"] = "Search"

        search_resp = _http.post(
            _SCI_AJAX_URL,
            data=form_data,
            cookies=sd["cookies"],
            headers={
                "User-Agent": _SCI_UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": _SCI_INIT_URL,
            },
            timeout=20,
        )
        search_resp.raise_for_status()

        _SCI_SESSIONS.pop(token, None)
        return _sci_cors(jsonify(search_resp.json()))
    except Exception as e:
        logger.exception("sci_search error")
        return _sci_cors(jsonify({"success": False, "data": {"message": str(e)}})), 500


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    _init_scheduler()
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info("Starting NCLAT Cause List server on port %d", port)
    # use_reloader=False is required when APScheduler runs in the same process
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
