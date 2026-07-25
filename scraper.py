"""
NCLAT website scraper.

Fetches the NCLAT daily-cause-list page, discovers available dates and PDF URLs,
then invokes pdf_parser.fetch_and_parse for each PDF and stores results via database.

Court detection relies on COURT_PATTERNS below. If NCLAT renames a court in their
PDF filenames, add the new pattern (as a regex fragment) to the relevant entry.
"""

import re
import logging
from datetime import datetime, date
from typing import Optional, List, Dict
from urllib.parse import unquote
import requests
from bs4 import BeautifulSoup

from pdf_parser import fetch_and_parse
from database import upsert_cause_list, upsert_dates, log_scrape, init_db

logger = logging.getLogger(__name__)

NCLAT_URL = "https://nclat.nic.in/daily-cause-list"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NCLAT-CauseList-Bot/1.0)"
}

# ---------------------------------------------------------------------------
# Court detection: maps regex patterns found in PDF filenames → court_key
# ---------------------------------------------------------------------------
# Based on actual NCLAT filenames observed July 2026:
#   Causelist_ch_DD.MM.YYYY.pdf         → Chairperson
#   Causelist_II_DD.MM.YYYY.pdf         → Court II
#   Causelist_III_DD.MM.YYYY.pdf        → Court III
#   Causelist_IV_DD.MM.YYYY.pdf         → Court IV
#   Registrar Court_DD.MM.YYYY.pdf      → Registrar
#   DD.MM.YYYY.pdf  (bare date)         → Chennai (no other court uses this format)
#   Supp_Causelist_* / *Suppl*          → supplementary variant of the above
#
# ORDER MATTERS: IV must come before II/I to avoid partial matches.
# If NCLAT changes naming, update the patterns below.
COURT_PATTERNS: List[tuple] = [
    (r"_ch_|causelist_ch|supp_causelist_ch", "chairperson"),
    (r"_iv_|causelist_iv|supp_causelist_iv|\(iv\)", "court_iv"),
    (r"_iii_|causelist_iii|supp_causelist_iii|\(iii\)", "court_iii"),
    (r"_ii_|causelist_ii|supp_causelist_ii|\(ii\)", "court_ii"),
    (r"registrar", "registrar"),
    # Chennai: bare date files have no court code — matched as a final fallback
    # (handled separately in _detect_court, not via this list)
]

# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

# NCLAT uses DD.MM.YYYY in filenames (e.g. 29.07.2026).
# Also handle DD-MM-YYYY, DD_MM_YYYY, and YYYY-MM-DD just in case.
DATE_REGEXES = [
    re.compile(r"(\d{2})[_\-\.](\d{2})[_\-\.](\d{4})"),  # DD.MM.YYYY / DD-MM-YYYY / DD_MM_YYYY
    re.compile(r"(\d{4})[_\-](\d{2})[_\-](\d{2})"),       # YYYY-MM-DD
    re.compile(r"(\d{2})(\d{2})(\d{4})"),                  # DDMMYYYY (no separator)
]


def _parse_date_from_text(text: str) -> Optional[str]:
    """Extract a YYYY-MM-DD from a filename or link text."""
    text = text.lower()
    for pat in DATE_REGEXES:
        m = pat.search(text)
        if not m:
            continue
        g = m.groups()
        try:
            if len(g[0]) == 4:           # YYYY-MM-DD
                dt = date(int(g[0]), int(g[1]), int(g[2]))
            elif len(g[2]) == 4:         # DD-MM-YYYY or DDMMYYYY
                dt = date(int(g[2]), int(g[1]), int(g[0]))
            else:
                continue
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _is_bare_date_file(filename: str) -> bool:
    """True for files like '27.07.2026.pdf' or '23.07.2026 Suppl..pdf' — no court code."""
    # Strip URL encoding, extension, version suffix, and supplementary markers
    name = re.sub(r"%[0-9a-f]{2}", " ", filename.lower())  # URL-decode roughly
    name = re.sub(r"\.pdf$", "", name)
    name = re.sub(r"[\s_]+(suppl?\.?|supplementary)[\s\(\)ivx]*$", "", name).strip()
    name = re.sub(r"_\d+$", "", name).strip()  # strip _0, _1 version suffixes
    # What's left should be just a date (DD.MM.YYYY or similar) for Chennai files
    return bool(re.fullmatch(r"\d{2}[.\-_]\d{2}[.\-_]\d{4}", name))


