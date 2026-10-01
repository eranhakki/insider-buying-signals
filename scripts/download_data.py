#!/usr/bin/env python3
"""
download_data.py  --  data acquisition for the insider-cluster study.

Run this on a computer that can reach sec.gov and api.tiingo.com.
It produces ONE file, insider_data_export.zip, containing everything the
analysis needs. Nothing in the export contains your Tiingo API key.

What it downloads
-----------------
1. SEC Insider Transactions Data Sets (Forms 3/4/5), every quarter listed on
   https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets
   Kept: every non-derivative transaction with code 'P', every row of every
   4/A amendment, the matching SUBMISSION / REPORTINGOWNER / FOOTNOTES rows,
   and per-quarter row counts by transaction code (for the sample table).
2. SEC EDGAR company records (data.sec.gov/submissions) for each issuer with an
   officer/director purchase: SIC code, current tickers, former names.
3. Tiingo supported_tickers.zip (listing + delisting dates for every symbol).
4. Tiingo daily prices (raw and split/dividend-adjusted) for every ticker the
   issuers reported, their current EDGAR tickers, and benchmark ETFs.
   Prices are trimmed to the dates the study can use.

Usage
-----
    pip install requests pandas pyarrow
    python download_data.py --test      # 2-minute check that everything works
    python download_data.py             # full run (resumable; re-run if stopped)

Credentials
-----------
    TIINGO_API_KEY   environment variable (or you will be prompted, hidden)
    SEC_CONTACT      "Your Name your@email" (or you will be prompted). The SEC
                     requires a contact in the User-Agent of automated requests.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import getpass
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

try:
    import pandas as pd
    import requests
    import pyarrow  # noqa: F401  (needed by pandas.to_parquet)
except ImportError as e:  # pragma: no cover
    sys.exit(f"Missing package ({e.name}). Run:  pip install requests pandas pyarrow")

SEC_PAGE = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
SEC_README = "https://www.sec.gov/files/insider_transactions_readme.pdf"
SEC_URL_PATTERNS = [
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip",
    "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{q}_form345.zip",
]
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
TIINGO_SUPPORTED = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
TIINGO_PRICES = "https://api.tiingo.com/tiingo/daily/{t}/prices"

BENCHMARKS = ["SPY", "IWM", "VTI", "IJR", "MDY",
              "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC"]
PRICE_START = "2005-01-01"
PRE_DAYS = 400    # calendar days of history kept before each filing (momentum, liquidity)
POST_DAYS = 200   # calendar days kept after each filing (60 trading days + lags)
SEC_SLEEP = 0.15  # stay well under the SEC's 10 requests/second limit

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data_cache"
OUT = ROOT / "insider_data_export"
LOG_ROWS: list[dict] = []


# ----------------------------------------------------------------- utilities
def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def log(source: str, item: str, status: str, detail: str = "") -> None:
    LOG_ROWS.append({"utc": now(), "source": source, "item": item,
                     "status": status, "detail": detail[:300]})


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get(session: requests.Session, url: str, *, sleep: float = 0.0, tries: int = 6,
        **kw) -> requests.Response | None:
    """GET with polite retries. Returns the response for 200/404, else None."""
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=120, **kw)
        except requests.RequestException as e:
            wait = min(300, 5 * 2 ** attempt)
            print(f"   network error ({e.__class__.__name__}); retrying in {wait}s")
            time.sleep(wait)
            continue
        if sleep:
            time.sleep(sleep)
        if r.status_code in (200, 404):
            return r
        if r.status_code in (401, 403) and "tiingo" in url:
            return r  # authentication problem: retrying will not help
        if r.status_code in (429, 403, 500, 502, 503, 504):
            wait = 60 if r.status_code == 429 else min(300, 10 * 2 ** attempt)
            if r.status_code == 429 and "tiingo" in url:
                wait = 600  # hourly request allowance used up; wait it out
            print(f"   HTTP {r.status_code} from {url.split('?')[0]}; waiting {wait}s")
            time.sleep(wait)
            continue
        return r
    return None


def norm_symbol(s) -> str | None:
    """SEC-reported symbol -> Tiingo style (BRK.B -> BRK-B). None if unusable."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip().upper().lstrip("$")
    s = re.split(r"[\s,;]+", s)[0] if s else s
    s = s.replace(".", "-").replace("/", "-")
    if s in {"", "NONE", "N/A", "NA", "NULL", "-", "--"}:
        return None
    if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", s):
        return None
    return s


