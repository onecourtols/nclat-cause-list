"""
Tests for pdf_parser.py — especially the Chairperson Court split-table path.

The Chairperson Court PDF page 1 uses a split layout:
  left table  → S.No. | Case No.
  right table → Parties | Counsel for Appellant | Counsel for Respondent

pdfplumber sometimes injects a spurious 3rd empty column into the left table
(from the page gutter), which previously caused _is_left_only_table() to
return False and skip the merge — leaving items with only sno + case_no and
no parties or counsel.

Run:
    pip install pytest
    pytest tests/test_pdf_parser.py -v
"""
import pytest
from unittest.mock import MagicMock, patch

from pdf_parser import (
    _is_left_only_table,
    _is_right_only_table,
    _parse_table,
    _parse_right_table_entries,
    _merge_split_pair,
    fetch_and_parse,
)


# ── shared table fixtures ─────────────────────────────────────────────────────

# Normal 2-column left table
LEFT_2COL = [
    ["S. No.", "Case No."],
    ["1.", "Comp. App. (AT) (Ins) No. 100/2026"],
    ["2.", "Comp. App. (AT) (Ins) No. 200/2026"],
]

# THE REGRESSION: pdfplumber injects a spurious 3rd None/"" column.
# Old code: ncols > 2 → _is_left_only_table() returns False → merge skipped.
# Fixed code: non-empty columns counted → still returns True → merge fires.
LEFT_SPURIOUS_EMPTY_COL = [
    ["S. No.", "Case No.", None],
    ["1.", "Comp. App. (AT) (Ins) No. 100/2026", None],
    ["2.", "Comp. App. (AT) (Ins) No. 200/2026", ""],
]

# Right table with a header row.
# Col 0 is always "" in every row — _parse_right_table_entries uses col0=="" as
# the case-boundary marker.  Column headers and actual data live in cols 1+.
RIGHT_WITH_HEADER = [
    ["", "Name of the Parties", "Counsel for Appellant", "Counsel for Respondent"],
    ["", "Alpha Corp Vs. Beta Ltd.", "Mr. A Sharma", "Mr. B Singh"],
    ["", "Gamma Ltd. Vs. Delta Co.", "Ms. C Nair", "Mr. D Kumar"],
]

# Headerless right table — used only to verify _is_right_only_table detection.
# (The headerless positional fallback assigns "parties" to col 0 which is always
# empty "", so it cannot produce real merge records — kept for detection tests only.)
RIGHT_HEADERLESS = [
    ["", "Alpha Corp Vs. Beta Ltd.", "Mr. A Sharma", "Mr. B Singh"],
    ["", "Gamma Ltd. Vs. Delta Co.", "Ms. C Nair", "Mr. D Kumar"],
]

