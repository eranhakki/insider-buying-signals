"""Inference helpers: two-way clustered OLS/WLS, clustered means, block bootstrap."""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm


def winsor(x: pd.Series, lo: float, hi: float) -> pd.Series:
    return x.clip(lower=lo, upper=hi)


def _codes(s) -> np.ndarray:
    return pd.factorize(pd.Series(s).astype(str))[0]


def cluster_ols(y, X, g1, g2=None, w=None):
    """OLS/WLS with one- or two-way cluster-robust covariance (Cameron-Gelbach-Miller)."""
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    model = sm.WLS(y, X, weights=w) if w is not None else sm.OLS(y, X)
    if g2 is None:
        return model.fit(cov_type="cluster", cov_kwds={"groups": _codes(g1)})
    groups = np.column_stack([_codes(g1), _codes(g2)])
    return model.fit(cov_type="cluster", cov_kwds={"groups": groups})


def clustered_mean(y, g1, g2=None) -> dict:
    """Mean of y with a two-way clustered SE (regression on a constant)."""
    y = pd.Series(y).astype(float)
    ok = y.notna().values
    yv = y.values[ok]
    if len(yv) < 3:
        return {"n": len(yv), "mean": np.nan, "se": np.nan, "lo": np.nan, "hi": np.nan, "t": np.nan}
    X = np.ones((len(yv), 1))
    r = cluster_ols(yv, X, np.asarray(g1)[ok], None if g2 is None else np.asarray(g2)[ok])
    m, se = r.params[0], r.bse[0]
    return {"n": len(yv), "mean": m, "se": se, "lo": m - 1.96 * se, "hi": m + 1.96 * se, "t": m / se}


def describe(y, g1, g2) -> dict:
    y = pd.Series(y).astype(float)
    d = clustered_mean(y, g1, g2)
    d.update({"median": y.median(), "share_pos": (y > 0).mean(), "p10": y.quantile(0.1), "p90": y.quantile(0.9)})
    return d


def block_bootstrap(stat_fn, blocks: pd.Series, n: int, seed: int) -> np.ndarray:
    """Resample whole blocks (e.g. calendar months) with replacement."""
    rng = np.random.default_rng(seed)
    ub = blocks.unique()
    idx_by_block = {b: np.where(blocks.values == b)[0] for b in ub}
    out = np.empty(n)
    for i in range(n):
        pick = rng.choice(ub, size=len(ub), replace=True)
        rows = np.concatenate([idx_by_block[b] for b in pick])
        out[i] = stat_fn(rows)
    return out


def newey_west_mean(x: pd.Series, lags: int = 20) -> dict:
    x = pd.Series(x).dropna().astype(float)
    r = sm.OLS(x.values, np.ones((len(x), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"n_days": len(x), "mean": r.params[0], "se": r.bse[0], "t": r.tvalues[0]}


def capm_alpha(port: pd.Series, mkt: pd.Series, lags: int = 20) -> dict:
    df = pd.concat([port, mkt], axis=1, keys=["p", "m"]).dropna()
    r = sm.OLS(df["p"].values, sm.add_constant(df["m"].values)).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"alpha": r.params[0], "alpha_se": r.bse[0], "alpha_t": r.tvalues[0], "beta": r.params[1], "n_days": len(df)}
