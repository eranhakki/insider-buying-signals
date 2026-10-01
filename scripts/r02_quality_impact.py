"""POST-REVIEW step r02 (added 2026-09-30, after the test-period results had been seen).

Which rows of the ORIGINAL (v1) samples does the v2 price-quality rule invalidate, and why?
Re-evaluates every v1 matched row and event-study event against the corrected (v2) price
store and attributes each invalidated row to the flag class responsible.

Outputs (tables/post_review/):
  quality_removed_rows.csv       every invalidated v1 matched row / event with its reason
  quality_removed_summary.csv    counts by sample, period, year, treated/control, class
  quality_removed_totals.csv     headline counts (issuers, events, treated signals, control rows)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402
from src.incremental import balance_detailed, light_cov  # noqa: E402
from src.prices import PriceStore, event_returns  # noqa: E402

V1 = C.ROOT / "output" / "intermediate_v1"   # written by the PRICE_QUALITY=v1 run
OUT = C.TABLES / "post_review"
OUT.mkdir(parents=True, exist_ok=True)


def reason(fl_by_row, r, lo, hi):
    """Flag classes whose affected days or break fall inside (lo, hi] for ticker row r."""
    f = fl_by_row.get(r)
    if f is None:
        return ""
    hit = []
    for x in f.itertuples(index=False):
        a = x.run_start_idx if x.cls == "stale_placeholder" else x.jump_idx
        b = (x.rev_end_idx - 1) if x.cls == "reversing_spike" else x.jump_idx
        if x.cls == "plausible_move":
            continue
        if b > lo and a <= hi:
            hit.append(x.cls)
    return "|".join(sorted(set(hit)))


def v1_balance():
    """Detailed balance (raw and as-used) for the ORIGINAL v1 matched sample."""
    import json
    st = pd.read_parquet(V1 / "stacked_primary.parquet")
    cuts = {k: tuple(v) for k, v in json.loads((V1 / "dev_cuts.json").read_text()).items()}
    zs = json.loads((V1 / "zscale.json").read_text())
    for per in ["dev", "test"]:
        b = balance_detailed(st[st["period"] == per], cuts, zs)
        b.insert(0, "period", per)
        b.to_csv(OUT / f"balance_detailed_v1_{per}.csv", index=False)


def extreme_trace(ps, fl):
    """The reviewer's list: v1 matched rows with ret_21 > 200% or ret_126 > 1000%, each traced to the
    largest single-day move (>= 3x) in its covariate window and that move's class and raw evidence."""
    st = pd.read_parquet(V1 / "stacked_primary.parquet")
    ex = st[(st["ret_21"] > 2) | (st["ret_126"] > 10)].copy()
    d0 = ps.idx_on_or_before(ex["date"])
    rows = []
    for (_, x), dd in zip(ex.iterrows(), d0):
        f = fl[(fl["row"] == x["row"]) & (fl["jump_idx"] > dd - 127) & (fl["jump_idx"] <= dd)]
        top = f.iloc[np.argmax(np.abs(np.log(f["adj_ratio"])))] if len(f) else None
        rows.append({"period": x["period"], "treated": int(x["treated"]), "issuer_name": x["issuer_name"],
                     "issuer_cik": x["issuer_cik"], "ticker": x["ticker"], "signal_or_landmark_date": x["date"].date(),
                     "ret_21": x["ret_21"], "ret_126": x["ret_126"], "y60": x["y60"],
                     "move_date": None if top is None else top["jump_date"],
                     "close_before": None if top is None else top["close_before"],
                     "close_after": None if top is None else top["close_after"],
                     "move_ratio": None if top is None else top["adj_ratio"],
                     "zero_volume_days_of_prior_10": None if top is None else top["zero_volume_days_of_prior_10"],
                     "missing_days_before": None if top is None else top["missing_days_before"],
                     "split_recorded_pm3d": None if top is None else top["split_recorded_pm3d"],
                     "class": "gradual (no single-day move of 3x or more)" if top is None else top["cls"]})
    T = pd.DataFrame(rows).sort_values("ret_21", ascending=False)
    T.to_csv(OUT / "extreme_obs_trace.csv", index=False)
    print(T["class"].value_counts().to_string())


