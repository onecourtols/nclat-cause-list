"""Seed mock cause list data for UI testing. Run once: python3 seed_mock.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, upsert_cause_list, upsert_dates

TODAY = "2026-07-25"
TOMORROW = "2026-07-26"

init_db()

upsert_dates([
    {"date": TODAY,    "label": "Today"},
    {"date": TOMORROW, "label": "Tomorrow"},
])

# ── Chairperson Court ─────────────────────────────────────────────────────────
upsert_cause_list(TODAY, "chairperson", "supplementary", "https://nclat.nic.in/dummy-supp.pdf", [
    {"sno": "1", "case_no": "CA/12/2024", "parties": "Reliance Industries Ltd. vs. SEBI",
     "counsel_appellant": "Mr. Harish Salve, Mr. Rohan Mehta",
     "counsel_respondent": "Mr. Mukul Rohatgi, Ms. Priya Shah"},
    {"sno": "2", "case_no": "CA/45/2024", "parties": "Adani Ports SEZ Ltd. vs. Union of India",
     "counsel_appellant": "Mr. Arvind Datar",
     "counsel_respondent": "Mr. P.S. Narasimha, ASG"},
])

upsert_cause_list(TODAY, "chairperson", "main", "https://nclat.nic.in/dummy-main.pdf", [
    {"sno": "1", "case_no": "MA/101/2024", "parties": "Jet Airways (India) Ltd. (In Liquidation) vs. State Bank of India",
     "counsel_appellant": "Mr. Neeraj Kishan Kaul", "counsel_respondent": "Mr. Kapil Sibal"},
    {"sno": "2", "case_no": "MA/102/2024", "parties": "Future Retail Ltd. vs. Amazon.com NV Investment Holdings LLC",
     "counsel_appellant": "Mr. Abhishek Manu Singhvi", "counsel_respondent": "Mr. Darius Khambata"},
    {"sno": "3", "case_no": "CP/88/2025", "parties": "Byju's (Think & Learn Pvt. Ltd.) vs. BCCI",
     "counsel_appellant": "Mr. C.A. Sundaram", "counsel_respondent": "Mr. Gopal Subramanium"},
    {"sno": "4", "case_no": "CP/201/2025", "parties": "Go First Airlines vs. ED & Anr.",
     "counsel_appellant": "Mr. Siddharth Luthra", "counsel_respondent": "Mr. Vikramjit Banerjee, ASG"},
    {"sno": "5", "case_no": "TA/77/2024", "parties": "Videocon Industries Ltd. vs. SBI & Ors.",
     "counsel_appellant": "Mr. Shyam Divan", "counsel_respondent": "Mr. Rakesh Dwivedi"},
])

# ── Court II ──────────────────────────────────────────────────────────────────
upsert_cause_list(TODAY, "court_ii", "main", "https://nclat.nic.in/dummy-c2.pdf", [
    {"sno": "1", "case_no": "IB/301/2025", "parties": "DHFL vs. Piramal Capital & Housing Finance",
     "counsel_appellant": "Mr. Iqbal Chagla", "counsel_respondent": "Mr. Mihir Thakur"},
    {"sno": "2", "case_no": "IB/302/2025", "parties": "Jaypee Infratech Ltd. vs. IDBI Bank",
     "counsel_appellant": "Dr. Abhishek Manu Singhvi", "counsel_respondent": "Mr. Pallav Shishodia"},
])

# ── Court III ─────────────────────────────────────────────────────────────────
upsert_cause_list(TODAY, "court_iii", "main", "https://nclat.nic.in/dummy-c3.pdf", [
    {"sno": "1", "case_no": "CA/500/2025", "parties": "Essar Steel India Ltd. vs. Standard Chartered Bank",
     "counsel_appellant": "Mr. Fali S. Nariman", "counsel_respondent": "Mr. Arun Jaitley"},
])

# ── Chennai Bench ─────────────────────────────────────────────────────────────
upsert_cause_list(TODAY, "chennai", "supplementary", "https://nclat.nic.in/dummy-chennai-supp.pdf", [
    {"sno": "1", "case_no": "CP/11/CH/2025", "parties": "Sathavahana Ispat Ltd. vs. ARCIL",
     "counsel_appellant": "Mr. P.H. Arvind Pandian", "counsel_respondent": "Mr. C. Natarajan"},
])

upsert_cause_list(TODAY, "chennai", "main", "https://nclat.nic.in/dummy-chennai.pdf", [
    {"sno": "1", "case_no": "TA/200/CH/2024", "parties": "Lakshmi Machine Works Ltd. vs. ICICI Bank",
     "counsel_appellant": "Mr. Vikram Chaudhri", "counsel_respondent": "Mr. Krishnan Venugopal"},
    {"sno": "2", "case_no": "CP/22/CH/2025", "parties": "Alstom T&D India Ltd. vs. NCLT",
     "counsel_appellant": "Mr. A. Sirajudeen", "counsel_respondent": "Mr. Sriram Panchu"},
])

# ── Tomorrow – Chairperson ────────────────────────────────────────────────────
upsert_cause_list(TOMORROW, "chairperson", "main", "https://nclat.nic.in/dummy-tmw.pdf", [
    {"sno": "1", "case_no": "CA/900/2025", "parties": "Suzlon Energy Ltd. vs. SBI Consortium",
     "counsel_appellant": "Mr. Maninder Singh", "counsel_respondent": "Mr. Tushar Mehta, ASG"},
])

print("Mock data seeded for", TODAY, "and", TOMORROW)
