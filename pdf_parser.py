"""
PDF parser for NCLAT Daily Cause List PDFs.

NCLAT PDFs have a specific quirk: pdfplumber often splits one logical case row
across multiple table rows (because cell text wraps). This parser merges those
continuation rows back into single records.

The actual column structure observed in NCLAT PDFs (July 2026):
  S. No. | Case No. | Name of the parties | Name of the parties |
  Counsel for Appellants | Counsel for Appellants | Counsel for Respondents

  ↑ cols 2+3 are both "parties"; cols 4+5 are both "counsel_appellant"
  (PDF layout artifact — deduplicated during parsing)

HOW TO ADJUST IF NCLAT CHANGES THEIR FORMAT:
  1. Run the diagnostic block at the bottom of this file on a new PDF.
  2. Update COLUMN_ALIASES to map new header text → canonical keys.
  3. If the column count changes, check _merge_data_rows — it relies on
     col[0] (S. No.) being present to detect new-case boundaries.
"""

import io
import re
import logging
from typing import List, Dict, Optional
import requests
import pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column header normalisation
# Maps any variant found in NCLAT PDFs → canonical key.
# Add entries here when NCLAT renames a column.
# ---------------------------------------------------------------------------
COLUMN_ALIASES: Dict[str, str] = {
    # S. No.
    "s. no.": "sno", "s.no.": "sno", "sno": "sno",
    "sl. no.": "sno", "sl.no.": "sno", "s no": "sno",
    "item no.": "sno", "item no": "sno", "sr. no.": "sno",

    # Case number
    "case no.": "case_no", "case no": "case_no",
    "case number": "case_no", "comp. petition no.": "case_no",

    # Parties — NCLAT uses "Name of the parties" (note "the")
    "name of the parties": "parties",
    "name of parties": "parties",
    "names of parties": "parties",
    "title of case": "parties",
    "parties": "parties",

    # Appellant counsel
    "counsel for appellants": "counsel_appellant",
    "counsel for appellant": "counsel_appellant",
    "counsel for appellant(s)": "counsel_appellant",
    "advocate for appellant": "counsel_appellant",
    "appellant's counsel": "counsel_appellant",

    # Respondent counsel
    "counsel for respondents": "counsel_respondent",
    "counsel for respondent": "counsel_respondent",
    "counsel for respondent(s)": "counsel_respondent",
    "advocate for respondent": "counsel_respondent",
    "respondent's counsel": "counsel_respondent",

    # Optional extras
    "remarks": "remarks",
    "coram": "coram",
    "bench": "coram",
}

# Serial number cell: "1.", "2.", "10", etc.
_SN_RE = re.compile(r"^\d+\.?$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(val) -> str:
    """Strip and collapse whitespace in a cell value."""
    return re.sub(r"\s+", " ", str(val or "")).strip()


def _normalise_header(cell: str) -> str:
    return re.sub(r"\s+", " ", str(cell or "").strip().lower())


def _map_header(cell: str) -> str:
    return COLUMN_ALIASES.get(_normalise_header(cell), _normalise_header(cell))


def _is_sn(cell) -> bool:
    return bool(_SN_RE.match(_clean(cell)))


def _is_header_row(row: list) -> bool:
    return any(re.search(r"s\.?\s*no\.?|case\s*no", str(c or "").lower()) for c in row)


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def _parse_table(raw_table: List[List]) -> List[Dict]:
    """
    Parse a pdfplumber table (list of rows) into a list of case-item dicts.

    Handles:
    - Split header rows (e.g. "Counsel for" on one row, "Appellants" on next)
    - Continuation data rows (cells split across multiple rows because of wrapping)
    - Duplicate columns (pdfplumber sometimes detects the same PDF column twice)
    """
    if not raw_table or len(raw_table) < 2:
        return []

    num_cols = max(len(r) for r in raw_table)

    # ── Step 1: separate header rows from data rows ──────────────────────────
    header_rows: List[List] = []
    data_rows: List[List] = []
    found_data = False

    for row in raw_table:
        if found_data:
            data_rows.append(row)
            continue
        if _is_sn(row[0] if row else ""):
            found_data = True
            data_rows.append(row)
        else:
            header_rows.append(row)

    if not header_rows:
        return []

    # ── Step 2: merge split header rows into one combined header ─────────────
    merged_hdr = [""] * num_cols
    for row in header_rows:
        for i, c in enumerate(row):
            if i >= num_cols:
                break
            val = _clean(c)
            if val:
                merged_hdr[i] = (merged_hdr[i] + " " + val).strip() if merged_hdr[i] else val

    col_keys = [_map_header(h) for h in merged_hdr]

    # ── Step 3: merge continuation data rows ─────────────────────────────────
    # A row is a "continuation" when col[0] (S. No.) is empty.
    merged_data: List[List[str]] = []
    current: Optional[List[str]] = None

    for row in data_rows:
        padded = [_clean(row[i]) if i < len(row) else "" for i in range(num_cols)]
        first = padded[0]

        if _is_sn(first):
            # New case — save previous
            if current is not None:
                merged_data.append(current)
            current = padded
        elif current is not None:
            # Continuation — append non-empty cells to their column
            for i, val in enumerate(padded):
                if val and i < len(current):
                    current[i] = (current[i] + " " + val).strip() if current[i] else val
        # else: section title row before first S. No. — skip

    if current is not None:
        merged_data.append(current)

    # ── Step 4: build records, deduplicating columns with the same key ───────
    items: List[Dict] = []

    for cells in merged_data:
        record: Dict[str, str] = {}

        for i, key in enumerate(col_keys):
            if not key or i >= len(cells):
                continue
            val = cells[i]
            if not val:
                continue

            if key in record:
                # Same canonical key appears twice (PDF layout artifact).
                # Keep unique content only — skip if it's already there.
                existing = record[key]
                if val and val not in existing:
                    record[key] = (existing + " " + val).strip()
            else:
                record[key] = val

        # Require at least a case number or party name to be a valid record
        if not record.get("case_no") and not record.get("parties"):
            continue

        items.append(record)

    return items


# ---------------------------------------------------------------------------
# PDF fetching + multi-page extraction
# ---------------------------------------------------------------------------

def fetch_and_parse(pdf_url: str, timeout: int = 30) -> List[Dict]:
    """
    Download a PDF from *pdf_url* and return a list of case-item dicts.

    Each dict has at minimum: case_no (or parties).
    Optional fields: sno, counsel_appellant, counsel_respondent, remarks, coram.

    Raises requests.HTTPError on bad HTTP status.
    """
    logger.info("Fetching PDF: %s", pdf_url)
    resp = requests.get(
        pdf_url, timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (NCLAT-CauseList-Bot/1.0)"}
    )
    resp.raise_for_status()

    all_items: List[Dict] = []

    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                tables = page.extract_tables()
                for raw_table in tables:
                    items = _parse_table(raw_table)
                    all_items.extend(items)
            except Exception as exc:
                logger.warning("Page %d parse error (%s): %s", page_num, pdf_url, exc)

    # De-duplicate by (case_no, parties) in case the same item spans pages
    seen: set = set()
    deduped: List[Dict] = []
    for item in all_items:
        key = (item.get("case_no", ""), item.get("parties", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    logger.info("Parsed %d items from %s", len(deduped), pdf_url)
    return deduped