def main():
    v1_balance()
    ps = PriceStore(quality="v2")
    fl = pd.read_parquet(C.PRICE_FLAGS).rename(columns={"class": "cls"})
    fl_by_row = {r: g for r, g in fl.groupby("row")}
    extreme_trace(ps, fl)
    out = []

    st = pd.read_parquet(V1 / "stacked_primary.parquet")
    lc = light_cov(ps, st["row"].values, st["date"])
    r60 = event_returns(ps, st["row"].values, st["date"], C.ENTRY, 60)
    d0 = ps.idx_on_or_before(st["date"])
    cov_bad = (lc["ret_21"].isna() | lc["ret_126"].isna()) & st["ret_21"].notna() & st["ret_126"].notna()
    out_bad = r60["xret"].isna().values & st["y60"].notna().values
    for i in np.where(cov_bad.values | out_bad)[0]:
        x = st.iloc[i]
        out.append({"sample": "matched", "period": x["period"], "year": x["year"], "treated": int(x["treated"]),
                    "pair": x["pair"], "issuer_cik": x["issuer_cik"], "issuer_name": x["issuer_name"], "ticker": x["ticker"],
                    "date": x["date"].date(), "v1_ret_21": x["ret_21"], "v1_ret_126": x["ret_126"], "v1_y60": x["y60"],
                    "covariates_invalid": bool(cov_bad.iloc[i]), "outcome_invalid": bool(out_bad[i]),
                    "reason": reason(fl_by_row, x["row"], d0[i] - 127, d0[i] + 64)})

    ev = pd.read_parquet(V1 / "events_W30.parquet")
    ev = ev[ev["match_primary"].fillna(False).astype(bool) & (ev["px"] >= C.MIN_PRICE) & ev["row"].ge(0)]
    e60 = event_returns(ps, ev["row"].values, ev["date"], C.ENTRY, 60)
    bad = e60["xret"].isna().values & ev[f"xret_{C.ENTRY}_h60"].notna().values
    d0e = ps.idx_on_or_before(ev["date"])
    for i in np.where(bad)[0]:
        x = ev.iloc[i]
        out.append({"sample": "event study", "period": x["period"], "year": x["year"], "treated": np.nan,
                    "etype": x["etype"], "issuer_cik": x["issuer_cik"], "issuer_name": x["issuer_name"], "ticker": x["tkr"],
                    "date": x["date"].date(), "v1_y60": x[f"xret_{C.ENTRY}_h60"], "outcome_invalid": True,
                    "reason": reason(fl_by_row, x["row"], d0e[i], d0e[i] + 64)})
    R = pd.DataFrame(out)
    R.to_csv(OUT / "quality_removed_rows.csv", index=False)

    m = R[R["sample"] == "matched"]
    summ = (m.assign(role=np.where(m["treated"] == 1, "treated signal", "control row"))
             .groupby(["period", "year", "role"]).size().unstack("role", fill_value=0))
    summ.to_csv(OUT / "quality_removed_summary.csv")
    tot = []
    for per in ["dev", "test"]:
        mm = m[m["period"] == per]
        ee = R[(R["sample"] == "event study") & (R["period"] == per)]
        tot.append({"period": per,
                    "treated_signals_removed": int((mm["treated"] == 1).sum()),
                    "treated_pairs_affected_total": int(mm["pair"].nunique()),
                    "control_rows_removed": int((mm["treated"] == 0).sum()),
                    "matched_issuers_affected": int(mm["issuer_cik"].nunique()),
                    "event_study_events_removed": int(len(ee)),
                    "event_study_issuers_affected": int(ee["issuer_cik"].nunique()),
                    "matched_rows_by_class": "; ".join(f"{k}: {v}" for k, v in
                                                       mm["reason"].replace("", "other (NaN day at window end)").value_counts().items())})
    T = pd.DataFrame(tot)
    T.to_csv(OUT / "quality_removed_totals.csv", index=False)
    print(T.to_string(index=False))
    print(summ.to_string())


if __name__ == "__main__":
    main()
