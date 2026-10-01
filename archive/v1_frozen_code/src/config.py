"""Frozen parameters. Mirrors docs/ANALYSIS_PLAN.md; change nothing here without
logging a deviation in that file."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "insider_data_export"
INTER = ROOT / "output" / "intermediate"
TABLES = ROOT / "output" / "tables"
FIGS = ROOT / "output" / "figures"
for p in (INTER, TABLES, FIGS):
    p.mkdir(parents=True, exist_ok=True)

DEV_START, DEV_END = "2006-01-01", "2018-12-31"
TEST_START, TEST_END = "2019-01-01", "2026-06-30"

WINDOW = 30                      # primary cluster window (calendar days)
ALT_WINDOWS = [14, 60]
HORIZONS = [20, 60]              # trading days after entry
PRIMARY_H = 60
ENTRY = "t1_close"               # primary timing rule
ENTRY_VARIANTS = ["t1_close", "t1_open", "t2_close", "t0_close"]

MIN_PRICE = 1.0
LIQ_PRICE, LIQ_DV = 5.0, 1_000_000
MATCH_ISSUER_BAND = (0.8, 1.25)
MATCH_EVENT_BAND = (0.67, 1.5)
MATCH_STRICT_BAND = (0.9, 1.1)
DELIST_RET = -0.30

N_CONTROLS = 5
CONTROL_START_WINDOW = 60        # calendar days either side of F_i
MATCH_VARS = ["ret_21", "ret_126", "log_dv", "log_init_value"]
BOOT = 1000
SEED = 20260930

EXCLUDED_SIC = {"6722", "6726"}
# Deviation 1: EDGAR gives registered/closed-end funds no SIC code, so funds are
# identified as blank-SIC issuers with a fund-style name.
FUND_NAME_RE = r"\bfunds?\b|\btrust\b|portfolio|municipal|\bincome\b|opportunit|\bstrateg"

COMMON_RE = r"common|ordinary|class [a-c]\b|shares|stock"
NONCOMMON_RE = (r"preferred|\bpref\b|warrant|\bnotes?\b|debenture|\bunits?\b|\brights?\b|option|"
                r"depositary|\bads\b|bond|convertible|series [a-z] pref")
FOOTNOTE_EXCLUDE_RE = (
    r"private placement|privately negotiated|subscription agreement|"
    r"directly from the (?:company|issuer)|from the issuer|purchased from the company|"
    r"registered direct|public offering|underwritten|initial public offering|\bipo\b|"
    r"directed share|rights offering|employee stock purchase|\bespp\b|dividend reinvestment|"
    r"\bdrip\b|401\(k\)|conversion of|in exchange for|exchange offer|"
    r"(?:pursuant to|in connection with) (?:the |a )?merger|merger consideration|spin-?off")
# Deviation 3: the screen reads only footnotes attached to transaction fields
# (not to post-transaction holdings / ownership-nature fields) plus REMARKS.
TXN_FN_COLS = ["SECURITY_TITLE_FN", "TRANS_DATE_FN", "DEEMED_EXECUTION_DATE_FN", "EQUITY_SWAP_TRANS_CD_FN",
               "TRANS_TIMELINESS_FN", "TRANS_SHARES_FN", "TRANS_PRICEPERSHARE_FN", "TRANS_ACQUIRED_DISP_CD_FN"]
PLAN_RE = r"10b5-?1"
TOP_TITLE_RE = r"\bceo\b|chief executive|\bcfo\b|chief financial|president|chair"

BENCH = "SPY"
SECTOR_ETFS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC"]
