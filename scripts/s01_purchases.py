"""Step 1: SEC rows -> eligible open-market purchase disclosures.

Outputs (output/intermediate):
  legs_all.parquet        every P-code leg with each filter flag (audit trail)
  disclosures.parquet     one row per (issuer, filing date, owner group), primary sample
  amend_only.parquet      4/A-only purchases (robustness)
Tables: sample_construction_legs.csv
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402

FN_COLS = None
ED_CIKS: set = set()


def load():
    nd = pd.read_parquet(C.RAW / "sec_nonderiv_trans.parquet")
    sub = pd.read_parquet(C.RAW / "sec_submission.parquet")
    own = pd.read_parquet(C.RAW / "sec_reportingowner.parquet")
    fn = pd.read_parquet(C.RAW / "sec_footnotes.parquet")
    ed = pd.read_parquet(C.RAW / "edgar_companies.parquet")
    return nd, sub, own, fn, ed


def owner_groups(own: pd.DataFrame) -> pd.DataFrame:
    own = own.drop_duplicates(["ACCESSION_NUMBER", "RPTOWNERCIK"]).copy()
    rel = own["RPTOWNER_RELATIONSHIP"].fillna("").str.upper()
    own["is_officer"] = rel.str.contains("OFFICER")
    own["is_director"] = rel.str.contains("DIRECTOR")
    own["title"] = own["RPTOWNER_TITLE"].fillna("").str.strip()
    own["is_top"] = own["title"].str.lower().str.contains(C.TOP_TITLE_RE, regex=True)
    own["owner_cik"] = own["RPTOWNERCIK"].astype(str).str.lstrip("0")
    g = own.groupby("ACCESSION_NUMBER").agg(
        owners=("owner_cik", lambda s: "|".join(sorted(set(s)))),
        owner_names=("RPTOWNERNAME", lambda s: "; ".join(sorted(set(map(str, s))))),
        n_owners=("owner_cik", "nunique"),
        any_officer=("is_officer", "any"),
        any_director=("is_director", "any"),
        any_top=("is_top", "any"),
        titles=("title", lambda s: "; ".join(sorted({t for t in s if t}))),
    ).reset_index()
    g["any_od"] = g["any_officer"] | g["any_director"]
    return g


def footnote_text(nd: pd.DataFrame, fn: pd.DataFrame, cols=None) -> pd.Series:
    """Concatenate the text of the footnotes referenced in `cols` on each leg."""
    fn_cols = cols or [c for c in nd.columns if c.endswith("_FN")]
    ref = nd[["ACCESSION_NUMBER"] + fn_cols].copy()
    ref["ids"] = ref[fn_cols].fillna("").agg(",".join, axis=1)
    ref["ids"] = ref["ids"].str.findall(r"F\d+")
    ex = ref[["ACCESSION_NUMBER", "ids"]].explode("ids").dropna()
    ex = ex.reset_index().rename(columns={"index": "row"})
    fnt = fn.drop_duplicates(["ACCESSION_NUMBER", "FOOTNOTE_ID"])[["ACCESSION_NUMBER", "FOOTNOTE_ID", "FOOTNOTE_TXT"]]
    ex = ex.merge(fnt, left_on=["ACCESSION_NUMBER", "ids"], right_on=["ACCESSION_NUMBER", "FOOTNOTE_ID"], how="left")
    txt = ex.groupby("row")["FOOTNOTE_TXT"].apply(lambda s: " || ".join(s.dropna().astype(str)))
    return txt.reindex(nd.index).fillna("")


def main():
    nd, sub, own, fn, ed = load()
    nd = nd.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]).reset_index(drop=True)
    sub = sub.drop_duplicates("ACCESSION_NUMBER")
    og = owner_groups(own)

    p = nd[nd["TRANS_CODE"] == "P"].copy()
    fnp = fn[fn["ACCESSION_NUMBER"].isin(p["ACCESSION_NUMBER"])]
    p["footnotes"] = footnote_text(p, fnp, C.TXN_FN_COLS)          # transaction-field footnotes (screened)
    p["footnotes_all"] = footnote_text(p, fnp)                     # every footnote (kept for the audit)
    p = p.merge(sub[["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME",
                     "ISSUERTRADINGSYMBOL", "REMARKS", "NOT_SUBJECT_SEC16", "AFF10B5ONE", "DATE_OF_ORIG_SUB"]],
                on="ACCESSION_NUMBER", how="left")
    p = p.merge(og, on="ACCESSION_NUMBER", how="left")
    p["issuer_cik"] = pd.to_numeric(p["ISSUERCIK"], errors="coerce").astype("Int64")
    ed = ed.rename(columns={"ISSUERCIK": "issuer_cik"})
    ed["issuer_cik"] = ed["issuer_cik"].astype("Int64")
    p = p.merge(ed[["issuer_cik", "sic", "sic_description", "edgar_tickers"]], on="issuer_cik", how="left")
    global ED_CIKS
    ED_CIKS = set(ed["issuer_cik"].dropna())

    p["filing_date"] = pd.to_datetime(p["FILING_DATE"], format="%d-%b-%Y", errors="coerce")
    p["trans_date"] = pd.to_datetime(p["TRANS_DATE"], format="%d-%b-%Y", errors="coerce")
    p["shares"] = pd.to_numeric(p["TRANS_SHARES"], errors="coerce")
    p["price"] = pd.to_numeric(p["TRANS_PRICEPERSHARE"], errors="coerce")
    title = p["SECURITY_TITLE"].fillna("").str.lower()
    fntxt = (p["footnotes"] + " " + p["REMARKS"].fillna("")).str.lower()
    truthy = lambda s: s.fillna("").astype(str).str.strip().str.lower().isin(["1", "true", "y", "yes"])

    # ---- sequential filter flags (each row keeps the first filter it fails)
    steps = [
        ("original Form 4 (not 4/A, 5, 3)", p["DOCUMENT_TYPE"].eq("4")),
        ("acquisition code A", p["TRANS_ACQUIRED_DISP_CD"].eq("A")),
        ("owner is officer or director", p["any_od"].fillna(False).astype(bool)),
        ("common/ordinary equity title", title.str.contains(C.COMMON_RE) & ~title.str.contains(C.NONCOMMON_RE)),
        ("shares > 0 and price > 0", (p["shares"] > 0) & (p["price"] > 0)),
        ("no equity swap; subject to Sec. 16", ~truthy(p["EQUITY_SWAP_INVOLVED"]) & ~truthy(p["NOT_SUBJECT_SEC16"])),
        ("valid dates (0-365 days before filing)",
         p["filing_date"].notna() & p["trans_date"].notna() & (p["trans_date"] <= p["filing_date"])
         & ((p["filing_date"] - p["trans_date"]).dt.days <= 365)),
        ("footnote screen (not private/offering/plan acquisition)", ~fntxt.str.contains(C.FOOTNOTE_EXCLUDE_RE, regex=True)),
        ("issuer not a registered/closed-end fund",
         ~(p["sic"].astype(str).isin(C.EXCLUDED_SIC)
           | ((p["sic"].fillna("").astype(str).str.strip() == "") & p["issuer_cik"].isin(ED_CIKS)
              & p["ISSUERNAME"].fillna("").str.lower().str.contains(C.FUND_NAME_RE, regex=True)))),
        ("filing date in 2006-01-01..2026-06-30", p["filing_date"].between("2006-01-01", C.TEST_END)),
    ]
    p["fail_step"] = ""
    alive = pd.Series(True, index=p.index)
    rows = [{"step": "P-code non-derivative legs in the SEC data sets (all forms)", "legs_remaining": int(len(p)),
             "legs_removed": 0}]
    for name, ok in steps:
        ok = ok.fillna(False).astype(bool)
        failed = alive & ~ok
        p.loc[failed, "fail_step"] = name
        alive &= ok
        rows.append({"step": name, "legs_remaining": int(alive.sum()), "legs_removed": int(failed.sum())})
    p["eligible"] = alive
    p["fn_screen_hit"] = fntxt.str.contains(C.FOOTNOTE_EXCLUDE_RE, regex=True)
    p["plan_10b5_1"] = ((p["footnotes_all"] + " " + p["REMARKS"].fillna("")).str.lower().str.contains(C.PLAN_RE, regex=True)
                        | truthy(p["AFF10B5ONE"]))
    p["value"] = p["shares"] * p["price"]
    p["filing_lag_bd"] = np.nan
    ok = p["filing_date"].notna() & p["trans_date"].notna() & (p["trans_date"] <= p["filing_date"])
    p.loc[ok, "filing_lag_bd"] = np.busday_count(p.loc[ok, "trans_date"].values.astype("datetime64[D]"),
                                                  p.loc[ok, "filing_date"].values.astype("datetime64[D]"))

    keep_cols = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "DOCUMENT_TYPE", "issuer_cik", "ISSUERNAME",
                 "ISSUERTRADINGSYMBOL", "edgar_tickers", "sic", "sic_description", "filing_date", "trans_date",
                 "SECURITY_TITLE", "shares", "price", "value", "TRANS_ACQUIRED_DISP_CD", "owners", "owner_names",
                 "n_owners", "any_officer", "any_director", "any_top", "titles", "footnotes", "footnotes_all", "REMARKS",
                 "plan_10b5_1", "fn_screen_hit", "filing_lag_bd", "DATE_OF_ORIG_SUB", "fail_step", "eligible",
                 "SOURCE_QUARTER"]
    legs = p[keep_cols].copy()
    legs.to_parquet(C.INTER / "legs_all.parquet", index=False)
    sc = pd.DataFrame(rows)
    sc.to_csv(C.TABLES / "sample_construction_legs.csv", index=False)
    print(sc.to_string(index=False))

    # ---- legs -> disclosures
    e = legs[legs["eligible"]].copy()
    n0 = len(e)
    # identical legs reported in *different* accessions filed the same day are duplicate filings;
    # identical legs inside one accession are separate lots (e.g. direct and IRA) and are kept
    key = ["issuer_cik", "owners", "filing_date", "trans_date", "shares", "price"]
    first_acc = e.groupby(key, dropna=False)["ACCESSION_NUMBER"].transform("min")
    e = e[e["ACCESSION_NUMBER"] == first_acc]
    dup_removed = n0 - len(e)
    # merge same-day accessions for the same issuer whose owner sets overlap (union-find)
    e["acc_key"] = e["ACCESSION_NUMBER"]
    acc = e.drop_duplicates("ACCESSION_NUMBER")[["issuer_cik", "filing_date", "ACCESSION_NUMBER", "owners"]]
    nacc = acc.groupby(["issuer_cik", "filing_date"])["ACCESSION_NUMBER"].transform("size")
    groups = dict(zip(acc.loc[nacc == 1, "ACCESSION_NUMBER"], acc.loc[nacc == 1, "ACCESSION_NUMBER"]))
    for (cik, fd), g in acc[nacc > 1].groupby(["issuer_cik", "filing_date"], sort=False):
        accs = g[["ACCESSION_NUMBER", "owners"]].values.tolist()
        parent = {a: a for a, _ in accs}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        sets = [(a, set(o.split("|"))) for a, o in accs]
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                if sets[i][1] & sets[j][1]:
                    parent[find(sets[i][0])] = find(sets[j][0])
        for a, _ in accs:
            groups[a] = find(a)
    e["disc_id"] = e["ACCESSION_NUMBER"].map(groups)
    agg = e.groupby("disc_id").agg(
        issuer_cik=("issuer_cik", "first"), issuer_name=("ISSUERNAME", "first"),
        sec_symbol=("ISSUERTRADINGSYMBOL", "first"), edgar_tickers=("edgar_tickers", "first"),
        sic=("sic", "first"), filing_date=("filing_date", "first"),
        trans_date_min=("trans_date", "min"), trans_date_max=("trans_date", "max"),
        shares=("shares", "sum"), value=("value", "sum"),
        owners=("owners", lambda s: "|".join(sorted(set("|".join(s).split("|"))))),
        owner_names=("owner_names", "first"),
        any_officer=("any_officer", "max"), any_director=("any_director", "max"), any_top=("any_top", "max"),
        titles=("titles", "first"), plan_10b5_1=("plan_10b5_1", "max"),
        filing_lag_bd=("filing_lag_bd", "max"), n_legs=("NONDERIV_TRANS_SK", "size"),
        accessions=("ACCESSION_NUMBER", lambda s: "|".join(sorted(set(s)))),
    ).reset_index()
    agg["vwap"] = agg["value"] / agg["shares"]
    agg["role"] = np.where(agg["any_officer"], "officer", "director_only")
    agg["late_filed"] = agg["filing_lag_bd"] > 4
    agg = agg.sort_values(["issuer_cik", "filing_date"]).reset_index(drop=True)
    agg.to_parquet(C.INTER / "disclosures.parquet", index=False)

    # ---- 4/A-only purchases (robustness)
    a = legs[(legs["DOCUMENT_TYPE"] == "4/A") & (legs["fail_step"] == "original Form 4 (not 4/A, 5, 3)")].copy()
    # re-apply the other filters to amendments
    a = a[(a["TRANS_ACQUIRED_DISP_CD"] == "A")
          & (a["any_officer"].fillna(False).astype(bool) | a["any_director"].fillna(False).astype(bool))]
    a = a[a["SECURITY_TITLE"].fillna("").str.lower().str.contains(C.COMMON_RE)
          & ~a["SECURITY_TITLE"].fillna("").str.lower().str.contains(C.NONCOMMON_RE)
          & (a["shares"] > 0) & (a["price"] > 0)
          & ~(a["footnotes"] + " " + a["REMARKS"].fillna("")).str.lower().str.contains(C.FOOTNOTE_EXCLUDE_RE)]
    orig = legs[legs["DOCUMENT_TYPE"] == "4"][["issuer_cik", "owners", "trans_date", "shares"]]
    m = a.reset_index().merge(orig, on=["issuer_cik", "owners", "trans_date"], how="left", suffixes=("", "_o"))
    m["match"] = (m["shares_o"] - m["shares"]).abs() <= 0.01 * m["shares"]
    matched = m.groupby("index")["match"].any()
    a["has_original"] = matched.reindex(a.index).fillna(False).values
    amend_only = a[~a["has_original"]]
    amend_only.to_parquet(C.INTER / "amend_only.parquet", index=False)

    summ = {
        "eligible_legs": int(n0), "duplicate_legs_removed": int(dup_removed),
        "disclosures": int(len(agg)), "issuers": int(agg["issuer_cik"].nunique()),
        "multi_accession_disclosures": int((agg["accessions"].str.count(r"\|") > 0).sum()),
        "joint_filer_disclosures": int((agg["owners"].str.count(r"\|") > 0).sum()),
        "amendment_P_legs_checked": int(len(a)), "amendment_only_legs": int(len(amend_only)),
        "plan_10b5_1_disclosures": int(agg["plan_10b5_1"].sum()),
        "late_filed_disclosures": int(agg["late_filed"].sum()),
        "footnote_screened_legs": int((legs["fail_step"] == "footnote screen (not private/offering/plan acquisition)").sum()),
    }
    pd.Series(summ).to_csv(C.TABLES / "disclosure_summary.csv", header=["value"])
    print(pd.Series(summ).to_string())


if __name__ == "__main__":
    main()
