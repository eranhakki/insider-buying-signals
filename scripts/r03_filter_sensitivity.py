"""POST-REVIEW step r03 (added 2026-09-30, after the test-period results had been seen).

Sensitivity of the primary estimate to a stricter purchase filter aimed at the
misclassifications found in the 35-filing EDGAR audit (docs/audit/filing_audit_35.csv).
The pre-specified filter is unchanged; this is a post-review sensitivity analysis.

Stricter filter (removes a disclosure if any of):
  A. any footnote anywhere in the filing, or the remarks, matches the original exclusion
     screen (the original screen read only footnotes attached to the purchase line);
  B. buyback / company-directed language anywhere in the filing
     ("repurchase program|share repurchase|buyback|buy-back|manage dilution|not directly for the individual");
  C. IPO-window purchase: trade date from 10 days before to 7 days after a listing start date of the
     matched Tiingo ticker (catches allocations such as Metropolitan Bank, Nov 2017).
Revised 10b5-1 flag: any footnote anywhere in the filing mentions 10b5-1 (the original flag read only the
purchase line's footnotes and missed e.g. Broadway Financial, Nov 2008).

Outputs (tables/post_review/): filter_sensitivity_counts.csv, filter_sensitivity_estimates.csv,
                               filter_false_negative_prevalence.csv, audited_cases_in_samples.csv
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src import config as C  # noqa: E402
from src.incremental import Spec, add_outcomes, build_pairs, dev_cuts, estimate, load_episodes  # noqa: E402
from src.prices import PriceStore  # noqa: E402
from s03_signals import build  # noqa: E402

OUT = C.TABLES / "post_review"
OUT.mkdir(parents=True, exist_ok=True)
BUYBACK_RE = r"repurchase program|share repurchase|buyback|buy-back|manage dilution|not directly for the individual"
OFFICER_TXT_RE = r"\bceo\b|chief|president|\bevp\b|\bsvp\b|vice president|\bcfo\b|\bcoo\b|treasurer|secretary|officer"


def accession_flags():
    fn = pd.read_parquet(C.RAW / "sec_footnotes.parquet", columns=["ACCESSION_NUMBER", "FOOTNOTE_TXT"])
    sub = pd.read_parquet(C.RAW / "sec_submission.parquet", columns=["ACCESSION_NUMBER", "REMARKS", "AFF10B5ONE"])
    txt = fn.groupby("ACCESSION_NUMBER")["FOOTNOTE_TXT"].apply(lambda s: " || ".join(s.dropna().astype(str)))
    sub = sub.drop_duplicates("ACCESSION_NUMBER").set_index("ACCESSION_NUMBER")
    t = (txt.reindex(sub.index).fillna("") + " " + sub["REMARKS"].fillna("")).str.lower()
    aff = sub["AFF10B5ONE"].fillna("").astype(str).str.strip().str.lower().isin(["1", "true", "y", "yes"])
    return pd.DataFrame({"acc_fn_exclude": t.str.contains(C.FOOTNOTE_EXCLUDE_RE, regex=True),
                         "acc_buyback": t.str.contains(BUYBACK_RE, regex=True),
                         "acc_plan": t.str.contains(C.PLAN_RE, regex=True) | aff})


def ipo_window(d: pd.DataFrame) -> pd.Series:
    sup = pd.read_parquet(C.RAW / "tiingo_supported_tickers.parquet", columns=["ticker", "startDate"])
    sup["start"] = pd.to_datetime(sup["startDate"], errors="coerce")
    starts = sup.dropna().groupby("ticker")["start"].apply(lambda s: np.array(sorted(s.values)))
    flag = []
    for t, a, b in zip(d["ticker"], d["trans_date_min"], d["trans_date_max"]):
        s = starts.get(t)
        if s is None or pd.isna(t):
            flag.append(False)
            continue
        lo, hi = np.datetime64(a) - np.timedelta64(7, "D"), np.datetime64(b) + np.timedelta64(10, "D")
        flag.append(bool(((s >= lo) & (s <= hi)).any()))
    return pd.Series(flag, index=d.index)


def disc_flags(d: pd.DataFrame, af: pd.DataFrame) -> pd.DataFrame:
    acc = d[["disc_id", "accessions"]].assign(acc=d["accessions"].str.split("|")).explode("acc")
    acc = acc.join(af, on="acc")
    g = acc.groupby("disc_id")[["acc_fn_exclude", "acc_buyback", "acc_plan"]].any()
    d = d.join(g, on="disc_id")
    d["ipo_window"] = ipo_window(d)
    return d


def run(ps, spec, label, rows, zs):
    ep = load_episodes(spec)
    st, _ = build_pairs(ps, ep, spec, zs)
    st = add_outcomes(ps, st, spec)
    cuts = dev_cuts(st[st["period"] == "dev"])
    for per in ["dev", "test"]:
        for h in C.HORIZONS:
            r = estimate(st[st["period"] == per], h, cuts)
            r.update({"check": label, "period": per})
            rows.append(r)
    return st


def main():
    d = pd.read_parquet(C.INTER / "disclosures_matched.parquet")
    d = disc_flags(d, accession_flags())
    d["strict_drop"] = d["acc_fn_exclude"] | d["acc_buyback"] | d["ipo_window"]
    per = np.where(d["filing_date"] <= C.DEV_END, "dev", "test")
    cnt = pd.DataFrame({
        "reason": ["A. exclusion wording anywhere in filing", "B. buyback / company-directed wording",
                   "C. IPO-window purchase", "any of A-C (stricter filter)", "revised 10b5-1 flag (filing-wide)",
                   "original 10b5-1 flag"],
        "disclosures": [int(d.acc_fn_exclude.sum()), int(d.acc_buyback.sum()), int(d.ipo_window.sum()),
                        int(d.strict_drop.sum()), int((d.acc_plan | d.plan_10b5_1).sum()), int(d.plan_10b5_1.sum())],
        "priced_disclosures": [int((d.acc_fn_exclude & d.match_primary).sum()), int((d.acc_buyback & d.match_primary).sum()),
                               int((d.ipo_window & d.match_primary).sum()), int((d.strict_drop & d.match_primary).sum()),
                               int(((d.acc_plan | d.plan_10b5_1) & d.match_primary).sum()), int((d.plan_10b5_1 & d.match_primary).sum())],
    })
    cnt["share_of_disclosures"] = cnt["disclosures"] / len(d)
    cnt.to_csv(OUT / "filter_sensitivity_counts.csv", index=False)
    print(cnt.to_string(index=False))

    # episodes under the stricter filter, and with the revised plan flag
    ep_s = build(d[~d["strict_drop"]].drop(columns=["acc_fn_exclude", "acc_buyback", "acc_plan", "ipo_window", "strict_drop"]), C.WINDOW)
    ep_s.to_parquet(C.INTER / "episodes_W30_strictfilter.parquet", index=False)
    d2 = d.copy()
    d2["plan_10b5_1"] = d2["plan_10b5_1"] | d2["acc_plan"]
    ep_p = build(d2.drop(columns=["acc_fn_exclude", "acc_buyback", "acc_plan", "ipo_window", "strict_drop"]), C.WINDOW)
    ep_p.to_parquet(C.INTER / "episodes_W30_planfix.parquet", index=False)

    ps = PriceStore()
    rows = []
    run(ps, Spec(), "Primary (pre-specified filter)", rows, None)
    run(ps, Spec(episodes_file="episodes_W30_strictfilter.parquet"), "Stricter filter A-C (post-review)", rows, None)
    run(ps, Spec(episodes_file="episodes_W30_planfix.parquet", drop_plan=True),
        "Excluding 10b5-1 with revised filing-wide flag (post-review)", rows, None)
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "filter_sensitivity_estimates.csv", index=False)
    print(res[["check", "period", "h", "n_treated", "match_diff", "reg_coef", "reg_lo", "reg_hi", "reg_p"]].round(4).to_string(index=False))

    # prevalence of the two false-negative patterns among all P-code legs
    legs = pd.read_parquet(C.INTER / "legs_all.parquet", columns=["ACCESSION_NUMBER", "fail_step", "SECURITY_TITLE", "DOCUMENT_TYPE"])
    own = pd.read_parquet(C.RAW / "sec_reportingowner.parquet", columns=["ACCESSION_NUMBER", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TXT"])
    own["other_officer_title"] = (~own["RPTOWNER_RELATIONSHIP"].fillna("").str.upper().str.contains("OFFICER|DIRECTOR")
                                  & own["RPTOWNER_TXT"].fillna("").str.lower().str.contains(OFFICER_TXT_RE, regex=True))
    oo = own.groupby("ACCESSION_NUMBER")["other_officer_title"].any()
    l4 = legs[legs["DOCUMENT_TYPE"] == "4"]
    fnp = pd.DataFrame({
        "pattern": ["owner ticked 'Other' but gives an officer title (e.g. J.B. Hunt EVP)",
                    "security titled 'LLC interest' (e.g. Macquarie Infrastructure)"],
        "form4_P_legs_excluded": [int((l4["fail_step"].eq("owner is officer or director") & l4["ACCESSION_NUMBER"].map(oo).fillna(False)).sum()),
                                  int((l4["fail_step"].eq("common/ordinary equity title")
                                       & l4["SECURITY_TITLE"].fillna("").str.lower().str.contains(r"limited liability company interest|llc interest")).sum())],
    })
    fnp["as_share_of_eligible_legs"] = fnp["form4_P_legs_excluded"] / int((legs["fail_step"] == "").sum())
    fnp.to_csv(OUT / "filter_false_negative_prevalence.csv", index=False)
    print(fnp.to_string(index=False))

    # where did the audited misclassifications end up?
    aud = pd.read_csv(C.ROOT / "docs" / "audit" / "filing_audit_35.csv")
    aud = aud[aud["verdict"].isin(["false_positive", "probable_false_positive", "flag_error"])]
    ev = pd.read_parquet(C.INTER / "events_W30.parquet", columns=["issuer_cik", "date", "etype", "match_primary", "px"])
    st = pd.read_parquet(C.INTER / "stacked_primary.parquet", columns=["issuer_cik", "date", "treated"])
    rows = []
    for _, a in aud.iterrows():
        x = d[d["accessions"].str.contains(a["ACCESSION_NUMBER"], regex=False)]
        if x.empty:
            rows.append({"accession": a["ACCESSION_NUMBER"], "issuer": a["ISSUERNAME"], "verdict": a["verdict"], "note": "not an eligible disclosure"})
            continue
        x = x.iloc[0]
        e = ev[(ev["issuer_cik"] == x["issuer_cik"]) & (ev["date"] == x["filing_date"])]
        m = st[(st["issuer_cik"] == x["issuer_cik"]) & (st["date"] == x["filing_date"])]
        rows.append({"accession": a["ACCESSION_NUMBER"], "issuer": a["ISSUERNAME"], "verdict": a["verdict"],
                     "filing_date": x["filing_date"].date(), "priced": bool(x["match_primary"]),
                     "in_event_study_as": "|".join(e["etype"]) if len(e) and (e["px"] >= C.MIN_PRICE).any() else "",
                     "in_matched_test_as": "treated" if (m["treated"] == 1).any() else ("control" if len(m) else ""),
                     "caught_by_stricter_filter": bool(x["strict_drop"]),
                     "caught_by_revised_plan_flag": bool(x["acc_plan"])})
    pd.DataFrame(rows).to_csv(OUT / "audited_cases_in_samples.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