# --------------------------------------------------------------- SEC: zips
def sec_zip_urls(session) -> dict[str, str]:
    """Quarter -> URL, read from the SEC page; falls back to known patterns."""
    urls: dict[str, str] = {}
    r = get(session, SEC_PAGE, sleep=SEC_SLEEP)
    if r is not None and r.status_code == 200:
        for m in re.finditer(r'href="([^"]*?(\d{4}q[1-4])_form345\.zip)"', r.text):
            href, q = m.group(1), m.group(2)
            urls[q] = href if href.startswith("http") else "https://www.sec.gov" + href
    if not urls:
        print("   could not read the SEC page; falling back to URL patterns")
        today = dt.date.today()
        for y in range(2006, today.year + 1):
            for k in range(1, 5):
                urls[f"{y}q{k}"] = SEC_URL_PATTERNS[0].format(q=f"{y}q{k}")
    log("sec_page", SEC_PAGE, "ok" if urls else "fail", f"{len(urls)} quarters")
    return dict(sorted(urls.items()))


def download_sec_zip(session, q: str, url: str) -> Path | None:
    dest = CACHE / "sec" / f"{q}_form345.zip"
    if dest.exists() and zipfile.is_zipfile(dest):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    candidates = [url] + [p.format(q=q) for p in SEC_URL_PATTERNS if p.format(q=q) != url]
    for u in candidates:
        r = get(session, u, sleep=SEC_SLEEP)
        if r is not None and r.status_code == 200 and r.content[:2] == b"PK":
            dest.write_bytes(r.content)
            log("sec_zip", q, "ok", f"{u} sha256={sha256(dest)} bytes={dest.stat().st_size}")
            return dest
    log("sec_zip", q, "fail", url)
    return None


def read_tsv(zf: zipfile.ZipFile, stem: str) -> pd.DataFrame | None:
    names = [n for n in zf.namelist() if Path(n).stem.upper() == stem]
    if not names:
        return None
    with zf.open(names[0]) as f:
        return pd.read_csv(f, sep="\t", dtype=str, quoting=csv.QUOTE_NONE,
                           keep_default_na=False, na_values=[""],
                           encoding="utf-8", encoding_errors="replace",
                           on_bad_lines="warn", low_memory=False)