# Full-width table used on pages 2+ (sno | case_no | parties | counsel x2)
FULL_TABLE_P2 = [
    ["S. No.", "Case No.", "Name of the Parties", "Counsel for Appellant", "Counsel for Respondent"],
    ["1.", "Comp. App. (AT) (Ins) No. 300/2026", "Delta Vs. Epsilon Ltd.", "Mr. E Rao", "Mr. F Iyer"],
    ["2.", "Comp. App. (AT) (Ins) No. 400/2026", "Zeta Corp Vs. Eta Inc.", "Ms. G Patel", "Mr. H Khan"],
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_mock_pdf(pages_tables):
    """Build a mock pdfplumber PDF context manager from a list-of-page-tables."""
    mock_pages = []
    for tables in pages_tables:
        p = MagicMock()
        p.extract_tables.return_value = tables
        mock_pages.append(p)
    pdf_cm = MagicMock()
    pdf_cm.__enter__ = lambda s: pdf_cm
    pdf_cm.__exit__ = MagicMock(return_value=False)
    pdf_cm.pages = mock_pages
    return pdf_cm


def _mock_response(content=b"FAKEPDF"):
    r = MagicMock()
    r.content = content
    r.raise_for_status = MagicMock()
    return r


# ── _is_left_only_table ───────────────────────────────────────────────────────

class TestIsLeftOnlyTable:
    def test_normal_2col(self):
        assert _is_left_only_table(LEFT_2COL) is True

    def test_spurious_empty_third_col(self):
        # Regression: a spurious None/"" 3rd column must NOT block detection.
        assert _is_left_only_table(LEFT_SPURIOUS_EMPTY_COL) is True

    def test_3col_with_real_content(self):
        table = [
            ["S. No.", "Case No.", "Parties"],
            ["1.", "Comp. App. No. 1/2026", "Alpha Corp"],
        ]
        assert _is_left_only_table(table) is False

    def test_no_sno_in_data(self):
        table = [["Name", "Value"], ["Alpha Corp", "100"]]
        assert _is_left_only_table(table) is False

    def test_empty_table(self):
        assert _is_left_only_table([]) is False

    def test_right_table_not_classified_as_left(self):
        assert _is_left_only_table(RIGHT_WITH_HEADER) is False


# ── _is_right_only_table ─────────────────────────────────────────────────────

class TestIsRightOnlyTable:
    def test_parties_in_header(self):
        assert _is_right_only_table(RIGHT_WITH_HEADER) is True

    def test_counsel_in_header(self):
        table = [["Counsel for Appellant", "Counsel for Respondent"], ["Mr. A", "Mr. B"]]
        assert _is_right_only_table(table) is True

    def test_appellant_keyword_in_header(self):
        table = [["Name of Appellant", "Counsel"], ["Alpha Corp", "Mr. A"]]
        assert _is_right_only_table(table) is True

    def test_headerless_3col_no_sno(self):
        assert _is_right_only_table(RIGHT_HEADERLESS) is True

    def test_2col_no_keywords_not_right(self):
        table = [["Alpha Corp", "100"], ["Beta Ltd.", "200"]]
        assert _is_right_only_table(table) is False

    def test_left_table_not_right(self):
        assert _is_right_only_table(LEFT_2COL) is False

    def test_empty_table(self):
        assert _is_right_only_table([]) is False


# ── _parse_table ──────────────────────────────────────────────────────────────

class TestParseTable:
    def test_standard_headed_table(self):
        items = _parse_table(FULL_TABLE_P2)
        assert len(items) == 2
        assert items[0]["case_no"] == "Comp. App. (AT) (Ins) No. 300/2026"
        assert items[0]["parties"] == "Delta Vs. Epsilon Ltd."
        assert items[0]["counsel_appellant"] == "Mr. E Rao"
        assert items[0]["counsel_respondent"] == "Mr. F Iyer"
        assert items[0]["sno"] == "1."

    def test_continuation_rows_merged(self):
        table = [
            ["S. No.", "Case No.", "Name of the Parties", "Counsel for Appellant", "Counsel for Respondent"],
            ["1.", "Comp. App. No. 100/2026", "Alpha Corp", "Mr. A", "Mr. B"],
            [None, None, "Vs. Beta Ltd.", None, None],  # continuation
        ]
        items = _parse_table(table)
        assert len(items) == 1
        assert items[0]["parties"] == "Alpha Corp Vs. Beta Ltd."

    def test_empty_table_returns_empty(self):
        assert _parse_table([]) == []

    def test_header_only_table_returns_empty(self):
        assert _parse_table([["S.No.", "Case No."]]) == []


# ── _merge_split_pair ─────────────────────────────────────────────────────────

class TestMergeSplitPair:
    def test_full_merge(self):
        items = _merge_split_pair(LEFT_2COL, RIGHT_WITH_HEADER)
        assert len(items) == 2
        assert items[0]["case_no"] == "Comp. App. (AT) (Ins) No. 100/2026"
        assert items[0]["parties"] == "Alpha Corp Vs. Beta Ltd."
        assert items[0]["counsel_appellant"] == "Mr. A Sharma"
        assert items[0]["counsel_respondent"] == "Mr. B Singh"

    def test_merge_with_spurious_empty_col_on_left(self):
        # Regression: merge must succeed even with a spurious 3rd empty column.
        items = _merge_split_pair(LEFT_SPURIOUS_EMPTY_COL, RIGHT_WITH_HEADER)
        assert len(items) == 2
        assert items[0]["parties"] == "Alpha Corp Vs. Beta Ltd."
        assert items[1]["parties"] == "Gamma Ltd. Vs. Delta Co."

    def test_fewer_right_entries_than_left(self):
        # Only the first right entry exists; second left item gets no right-side data.
        right_one = [
            ["", "Name of the Parties", "Counsel for Appellant", "Counsel for Respondent"],
            ["", "Alpha Corp Vs. Beta Ltd.", "Mr. A Sharma", "Mr. B Singh"],
        ]
        items = _merge_split_pair(LEFT_2COL, right_one)
        assert items[0]["parties"] == "Alpha Corp Vs. Beta Ltd."
        assert not items[1].get("parties")


# ── fetch_and_parse integration ───────────────────────────────────────────────

class TestFetchAndParseSplitTable:

    @patch("pdf_parser.pdfplumber")
    @patch("pdf_parser.requests")
    def test_split_table_merges_correctly(self, mock_req, mock_pdf):
        mock_req.get.return_value = _mock_response()
        mock_pdf.open.return_value = _make_mock_pdf([
            [LEFT_2COL, RIGHT_WITH_HEADER],
        ])
        items = fetch_and_parse("https://example.com/fake.pdf")
        assert len(items) == 2
        assert items[0]["parties"] == "Alpha Corp Vs. Beta Ltd."
        assert items[0]["case_no"] == "Comp. App. (AT) (Ins) No. 100/2026"

    @patch("pdf_parser.pdfplumber")
    @patch("pdf_parser.requests")
    def test_spurious_empty_col_regression(self, mock_req, mock_pdf):
        """
        REGRESSION: spurious 3rd empty column on left table must not cause
        the split-table merge to be skipped, leaving items with no parties/counsel.
        """
        mock_req.get.return_value = _mock_response()
        mock_pdf.open.return_value = _make_mock_pdf([
            [LEFT_SPURIOUS_EMPTY_COL, RIGHT_WITH_HEADER],
        ])
        items = fetch_and_parse("https://example.com/fake.pdf")
        assert len(items) == 2, (
            "Both items must be present — if the merge was skipped only the "
            "left-table sno+case_no would have been stored"
        )
        for item in items:
            assert "parties" in item, "parties must be present after merge"
            assert item["parties"], "parties must be non-empty after merge"

    @patch("pdf_parser.pdfplumber")
    @patch("pdf_parser.requests")
    def test_non_split_page_parsed_normally(self, mock_req, mock_pdf):
        mock_req.get.return_value = _mock_response()
        mock_pdf.open.return_value = _make_mock_pdf([
            [FULL_TABLE_P2],
        ])
        items = fetch_and_parse("https://example.com/fake.pdf")
        assert len(items) == 2
        assert items[0]["sno"] == "1."
        assert items[1]["sno"] == "2."

    @patch("pdf_parser.pdfplumber")
    @patch("pdf_parser.requests")
    def test_multipage_split_then_full(self, mock_req, mock_pdf):
        """Page 1 uses split layout; page 2 uses full-width layout."""
        mock_req.get.return_value = _mock_response()
        mock_pdf.open.return_value = _make_mock_pdf([
            [LEFT_2COL, RIGHT_WITH_HEADER],  # page 1: split
            [FULL_TABLE_P2],                  # page 2: full-width
        ])
        items = fetch_and_parse("https://example.com/fake.pdf")
        # 2 from page 1 + 2 from page 2 = 4 distinct items
        assert len(items) == 4

    @patch("pdf_parser.pdfplumber")
    @patch("pdf_parser.requests")
    def test_deduplication(self, mock_req, mock_pdf):
        """Identical (case_no, parties) pairs across pages must be deduplicated."""
        mock_req.get.return_value = _mock_response()
        mock_pdf.open.return_value = _make_mock_pdf([
            [FULL_TABLE_P2],
            [FULL_TABLE_P2],  # exact duplicate
        ])
        items = fetch_and_parse("https://example.com/fake.pdf")
        assert len(items) == 2  # deduplicated

    @patch("pdf_parser.pdfplumber")
    @patch("pdf_parser.requests")
    def test_page_parse_error_skipped(self, mock_req, mock_pdf):
        """A bad page must be skipped without aborting the whole parse."""
        bad_page = MagicMock()
        bad_page.extract_tables.side_effect = Exception("corrupt page")
        good_page = MagicMock()
        good_page.extract_tables.return_value = [FULL_TABLE_P2]

        pdf_cm = MagicMock()
        pdf_cm.__enter__ = lambda s: pdf_cm
        pdf_cm.__exit__ = MagicMock(return_value=False)
        pdf_cm.pages = [bad_page, good_page]
        mock_pdf.open.return_value = pdf_cm
        mock_req.get.return_value = _mock_response()

        items = fetch_and_parse("https://example.com/fake.pdf")
        assert len(items) == 2  # from the good page only