def _detect_court(filename: str) -> Optional[str]:
    fn = unquote(filename).lower()  # decode %28II%29 → (ii) before matching
    for pattern, key in COURT_PATTERNS:
        if re.search(pattern, fn):
            return key
    # Fallback: bare date-only filename → Chennai Bench
    if _is_bare_date_file(filename):
        return "chennai"
    return None


def _is_supplementary(filename: str) -> bool:
    return bool(re.search(r"suppl?\.?|supp_|supplementary", filename.lower()))


# ---------------------------------------------------------------------------
# Main scraping logic
# ---------------------------------------------------------------------------

def _build_absolute_url(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    return "https://nclat.nic.in" + (href if href.startswith("/") else "/" + href)


def discover_pdfs() -> dict:
    """
    Fetch the NCLAT cause list page and return a dict:
      {
        'dates': [{'date': 'YYYY-MM-DD', 'label': '...'}, ...],
        'pdfs':  [{'url': ..., 'date': ..., 'court_key': ..., 'list_type': ...}, ...]
      }
    """
    logger.info("Fetching NCLAT page: %s", NCLAT_URL)
    resp = requests.get(NCLAT_URL, headers=REQUEST_HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    today = date.today().isoformat()
    found_dates = set()
    pdfs = []

    for link in soup.find_all("a", href=True):
        href: str = link["href"]
        text: str = link.get_text(" ", strip=True)

        if not href.lower().endswith(".pdf"):
            continue

        filename = href.split("/")[-1]
        link_date = _parse_date_from_text(filename) or _parse_date_from_text(text)

        if not link_date:
            continue

        # Only expose today + future dates (per spec: "Today and Next Available Dates")
        if link_date < today:
            continue

        court_key = _detect_court(filename)
        if not court_key:
            logger.debug("Could not detect court from filename: %s", filename)
            continue

        list_type = "supplementary" if _is_supplementary(filename) else "main"
        abs_url = _build_absolute_url(href)

        found_dates.add(link_date)
        pdfs.append({
            "url": abs_url,
            "date": link_date,
            "court_key": court_key,
            "list_type": list_type,
        })

    # Build date label list
    sorted_dates = sorted(found_dates)
    date_entries = []
    future_count = 0
    for d in sorted_dates:
        if d == today:
            label = "Today"
        elif future_count == 0:
            label = "Tomorrow"
            future_count += 1
        else:
            label = ""   # frontend will just show the formatted date
            future_count += 1
        date_entries.append({"date": d, "label": label})

    logger.info("Found %d dates, %d PDFs", len(date_entries), len(pdfs))
    return {"dates": date_entries, "pdfs": pdfs}


def run_scrape() -> dict:
    """
    Full scrape cycle: discover PDFs, parse each, persist to DB.
    Returns a summary dict.
    """
    started = datetime.utcnow().isoformat()
    init_db()
    summary = {"started_at": started, "dates": [], "processed": 0, "errors": 0}

    try:
        discovery = discover_pdfs()
        upsert_dates(discovery["dates"])
        summary["dates"] = [d["date"] for d in discovery["dates"]]

        for pdf_info in discovery["pdfs"]:
            try:
                items = fetch_and_parse(pdf_info["url"])
                upsert_cause_list(
                    date=pdf_info["date"],
                    court_key=pdf_info["court_key"],
                    list_type=pdf_info["list_type"],
                    pdf_url=pdf_info["url"],
                    items=items,
                )
                summary["processed"] += 1
            except Exception as exc:
                logger.error("Failed to process PDF %s: %s", pdf_info["url"], exc)
                summary["errors"] += 1

        log_scrape(started, "success",
                   f"processed={summary['processed']} errors={summary['errors']}")
    except Exception as exc:
        logger.exception("Scrape failed: %s", exc)
        log_scrape(started, "error", str(exc))
        summary["error"] = str(exc)

    return summary