def process_sec_zip(path: Path, q: str) -> dict[str, pd.DataFrame]:
    """Keep purchase legs, 4/A amendments and the rows that describe them."""
    with zipfile.ZipFile(path) as zf:
        sub = read_tsv(zf, "SUBMISSION")
        own = read_tsv(zf, "REPORTINGOWNER")
        ndt = read_tsv(zf, "NONDERIV_TRANS")
        fn = read_tsv(zf, "FOOTNOTES")
    if sub is None or own is None or ndt is None:
        raise RuntimeError(f"{q}: expected tables missing from zip")

    counts = (ndt.assign(TRANS_CODE=ndt["TRANS_CODE"].fillna("?"))
                 .groupby("TRANS_CODE").size().rename("n_legs").reset_index())
    counts.insert(0, "quarter", q)
    doc_counts = sub.groupby("DOCUMENT_TYPE").size().rename("n_filings").reset_index()
    doc_counts.insert(0, "quarter", q)

    amend_acc = set(sub.loc[sub["DOCUMENT_TYPE"].isin(["4/A", "5/A"]), "ACCESSION_NUMBER"])
    p_acc = set(ndt.loc[ndt["TRANS_CODE"] == "P", "ACCESSION_NUMBER"])
    keep_acc = p_acc | amend_acc

    out = {
        "nonderiv_trans": ndt[ndt["ACCESSION_NUMBER"].isin(keep_acc)],
        "submission": sub[sub["ACCESSION_NUMBER"].isin(keep_acc)],
        "reportingowner": own[own["ACCESSION_NUMBER"].isin(keep_acc)],
        "footnotes": (fn[fn["ACCESSION_NUMBER"].isin(p_acc)] if fn is not None
                      else pd.DataFrame(columns=["ACCESSION_NUMBER", "FOOTNOTE_ID", "FOOTNOTE_TXT"])),
        "counts_trans_code": counts,
        "counts_document_type": doc_counts,
    }
    for k in ("nonderiv_trans", "submission", "reportingowner", "footnotes"):
        out[k] = out[k].copy()
        out[k].insert(0, "SOURCE_QUARTER", q)
    return out


def sec_stage(session, test: bool) -> dict[str, pd.DataFrame]:
    print("\n[1/4] SEC insider data sets")
    urls = sec_zip_urls(session)
    quarters = list(urls)
    if test:
        quarters = quarters[-1:]
    parts: dict[str, list[pd.DataFrame]] = {}
    for i, q in enumerate(quarters, 1):
        print(f"   {i:>3}/{len(quarters)}  {q}", end="", flush=True)
        path = download_sec_zip(session, q, urls[q])
        if path is None:
            print("  -- FAILED (logged)")
            continue
        tables = process_sec_zip(path, q)
        for k, v in tables.items():
            parts.setdefault(k, []).append(v)
        print(f"  purchases={int((tables['nonderiv_trans']['TRANS_CODE'] == 'P').sum()):,}")
    return {k: pd.concat(v, ignore_index=True) for k, v in parts.items()}


