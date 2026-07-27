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
from datetime import datetime

from flask import Flask, jsonify, render_template, request

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
    """Return available dates from the DB with labels computed at request time."""
    from datetime import date as _date
    today = _date.today().isoformat()
    dates = get_available_dates()
    # Recompute labels fresh so Today/Tomorrow stay accurate regardless of when
    # the scraper last ran.
    future_count = 0
    for entry in dates:
        d = entry["date"]
        if d < today:
            entry["label"] = ""          # past — hide from UI
        elif d == today:
            entry["label"] = "Today"
        elif future_count == 0:
            entry["label"] = "Tomorrow"
            future_count += 1
        else:
            entry["label"] = ""
            future_count += 1
    # Only expose today + future dates
    dates = [e for e in dates if e["date"] >= today]
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


@app.route("/api/display-board")
def api_display_board():
    """Proxy NCLAT live display board to avoid CORS."""
    import requests as req
    try:
        r = req.get(
            "https://nclat.nic.in/display-board/user-display-board/get-list",
            timeout=8,
            headers={"Referer": "https://nclat.nic.in/display-board/"},
        )
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as exc:
        logger.warning("Display board fetch failed: %s", exc)
        return jsonify({"status": False, "error": str(exc)}), 502


@app.route("/api/status")
def api_status():
    last = get_last_scrape()
    return jsonify({
        "last_scrape": last,
        "server_time": datetime.utcnow().isoformat() + "Z",
        "courts": COURTS,
    })


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    _init_scheduler()

    # If DB is empty (e.g. after a fresh deploy), kick off a scrape immediately
    if not get_available_dates():
        import threading
        from scraper import run_scrape
        logger.info("DB empty on startup — running initial scrape in background")
        threading.Thread(target=run_scrape, daemon=True).start()

    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info("Starting NCLAT Cause List server on port %d", port)
    # use_reloader=False is required when APScheduler runs in the same process
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
