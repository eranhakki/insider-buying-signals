"""POST-REVIEW step r01 (added 2026-09-30, after the test-period results had been seen).

Scan every Tiingo series in the price store for one-day moves of 3x or more
(either direction) in the adjusted close, classify each on data evidence, and
write the corrections the v2 price store applies.

Classes, applied in this order:
  stale_placeholder   the price is constant with zero reported volume on >= 5 of the 10 trading days before
                      the move: a dormant quote (e.g. SKYX at $0.001 before its Nasdaq listing), not trades.
                      FIX: the stale run is set to missing.
  data_gap_splice     >= 20 missing trading days immediately before the move: two histories joined (e.g. old
                      equity cancelled in a bankruptcy and new equity issued). FIX: returns may not span it
                      (break), in covariate and outcome windows.
  reversing_spike     the move is undone (net change < 1/3 of the jump, in logs) within 3 trading days:
                      a bad print. FIX: the spike days are set to missing.
  implausible_magnitude  none of the above, no split recorded within +-3 days, and a one-day move of 10x or
                      more up or -90% or worse. Cannot be resolved (often an unrecorded reverse split in a
                      sub-$1 OTC stock). RULE: treated as a break in *covariate* windows only (pre-signal,
                      information known at the time); outcomes are not screened on their own size.
  plausible_move      3x-10x moves with none of the error signatures: kept (e.g. KBIO Nov 2015, KRTX Nov 2019).

Outputs: intermediate/price_flags.parquet; tables/post_review/price_jumps_classified.csv,
         tables/post_review/price_flags_summary.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402
from src.prices import PriceStore  # noqa: E402

OUT = C.TABLES / "post_review"
OUT.mkdir(parents=True, exist_ok=True)
JUMP = np.log(3.0)
IMPLAUSIBLE = np.log(10.0)


def load_raw(ps):
    p = pd.read_parquet(C.RAW / "tiingo_prices.parquet", columns=["ticker", "date", "volume", "splitFactor"])
    p["date"] = pd.to_datetime(p["date"])
    p = p[p["date"].isin(ps.dates)]
    di = pd.Series(np.arange(len(ps.dates)), index=ps.dates)
    shape = (len(ps.tickers), len(ps.dates))
    vol = np.full(shape, np.nan, dtype=np.float32)
    spl = np.ones(shape, dtype=np.float32)
    r = p["ticker"].map(ps.tix).values
    c = di.reindex(p["date"]).values
    vol[r, c] = p["volume"].values
    spl[r, c] = p["splitFactor"].fillna(1).values
    return vol, spl


def med(x):
    x = x[~np.isnan(x)]
    return float(np.median(x)) if len(x) else np.nan


def classify(ps, vol, spl, r, j):
    a = ps.adj[r].astype(float)
    c = ps.close[r].astype(float)
    prev = np.where(~np.isnan(a[:j]))[0]
    i = prev[-1]
    gap = j - i - 1
    lr = np.log(a[j] / a[i])
    back = prev[-10:]
    v = vol[r, back]
    zero_days = int(np.sum(v == 0))
    stale = zero_days >= 5 and np.nanmax(c[back]) == np.nanmin(c[back])
    run_start = i
    if stale:   # extend back over the whole constant zero-volume run
        k = len(prev) - 1
        while k > 0 and vol[r, prev[k - 1]] == 0 and c[prev[k - 1]] == c[i]:
            k -= 1
        run_start = prev[k]
    after = np.where(~np.isnan(a[j + 1: j + 4]))[0]
    rev_end = None
    for t in after:
        k = j + 1 + t
        if abs(np.log(a[k] / a[i])) < abs(lr) / 3:
            rev_end = k
            break
    split_rec = bool(np.any(spl[r, max(0, j - 3): j + 4] != 1))
    if stale:
        cls = "stale_placeholder"
    elif gap >= 20:
        cls = "data_gap_splice"
    elif rev_end is not None:
        cls = "reversing_spike"
    elif abs(lr) >= IMPLAUSIBLE and not split_rec:
        cls = "implausible_magnitude"
    else:
        cls = "plausible_move"
    vb, va = med(vol[r, max(0, j - 22): j - 2]), med(vol[r, j + 2: j + 22])
    return {"ticker": ps.tickers[r], "row": r, "jump_idx": j, "prev_idx": i, "run_start_idx": run_start,
            "rev_end_idx": rev_end, "prev_date": ps.dates[i].date(), "jump_date": ps.dates[j].date(),
            "close_before": c[i], "close_after": c[j], "adj_before": a[i], "adj_after": a[j],
            "adj_ratio": float(np.exp(lr)), "missing_days_before": int(gap), "zero_volume_days_of_prior_10": zero_days,
            "volume_on_jump_day": float(vol[r, j]), "median_volume_20d_before": vb, "median_volume_20d_after": va,
            "split_recorded_pm3d": split_rec, "class": cls}


def main():
    ps = PriceStore(quality="v1")          # detection always runs on the uncorrected prices
    vol, spl = load_raw(ps)
    A = pd.DataFrame(ps.adj.astype(float)).ffill(axis=1).values
    d = np.abs(np.diff(np.log(A), axis=1))
    rr, jj = np.where(d > JUMP)
    jj = jj + 1
    keep = ~np.isnan(ps.adj[rr, jj])       # the move lands on a real observation
    recs = [classify(ps, vol, spl, r, j) for r, j in zip(rr[keep], jj[keep])]
    J = pd.DataFrame(recs)
    J.to_parquet(C.INTER / "price_flags.parquet", index=False)
    J.drop(columns=["row"]).sort_values(["class", "ticker", "jump_date"]).to_csv(OUT / "price_jumps_classified.csv", index=False)
    s = J.groupby("class").agg(moves=("ticker", "size"), tickers=("ticker", "nunique"),
                               median_ratio=("adj_ratio", "median"))
    s.to_csv(OUT / "price_flags_summary.csv")
    print(s)


if __name__ == "__main__":
    main()