# ----------------------------------------------------- SEC: company records
def officer_director_purchases(sec: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Purchase legs whose filing has at least one officer/director owner."""
    ndt, sub, own = sec["nonderiv_trans"], sec["submission"], sec["reportingowner"]
    rel = own["RPTOWNER_RELATIONSHIP"].fillna("").str.upper()
    od_acc = set(own.loc[rel.str.contains("OFFICER|DIRECTOR"), "ACCESSION_NUMBER"])
    p = ndt[(ndt["TRANS_CODE"] == "P") & ndt["ACCESSION_NUMBER"].isin(od_acc)]
    s = sub[["ACCESSION_NUMBER", "FILING_DATE", "ISSUERCIK", "ISSUERTRADINGSYMBOL"]].drop_duplicates("ACCESSION_NUMBER")
    p = p[["ACCESSION_NUMBER"]].drop_duplicates().merge(s, on="ACCESSION_NUMBER", how="left")
    p["filing_date"] = pd.to_datetime(p["FILING_DATE"], format="%d-%b-%Y", errors="coerce")
    return p


def edgar_stage(session, ciks: list[int]) -> pd.DataFrame:
    print(f"\n[2/4] SEC EDGAR company records for {len(ciks):,} issuers")
    cache = CACHE / "edgar"
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.time()
    for i, cik in enumerate(ciks, 1):
        f = cache / f"{cik}.json"
        if not f.exists():
            r = get(session, EDGAR_SUBMISSIONS.format(cik=cik), sleep=SEC_SLEEP)
            if r is None:
                log("edgar", str(cik), "fail")
                continue
            if r.status_code == 404:
                f.write_text("{}")
                log("edgar", str(cik), "404")
            else:
                d = r.json()
                slim = {k: d.get(k) for k in ("cik", "name", "sic", "sicDescription", "tickers",
                                              "exchanges", "formerNames", "entityType",
                                              "stateOfIncorporation")}
                f.write_text(json.dumps(slim))
        d = json.loads(f.read_text() or "{}")
        rows.append({"ISSUERCIK": cik, "edgar_name": d.get("name"), "sic": d.get("sic"),
                     "sic_description": d.get("sicDescription"),
                     "edgar_tickers": "|".join(d.get("tickers") or []),
                     "edgar_exchanges": "|".join([e or "" for e in (d.get("exchanges") or [])]),
                     "former_names": json.dumps(d.get("formerNames") or []),
                     "entity_type": d.get("entityType")})
        if i % 250 == 0:
            rate = i / max(time.time() - t0, 1)
            print(f"   {i:,}/{len(ciks):,}  (~{(len(ciks) - i) / rate / 60:.0f} min left)")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ Tiingo
def tiingo_supported(session) -> pd.DataFrame:
    print("\n[3/4] Tiingo supported-ticker list")
    dest = CACHE / "tiingo_supported_tickers.zip"
    if not dest.exists():
        r = get(session, TIINGO_SUPPORTED)
        if r is None or r.status_code != 200:
            log("tiingo_supported", TIINGO_SUPPORTED, "fail")
            return pd.DataFrame()
        dest.write_bytes(r.content)
        log("tiingo_supported", TIINGO_SUPPORTED, "ok", f"sha256={sha256(dest)}")
    with zipfile.ZipFile(dest) as zf:
        with zf.open(zf.namelist()[0]) as f:
            return pd.read_csv(f, dtype=str)


def keep_windows(prices: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    """Keep only rows within [filing-PRE_DAYS, filing+POST_DAYS] of any filing."""
    if not dates:
        return prices
    d = pd.to_datetime(prices["date"])
    mask = pd.Series(False, index=prices.index)
    ds = sorted(set(pd.Timestamp(x).normalize() for x in dates))
    # merge overlapping windows first
    windows, (lo, hi) = [], (ds[0] - pd.Timedelta(days=PRE_DAYS), ds[0] + pd.Timedelta(days=POST_DAYS))
    for x in ds[1:]:
        a, b = x - pd.Timedelta(days=PRE_DAYS), x + pd.Timedelta(days=POST_DAYS)
        if a <= hi:
            hi = max(hi, b)
        else:
            windows.append((lo, hi)); lo, hi = a, b
    windows.append((lo, hi))
    for a, b in windows:
        mask |= (d >= a) & (d <= b)
    return prices[mask]


def tiingo_prices(session, key: str, ticker: str, start: str, end: str) -> tuple[str, pd.DataFrame | None]:
    f = CACHE / "tiingo" / f"{ticker}_{start}_{end}.json.gz"  # range in name: test runs never shorten full-run data
    if f.exists():
        import gzip
        data = json.loads(gzip.decompress(f.read_bytes()) or b"[]")
        status = "cached"
    else:
        r = get(session, TIINGO_PRICES.format(t=ticker),
                params={"startDate": start, "endDate": end},
                headers={"Authorization": f"Token {key}", "Content-Type": "application/json"},
                sleep=0.05)
        if r is None:
            return "fail", None
        if r.status_code == 404:
            data, status = [], "not_found"
        elif r.status_code != 200:
            return f"http_{r.status_code}", None
        else:
            try:
                data = r.json()
            except ValueError:
                return "bad_json", None
            if isinstance(data, dict):  # error payload
                data, status = [], "error:" + str(data.get("detail", ""))[:80]
            else:
                status = "ok"
        import gzip
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(gzip.compress(json.dumps(data).encode()))
    if not data:
        return (status if status != "cached" else "empty"), None
    df = pd.DataFrame(data)
    cols = ["date", "open", "close", "volume", "adjOpen", "adjClose", "adjVolume", "divCash", "splitFactor"]
    df = df[[c for c in cols if c in df.columns]].copy()
    df["date"] = df["date"].str[:10]
    df.insert(0, "ticker", ticker)
    return ("ok" if status == "cached" else status), df


def tiingo_stage(session, key: str, purchases: pd.DataFrame, edgar: pd.DataFrame,
                 test: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("\n[4/4] Tiingo daily prices")
    # candidate tickers -> filing dates that need them
    need: dict[str, set] = {}
    src: dict[str, set] = {}
    purchases = purchases.dropna(subset=["filing_date"])
    for sym, fd, cik in purchases[["ISSUERTRADINGSYMBOL", "filing_date", "ISSUERCIK"]].itertuples(index=False):
        t = norm_symbol(sym)
        if t:
            need.setdefault(t, set()).add(fd); src.setdefault(t, set()).add("sec_reported")
    if not edgar.empty:
        cik_dates = purchases.groupby(purchases["ISSUERCIK"].astype(int))["filing_date"].apply(set).to_dict()
        for cik, tick in edgar[["ISSUERCIK", "edgar_tickers"]].itertuples(index=False):
            for t in (tick or "").split("|"):
                t = norm_symbol(t)
                if t:
                    need.setdefault(t, set()).update(cik_dates.get(int(cik), set()))
                    src.setdefault(t, set()).add("edgar_current")
    tickers = sorted(need)
    if test:
        tickers = tickers[:20]
    tickers = BENCHMARKS + [t for t in tickers if t not in BENCHMARKS]
    today = dt.date.today().isoformat()

    frames, status_rows = [], []
    t0 = time.time()
    for i, t in enumerate(tickers, 1):
        dates = sorted(need.get(t, []))
        if t in BENCHMARKS:
            start, end, dates_for_trim = PRICE_START, today, []
        else:
            start = (min(dates) - pd.Timedelta(days=PRE_DAYS)).date().isoformat()
            end = min((max(dates) + pd.Timedelta(days=POST_DAYS)).date(), dt.date.today()).isoformat()
            start = max(start, PRICE_START)
            dates_for_trim = dates
        status, df = tiingo_prices(session, key, t, start, end)
        n = 0
        if df is not None:
            df = keep_windows(df, dates_for_trim)
            n = len(df)
            frames.append(df)
        status_rows.append({"ticker": t, "status": status, "rows_kept": n,
                            "sources": "|".join(sorted(src.get(t, {"benchmark"}))),
                            "request_start": start, "request_end": end})
        if i % 100 == 0 or i == len(tickers):
            rate = i / max(time.time() - t0, 1)
            print(f"   {i:,}/{len(tickers):,} tickers  (~{(len(tickers) - i) / rate / 60:.0f} min left)")
    prices = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return prices, pd.DataFrame(status_rows)


# -------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true", help="1 quarter + 20 tickers, to check setup")
    ap.add_argument("--skip-edgar", action="store_true", help="skip EDGAR company records")
    args = ap.parse_args()

    key = os.environ.get("TIINGO_API_KEY") or getpass.getpass("Tiingo API key (input hidden): ")
    key = key.strip().strip('"').strip("'")
    contact = os.environ.get("SEC_CONTACT") or input("Your name and email for the SEC (e.g. 'Jane Doe jane@x.com'): ").strip()
    if not key or "@" not in contact:
        sys.exit("Need a Tiingo key and a contact with an email address.")

    sec_s = requests.Session()
    sec_s.headers.update({"User-Agent": f"{contact} (academic research)", "Accept-Encoding": "gzip, deflate"})
    ti_s = requests.Session()

    # quick credential check: one request, and say exactly what went wrong
    print("Checking the Tiingo key...")
    try:
        r = ti_s.get(TIINGO_PRICES.format(t="SPY"), timeout=30,
                     params={"startDate": "2024-01-02", "endDate": "2024-01-05"},
                     headers={"Authorization": f"Token {key}", "Content-Type": "application/json"})
    except requests.exceptions.SSLError as e:
        sys.exit(f"Could not reach Tiingo: SSL/certificate error.\n  {e}\n"
                 "Fix: run  pip3 install --upgrade certifi requests  and try again.")
    except requests.RequestException as e:
        sys.exit(f"Could not reach Tiingo (network problem): {e.__class__.__name__}: {e}")
    body = r.text[:300].replace(key, "<key>")
    if r.status_code != 200 or not r.text.strip().startswith("["):
        sys.exit(f"Tiingo key check failed: HTTP {r.status_code}\n  Tiingo said: {body}\n"
                 "Check the key was pasted in full (no spaces), from https://www.tiingo.com/account/api/token")
    print(f"Tiingo key OK (key length {len(key)}).")

    started = now()
    sec = sec_stage(sec_s, args.test)
    purchases = officer_director_purchases(sec)
    ciks = sorted(purchases["ISSUERCIK"].dropna().astype(int).unique().tolist())
    if args.test:
        ciks = ciks[:20]
    edgar = pd.DataFrame() if args.skip_edgar else edgar_stage(sec_s, ciks)
    supported = tiingo_supported(ti_s)
    prices, price_status = tiingo_stage(ti_s, key, purchases, edgar, args.test)

    # ---- write export
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    written = {}
    def save(name: str, df: pd.DataFrame) -> None:
        p = OUT / f"{name}.parquet"
        df.to_parquet(p, index=False, compression="zstd")
        written[p.name] = {"rows": int(len(df)), "sha256": sha256(p), "bytes": p.stat().st_size}
    for k, v in sec.items():
        save(f"sec_{k}", v)
    if not edgar.empty:
        save("edgar_companies", edgar)
    if not supported.empty:
        save("tiingo_supported_tickers", supported)
    if not prices.empty:
        # compact storage: raw close/volume (price-match and liquidity checks),
        # adjusted open/close (returns), split factor and dividends (corporate-action audit)
        prices = prices[["ticker", "date", "close", "volume", "adjOpen", "adjClose", "divCash", "splitFactor"]].copy()
        for c in ["close", "adjOpen", "adjClose", "divCash", "splitFactor"]:
            prices[c] = pd.to_numeric(prices[c], errors="coerce").astype("float32")
        prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce").astype("float64")
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
        save("tiingo_prices", prices)
    save("tiingo_price_status", price_status)
    pd.DataFrame(LOG_ROWS).to_csv(OUT / "download_log.csv", index=False)

    manifest = {
        "script": "download_data.py", "mode": "test" if args.test else "full",
        "started_utc": started, "finished_utc": now(),
        "python": sys.version.split()[0], "pandas": pd.__version__,
        "sources": {"sec_page": SEC_PAGE, "sec_readme": SEC_README,
                    "edgar_submissions": EDGAR_SUBMISSIONS, "tiingo_supported": TIINGO_SUPPORTED,
                    "tiingo_prices": TIINGO_PRICES},
        "price_trim_days": {"pre": PRE_DAYS, "post": POST_DAYS}, "benchmarks": BENCHMARKS,
        "files": written,
        "note": "Tiingo data are licensed to the subscriber; do not redistribute raw prices.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    zpath = ROOT / ("insider_data_export_TEST.zip" if args.test else "insider_data_export.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as zf:  # parquet already compressed
        for p in sorted(OUT.iterdir()):
            zf.write(p, arcname=f"insider_data_export/{p.name}")
    ok = (price_status["status"] == "ok").sum()
    print(f"\nDone. Tickers with prices: {ok:,}/{len(price_status):,}")
    print(f"Export: {zpath}  ({zpath.stat().st_size / 1e6:.1f} MB)")
    if args.test:
        print("Test run worked. Now run the full download:  python download_data.py")
    else:
        print("Attach that zip file in the chat.")


if __name__ == "__main__":
    main()
