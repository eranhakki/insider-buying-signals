"""Step 6: every pre-listed robustness check (ANALYSIS_PLAN.md section 11),
reported for both periods whatever it shows.

Output: tables/robustness.csv, tables/robustness_by_year.csv, tables/leave_one_year_out.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402
from src.incremental import Spec, add_outcomes, build_pairs, dev_cuts, estimate, load_episodes  # noqa: E402
from src.prices import PriceStore  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from s03_signals import build  # noqa: E402

MIN_N = 100


def est_rows(st, label, group, cuts=None, periods=("dev", "test")):
    cuts = cuts or dev_cuts(st[st["period"] == "dev"])
    out = []
    for per in periods:
        s = st[st["period"] == per]
        for h in C.HORIZONS:
            if s.empty or (s["treated"] == 1).sum() < 30:
                out.append({"group": group, "check": label, "period": per, "h": h, "n_treated": int((s["treated"] == 1).sum())})
                continue
            r = estimate(s, h, cuts)
            r.update({"group": group, "check": label, "period": per})
            out.append(r)
    return out


def subset_pairs(st, mask_treated):
    keep = st.loc[(st["treated"] == 1) & mask_treated, "pair"]
    return st[st["pair"].isin(keep)]


def amend_episodes():
    """Episodes rebuilt with 4/A-only purchases added at their amendment filing date."""
    d = pd.read_parquet(C.INTER / "disclosures_matched.parquet")
    a = pd.read_parquet(C.INTER / "amend_only.parquet")
    a = a[a["filing_date"].between("2006-01-01", C.TEST_END)]
    tick = (d[d["match_primary"]].groupby("issuer_cik")["ticker"].agg(lambda s: s.mode().iloc[0]))
    g = a.groupby("ACCESSION_NUMBER").agg(
        issuer_cik=("issuer_cik", "first"), issuer_name=("ISSUERNAME", "first"), sic=("sic", "first"),
        filing_date=("filing_date", "first"), shares=("shares", "sum"), value=("value", "sum"),
        owners=("owners", "first"), any_officer=("any_officer", "max"), any_top=("any_top", "max"),
        plan_10b5_1=("plan_10b5_1", "max"), filing_lag_bd=("filing_lag_bd", "max")).reset_index()
    g["disc_id"] = "A" + g["ACCESSION_NUMBER"]
    g["late_filed"] = g["filing_lag_bd"] > 4
    g["ticker"] = g["issuer_cik"].map(tick)
    g["match_primary"] = g["ticker"].notna()
    g["match_strict"] = g["match_primary"]
    g["any_officer"] = g["any_officer"].fillna(False).astype(bool)
    g["any_top"] = g["any_top"].fillna(False).astype(bool)
    cols = [c for c in d.columns if c in g.columns]
    dd = pd.concat([d, g[cols]], ignore_index=True)
    ep = build(dd, C.WINDOW)
    ep.to_parquet(C.INTER / "episodes_W30_amend.parquet", index=False)
    return len(g)


def main():
    ps = PriceStore()
    prim = pd.read_parquet(C.INTER / "stacked_primary.parquet")
    pc = dev_cuts(prim[prim["period"] == "dev"])
    rows = est_rows(prim, "Primary specification", "0 primary", pc)

    # --- outcome-only variants on the primary matched pairs
    base_cols = [c for c in prim.columns if not c.startswith(("y", "raw", "incomplete", "delisted"))
                 and c not in ("ret_21", "ret_126", "log_dv", "log_price", "vol_60", "px", "log_init_value",
                               "period", "month", "year", "sic_div", "spy_ret_252", "spy_vol_60")]
    pairs = prim[base_cols].copy()
    variants = [
        ("Entry at t+1 open", "4 timing", Spec(rule="t1_open")),
        ("Entry at t+2 close", "4 timing", Spec(rule="t2_close")),
        ("Entry at t+0 close (upper bound, may precede publication)", "4 timing", Spec(rule="t0_close")),
        ("Delisting: extra -30% at last price", "8 delisting", Spec(delist="minus30")),
        ("Delisting: complete windows only", "8 delisting", Spec(delist="complete_only")),
        ("Benchmark IWM", "11 benchmark", Spec(bench="IWM")),
        ("Benchmark sector SPDR ETF", "11 benchmark", Spec(bench="sector")),
    ]
    for label, grp, spec in variants:
        st = add_outcomes(ps, pairs.copy(), spec)
        rows += est_rows(st, label, grp)
        print("done", label, flush=True)

    # --- variants that change the sample (re-matched)
    n_amend = amend_episodes()
    rematch = [
        ("Cluster window 14 days", "1 window", Spec(W=14)),
        ("Cluster window 60 days", "1 window", Spec(W=60)),
        ("Liquid only: price >= $5 and median $ volume >= $1m", "5 liquidity/match", Spec(liquid_only=True)),
        ("Strict price match (ratio 0.9-1.1)", "5 liquidity/match", Spec(strict_match=True)),
        ("Excluding 10b5-1 plan purchases", "9 filings", Spec(drop_plan=True)),
        ("Excluding late filings (> 4 business days)", "9 filings", Spec(drop_late=True)),
        (f"Adding 4/A-only purchases ({n_amend:,} amendment disclosures)", "9 filings",
         Spec(episodes_file="episodes_W30_amend.parquet")),
    ]
    zs = None
    for label, grp, spec in rematch:
        ep = load_episodes(spec)
        st, _ = build_pairs(ps, ep, spec, zs)
        st = add_outcomes(ps, st, spec)
        rows += est_rows(st, label, grp)
        print("done", label, flush=True)

    # --- subsets of the primary matched sample (treated-row splits)
    t = prim[prim["treated"] == 1]
    dev_t = t[t["period"] == "dev"]
    med_val = dev_t["second_value"].median()
    vol_med = dev_t["spy_vol_60"].median()
    top1 = t.groupby("issuer_cik").size().sort_values(ascending=False)
    top1 = set(top1.index[: max(1, int(np.ceil(0.01 * len(top1))))])
    splits = [
        ("Second buyer is an officer", "2 roles", prim["second_role"].eq("officer")),
        ("Second buyer is director-only", "2 roles", prim["second_role"].eq("director_only")),
        ("Initial buyer is an officer", "2 roles", prim["init_role"].eq("officer")),
        ("Initial buyer is director-only", "2 roles", prim["init_role"].eq("director_only")),
        ("Second buyer is CEO/CFO/President/Chair", "2 roles", prim["second_top"].astype(bool)),
        (f"Second purchase below dev median (${med_val:,.0f})", "3 size", prim["second_value"] < med_val),
        (f"Second purchase at/above dev median (${med_val:,.0f})", "3 size", prim["second_value"] >= med_val),
        ("SPY trailing 12m return < 0", "6 market", prim["spy_ret_252"] < 0),
        ("SPY trailing 12m return >= 0", "6 market", prim["spy_ret_252"] >= 0),
        ("SPY 60d volatility above dev median", "6 market", prim["spy_vol_60"] > vol_med),
        ("SPY 60d volatility at/below dev median", "6 market", prim["spy_vol_60"] <= vol_med),
        ("Excluding 2008-2009 and 2020", "7 calendar", ~prim["year"].isin([2008, 2009, 2020])),
        ("Dropping the 1% of issuers with most signals", "10 concentration", ~prim["issuer_cik"].isin(top1)),
        ("Lag 1-7 days (second buyer within a week)", "12 lag (descriptive)", prim["lag_k"] <= 7),
        ("Lag 8-30 days", "12 lag (descriptive)", prim["lag_k"] > 7),
    ]
    for label, grp, mask in splits:
        rows += est_rows(subset_pairs(prim, mask), label, grp, pc)

    res = pd.DataFrame(rows)
    res["too_small"] = res["n_treated"] < MIN_N
    res.to_csv(C.TABLES / "robustness.csv", index=False)

    # --- by year and leave-one-year-out (primary sample, h = 60)
    by = []
    for y in sorted(prim["year"].unique()):
        s = subset_pairs(prim, prim["year"].eq(y))
        per = s["period"].iloc[0] if len(s) else ""
        if (s["treated"] == 1).sum() >= 30:
            r = estimate(s, C.PRIMARY_H, pc)
            r.update({"year": y, "period": per})
            by.append(r)
    pd.DataFrame(by).to_csv(C.TABLES / "robustness_by_year.csv", index=False)
    loo = []
    for per in ("dev", "test"):
        s0 = prim[prim["period"] == per]
        for y in sorted(s0["year"].unique()):
            s = subset_pairs(s0, ~s0["year"].eq(y))
            r = estimate(s, C.PRIMARY_H, pc)
            r.update({"dropped_year": y, "period": per})
            loo.append(r)
    pd.DataFrame(loo).to_csv(C.TABLES / "leave_one_year_out.csv", index=False)
    cols = ["group", "check", "period", "h", "n_treated", "match_diff", "reg_coef", "reg_lo", "reg_hi", "reg_p", "too_small"]
    print(res[res["h"] == 60][cols].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
