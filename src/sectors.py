"""Approximate SIC -> SPDR sector ETF map (robustness benchmark only).
XLRE starts Oct 2015 and XLC Jun 2018; before that the fallback ETF is used."""
import pandas as pd


def sector_etf(sic) -> tuple[str, str | None]:
    """Returns (etf, fallback-before-inception)."""
    try:
        s = int(str(sic)[:4])
    except (TypeError, ValueError):
        return "SPY", None
    if 1000 <= s <= 1299 or 1400 <= s <= 1499:
        return "XLB", None
    if 1300 <= s <= 1399 or 2900 <= s <= 2999:
        return "XLE", None
    if 2830 <= s <= 2836 or 3840 <= s <= 3851 or 8000 <= s <= 8099 or s == 8731:
        return "XLV", None
    if 3570 <= s <= 3579 or 3660 <= s <= 3679 or 3820 <= s <= 3829 or 7370 <= s <= 7379:
        return "XLK", None
    if 4800 <= s <= 4899 or 2710 <= s <= 2799 or 7800 <= s <= 7899:
        return "XLC", "XLK" if 4800 <= s <= 4899 else "XLY"
    if 4900 <= s <= 4999:
        return "XLU", None
    if s == 6798 or 6500 <= s <= 6553:
        return "XLRE", "XLF"
    if 6000 <= s <= 6799:
        return "XLF", None
    if 2000 <= s <= 2199 or 5400 <= s <= 5499 or 2840 <= s <= 2844:
        return "XLP", None
    if 5000 <= s <= 5999 or 7000 <= s <= 7099 or 3711 <= s <= 3716 or 2300 <= s <= 2399 or 7900 <= s <= 7999:
        return "XLY", None
    if 2800 <= s <= 2899 or 2400 <= s <= 2699 or 3200 <= s <= 3399:
        return "XLB", None
    if 1500 <= s <= 1799 or 3400 <= s <= 3999 or 4000 <= s <= 4799 or 7300 <= s <= 7399 or 8700 <= s <= 8799:
        return "XLI", None
    return "SPY", None


INCEPTION = {"XLRE": pd.Timestamp("2015-10-08"), "XLC": pd.Timestamp("2018-06-19")}


def sector_etf_at(sic, date) -> str:
    etf, fb = sector_etf(sic)
    if etf in INCEPTION and pd.Timestamp(date) < INCEPTION[etf] + pd.Timedelta(days=5):
        return fb or "SPY"
    return etf
