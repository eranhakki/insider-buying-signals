"""Step 8 (secondary, pre-listed in plan section 9): does adding the
second-buyer indicator to a simple return model fitted on 2006-2018 improve
out-of-sample prediction in 2019-2026?

Model: OLS of winsorised 60-day SPY-adjusted return on the known-at-time
covariates (no year dummies, since they cannot be used out of sample), fitted on
the development matched sample with and without the treated indicator.
Evaluation on the test matched sample: out-of-sample R^2 (vs the development
mean), and the monthly rank IC (Spearman) averaged over months.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402
from src.incremental import REG_COVS  # noqa: E402


def design(s, cuts, with_treated):
    X = s[REG_COVS].copy()
    for c in ["ret_21", "ret_126", "vol_60"]:
        X[c] = X[c].clip(*cuts[c])
    X["officer_init"] = (s["init_role"] == "officer").astype(float)
    X["top_init"] = s["init_top"].astype(float)
    if with_treated:
        X["treated"] = s["treated"].astype(float)
    X.insert(0, "const", 1.0)
    return X


def main():
    st = pd.read_parquet(C.INTER / "stacked_primary.parquet")
    cuts = {k: tuple(v) for k, v in json.loads((C.INTER / "dev_cuts.json").read_text()).items()}
    h = C.PRIMARY_H
    st["y"] = st[f"y{h}"].clip(*cuts[f"y{h}"])
    dev = st[(st["period"] == "dev")].dropna(subset=["y"] + REG_COVS)
    test = st[(st["period"] == "test")].dropna(subset=["y"] + REG_COVS)
    rows = []
    for wt in (False, True):
        Xd, Xt = design(dev, cuts, wt), design(test, cuts, wt)
        b, *_ = np.linalg.lstsq(Xd.values * np.sqrt(dev["w"].values)[:, None], dev["y"].values * np.sqrt(dev["w"].values), rcond=None)
        pred = Xt.values @ b
        y = test["y"].values
        w = test["w"].values
        base = np.average(dev["y"], weights=dev["w"])
        r2 = 1 - np.sum(w * (y - pred) ** 2) / np.sum(w * (y - base) ** 2)
        tt = test.assign(pred=pred)
        ics = tt.groupby("month").apply(lambda g: spearmanr(g["pred"], g["y"]).statistic if len(g) >= 20 else np.nan).dropna()
        rows.append({"model": "covariates + second-buyer flag" if wt else "covariates only",
                     "treated_coef_dev": b[-1] if wt else np.nan, "oos_r2": r2, "mean_monthly_rank_ic": ics.mean(),
                     "ic_t": ics.mean() / (ics.std() / np.sqrt(len(ics))), "months": len(ics), "n_test_rows": len(test)})
    res = pd.DataFrame(rows)
    res.loc[len(res)] = {"model": "difference (with flag − without)", "oos_r2": res.oos_r2[1] - res.oos_r2[0],
                         "mean_monthly_rank_ic": res.mean_monthly_rank_ic[1] - res.mean_monthly_rank_ic[0]}
    res.to_csv(C.TABLES / "predictive_check.csv", index=False)
    print(res.round(5).to_string(index=False))


if __name__ == "__main__":
    main()
