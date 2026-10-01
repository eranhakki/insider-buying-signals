"""Landmark-matching test of the incremental information in a second buyer.

For each second-buyer signal i (episode start F_i, lag k_i = S_i - F_i days) the
controls are other issuers' single-start episodes that began within +-60 days of
F_i and were still single-buyer at F + k_i. All covariates for controls are
measured at their landmark L = F + k_i, i.e. with information available then.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C
from .prices import PriceStore, covariates, event_returns
from .sectors import sector_etf_at
from .stats import block_bootstrap, cluster_ols, clustered_mean


def period_of(d):
    d = pd.to_datetime(pd.Series(d))
    return np.select([d.between(C.DEV_START, C.DEV_END), d.between(C.TEST_START, C.TEST_END)],
                     ["dev", "test"], default="out")


def light_cov(ps: PriceStore, rows, dates) -> pd.DataFrame:
    """Matching covariates only (fast): ret_21, ret_126, log_dv, px."""
    d0 = ps.idx_on_or_before(dates)
    n = len(rows)
    out = {k: np.full(n, np.nan) for k in ("ret_21", "ret_126", "log_dv", "px")}
    ok = (rows >= 0) & (d0 >= 130)
    ii = np.where(ok)[0]
    r, d = rows[ii], d0[ii]
    p0 = ps.adj[r, d].astype(float)
    c0 = ps.close[r, d].astype(float)
    for back in range(1, 6):
        m = np.isnan(p0)
        p0[m] = ps.adj[r[m], d[m] - back]
        m = np.isnan(c0)
        c0[m] = ps.close[r[m], d[m] - back]
    out["ret_21"][ii] = p0 / ps.adj[r, d - 21] - 1
    out["ret_126"][ii] = p0 / ps.adj[r, d - 126] - 1
    out["log_dv"][ii] = np.log(np.maximum(ps.dvmed60[r, d].astype(float), 1.0))
    out["px"][ii] = c0
    if ps.quality == "v2":   # POST-REVIEW: same break rule as prices.covariates
        brk = ps.spans_break(r, d - 127, d, "cov")
        out["ret_21"][ii[brk]] = np.nan
        out["ret_126"][ii[brk]] = np.nan
    return pd.DataFrame(out)


@dataclass
class Spec:
    name: str = "primary"
    W: int = C.WINDOW
    rule: str = C.ENTRY
    horizons: tuple = tuple(C.HORIZONS)
    bench: str = "SPY"            # SPY | IWM | sector
    delist: str = "last_price"    # last_price | minus30 | complete_only
    strict_match: bool = False
    liquid_only: bool = False
    drop_plan: bool = False
    drop_late: bool = False
    episodes_file: str | None = None
    treated_filter: str | None = None   # pandas query applied to treated rows before matching
    notes: str = ""


def load_episodes(spec: Spec) -> pd.DataFrame:
    f = spec.episodes_file or f"episodes_W{spec.W}.parquet"
    ep = pd.read_parquet(C.INTER / f)
    ep = ep[~ep["same_day_cluster"] & ep["ticker"].notna() & ep["init_match_primary"].fillna(False)].copy()
    if spec.strict_match:
        ep = ep[ep["init_match_strict"].fillna(False)]
    if spec.drop_plan:
        ep = ep[~ep["init_plan"]]
    if spec.drop_late:
        ep = ep[~ep["init_late"]]
    ep = ep.reset_index(drop=True)
    ep["ep_id"] = np.arange(len(ep))
    ep["n_repeats"] = ep["repeat_dates"].apply(len)
    return ep


def build_pairs(ps: PriceStore, ep: pd.DataFrame, spec: Spec, zscale: dict | None = None):
    rows_all = ps.row(ep["ticker"])
    ep["row"] = rows_all
    tr = ep[ep["has_second"] & ep["lag"].ge(1)].copy()
    if spec.strict_match:
        tr = tr[tr["second_match_strict"].fillna(False)]
    if spec.drop_plan:
        tr = tr[~tr["second_plan"].astype(bool)]
    if spec.drop_late:
        tr = tr[~tr["second_late"].astype(bool)]
    tr["date"] = tr["S"]
    tcov = light_cov(ps, tr["row"].values, tr["date"])
    tr = pd.concat([tr.reset_index(drop=True), tcov], axis=1)
    tr["period"] = period_of(tr["date"])
    tr = tr[(tr["px"] >= C.MIN_PRICE) & tr[C.MATCH_VARS[:3]].notna().all(1) & (tr["period"] != "out")]
    if spec.liquid_only:
        tr = tr[(tr["px"] >= C.LIQ_PRICE) & (np.exp(tr["log_dv"]) >= C.LIQ_DV)]
    if spec.treated_filter:
        tr = tr.query(spec.treated_filter)
    tr["log_init_value"] = np.log(tr["init_value"].clip(lower=1))

    # candidate pool at each needed lag
    ep_sorted = ep.sort_values("F").reset_index(drop=True)
    Fv = ep_sorted["F"].values.astype("datetime64[D]")
    pools = {}
    for k in sorted(tr["lag"].unique()):
        L = ep_sorted["F"] + pd.to_timedelta(k, "D")
        elig = (~ep_sorted["has_second"]) | (ep_sorted["lag"] > k)
        c = ep_sorted[elig].copy()
        c["date"] = L[elig]
        cc = light_cov(ps, c["row"].values, c["date"])
        c = pd.concat([c.reset_index(drop=True), cc], axis=1)
        c["period"] = period_of(c["date"])
        c = c[(c["px"] >= C.MIN_PRICE) & c[C.MATCH_VARS[:3]].notna().all(1)]
        if spec.liquid_only:
            c = c[(c["px"] >= C.LIQ_PRICE) & (np.exp(c["log_dv"]) >= C.LIQ_DV)]
        c["log_init_value"] = np.log(c["init_value"].clip(lower=1))
        pools[k] = c.sort_values("F").reset_index(drop=True)

    # standardisation (development-period treated rows, winsorised 1/99)
    if zscale is None:
        dv = tr[tr["period"] == "dev"]
        zscale = {}
        for v in C.MATCH_VARS:
            lo, hi = dv[v].quantile([0.01, 0.99])
            x = dv[v].clip(lo, hi)
            zscale[v] = (lo, hi, x.mean(), x.std())

    def z(df):
        return np.column_stack([(df[v].clip(zscale[v][0], zscale[v][1]) - zscale[v][2]) / zscale[v][3]
                                for v in C.MATCH_VARS])

    pairs = []
    win = np.timedelta64(C.CONTROL_START_WINDOW, "D")
    for k, g in tr.groupby("lag"):
        pool = pools[k]
        if pool.empty:
            continue
        pF = pool["F"].values.astype("datetime64[D]")
        Zp = z(pool)
        Zt = z(g)
        for j, (i, t) in enumerate(g.iterrows()):
            F = np.datetime64(t["F"], "D")
            a, b = np.searchsorted(pF, F - win, "left"), np.searchsorted(pF, F + win, "right")
            if b <= a:
                continue
            cand = np.arange(a, b)
            cand = cand[(pool["issuer_cik"].values[cand] != t["issuer_cik"])
                        & (pool["period"].values[cand] == t["period"])]
            if len(cand) == 0:
                continue
            dist = np.sqrt(((Zp[cand] - Zt[j]) ** 2).sum(1))
            pick = cand[np.argsort(dist)[: C.N_CONTROLS]]
            pairs.append((t["ep_id"], k, pool["ep_id"].values[pick], dist[np.argsort(dist)[: C.N_CONTROLS]]))
    # assemble stacked sample
    trows, crows = [], []
    for pid, (tid, k, cids, d) in enumerate(pairs):
        trows.append({"pair": pid, "ep_id": tid, "treated": 1, "lag_k": k, "w": 1.0, "dist": 0.0})
        for c, dd in zip(cids, d):
            crows.append({"pair": pid, "ep_id": c, "treated": 0, "lag_k": k, "w": 1.0 / len(cids), "dist": dd})
    st = pd.DataFrame(trows + crows)
    st = st.merge(ep.drop(columns=["repeat_dates"]).assign(
        repeat_list=ep["repeat_dates"]), on="ep_id", how="left")
    st["date"] = np.where(st["treated"] == 1, st["S"], st["F"] + pd.to_timedelta(st["lag_k"], "D"))
    st["date"] = pd.to_datetime(st["date"])
    st["n_repeats_asof"] = [sum(1 for x in lst if x <= dte) for lst, dte in zip(st["repeat_list"], st["date"])]
    st = st.drop(columns=["repeat_list"])
    return st, zscale


def add_outcomes(ps: PriceStore, st: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    rows = st["row"].values
    cov = covariates(ps, rows, st["date"])
    st = pd.concat([st.reset_index(drop=True), cov], axis=1)
    st["log_init_value"] = np.log(st["init_value"].clip(lower=1))
    st["period"] = period_of(st["date"])
    st["month"] = st["date"].dt.to_period("M").astype(str)
    st["year"] = st["date"].dt.year
    st["sic_div"] = st["sic"].fillna("").astype(str).str[:1].replace("", "X")
    brow = None
    bench = spec.bench
    if spec.bench == "sector":
        brow = ps.row([sector_etf_at(s, d) for s, d in zip(st["sic"], st["date"])])
        bench = "SPY"
    for h in spec.horizons:
        r = event_returns(ps, rows, st["date"], spec.rule, h, bench=bench, bench_rows=brow)
        x = r["xret"].values.copy()
        if spec.delist == "minus30":
            dl = r["delisted"].values & ~np.isnan(x)
            x[dl] = (1 + r["ret"].values[dl]) * (1 + C.DELIST_RET) - 1 - r["bench_ret"].values[dl]
        if spec.delist == "complete_only":
            x[r["incomplete"].values] = np.nan
        st[f"y{h}"] = x
        st[f"raw{h}"] = r["ret"].values
        st[f"incomplete{h}"] = r["incomplete"].values
        st[f"delisted{h}"] = r["delisted"].values
    # market state at the treated date (for regime splits)
    spy = ps.tix[C.BENCH]
    d0 = ps.idx_on_or_before(st["date"])
    st["spy_ret_252"] = ps.adj[spy, d0] / ps.adj[spy, np.maximum(d0 - 252, 0)] - 1
    lr = np.diff(np.log(ps.adj[spy].astype(float)))
    vol = pd.Series(lr).rolling(60).std().values * np.sqrt(252)
    st["spy_vol_60"] = vol[np.maximum(d0 - 1, 0)]
    return st


REG_COVS = ["ret_21", "ret_126", "log_dv", "log_price", "vol_60", "log_init_value", "n_repeats_asof", "lag_k"]


def dev_cuts(dev: pd.DataFrame) -> dict:
    """Winsorisation cut-offs fixed on the development-period stacked sample."""
    cuts = {f"y{h}": tuple(dev[f"y{h}"].quantile([0.01, 0.99]).values) for h in C.HORIZONS if f"y{h}" in dev}
    for c in ["ret_21", "ret_126", "vol_60"]:
        cuts[c] = tuple(dev[c].quantile([0.01, 0.99]).values)
    return cuts


def estimate(st: pd.DataFrame, h: int, cuts: dict, boot: int = 0, seed: int = C.SEED) -> dict:
    """Matched difference and regression-adjusted estimate for one period's stacked sample."""
    s = st.copy()
    s["y"] = s[f"y{h}"].clip(*cuts[f"y{h}"])
    s = s[s["y"].notna()]
    # keep pairs whose treated row has an outcome and at least one control
    has_t = s[s["treated"] == 1].groupby("pair").size()
    has_c = s[s["treated"] == 0].groupby("pair").size()
    ok_pairs = has_t.index.intersection(has_c.index)
    s = s[s["pair"].isin(ok_pairs)].copy()
    s.loc[s["treated"] == 0, "w"] = 1.0 / s[s["treated"] == 0].groupby("pair")["pair"].transform("size")
    t = s[s["treated"] == 1].set_index("pair")
    cm = s[s["treated"] == 0].groupby("pair")["y"].mean()
    d = (t["y"] - cm.reindex(t.index))
    md = clustered_mean(d.values, t["issuer_cik"].values, t["month"].values)
    out = {"h": h, "n_treated": int(len(t)), "n_control_rows": int((s["treated"] == 0).sum()),
           "n_control_episodes": int(s.loc[s["treated"] == 0, "ep_id"].nunique()),
           "treated_issuers": int(t["issuer_cik"].nunique()),
           "mean_treated": t["y"].mean(), "mean_control": cm.mean(),
           "median_treated": t["y"].median(), "median_control": s.loc[s["treated"] == 0, "y"].median(),
           "match_diff": md["mean"], "match_se": md["se"], "match_lo": md["lo"], "match_hi": md["hi"],
           "match_t": md["t"]}
    if len(t) < 30:
        return out
    # regression adjustment
    X = s[REG_COVS].copy()
    for c in ["ret_21", "ret_126", "vol_60"]:
        X[c] = X[c].clip(*cuts[c])
    X["officer_init"] = (s["init_role"] == "officer").astype(float)
    X["top_init"] = s["init_top"].astype(float)
    X = pd.concat([X, pd.get_dummies(s["year"], prefix="y", drop_first=True, dtype=float),
                   pd.get_dummies(s["sic_div"], prefix="sic", drop_first=True, dtype=float)], axis=1)
    X.insert(0, "treated", s["treated"].astype(float))
    X.insert(0, "const", 1.0)
    ok = X.notna().all(1).values
    r = cluster_ols(s["y"].values[ok], X.values[ok], s["issuer_cik"].values[ok], s["month"].values[ok],
                    w=s["w"].values[ok])
    j = list(X.columns).index("treated")
    out.update({"reg_coef": r.params[j], "reg_se": r.bse[j], "reg_lo": r.params[j] - 1.96 * r.bse[j],
                "reg_hi": r.params[j] + 1.96 * r.bse[j], "reg_p": r.pvalues[j], "reg_n": int(ok.sum())})
    if boot:
        months = t["month"]
        dv = d.values
        bs = block_bootstrap(lambda idx: np.nanmean(dv[idx]), months.reset_index(drop=True), boot, seed)
        out.update({"boot_lo": np.nanpercentile(bs, 2.5), "boot_hi": np.nanpercentile(bs, 97.5),
                    "boot_p": 2 * min((bs <= 0).mean(), (bs >= 0).mean())})
    return out


def balance(st: pd.DataFrame) -> pd.DataFrame:
    vars_ = ["ret_21", "ret_126", "log_dv", "log_price", "vol_60", "log_init_value", "n_repeats_asof", "lag_k"]
    rows = []
    for v in vars_:
        t = st.loc[st["treated"] == 1, v]
        c = st.loc[st["treated"] == 0, v]
        cw = st.loc[st["treated"] == 0, "w"]
        cm = np.average(c.fillna(c.median()), weights=cw)
        sd = np.sqrt((t.var() + c.var()) / 2)
        rows.append({"variable": v, "treated_mean": t.mean(), "control_mean": cm, "std_diff": (t.mean() - cm) / sd})
    x = st.assign(off=(st["init_role"] == "officer").astype(float))
    t, c = x[x.treated == 1]["off"], x[x.treated == 0]
    rows.append({"variable": "initial buyer is officer", "treated_mean": t.mean(),
                 "control_mean": np.average(c["off"], weights=c["w"]), "std_diff": np.nan})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# POST-REVIEW (2026-09-30): balance on the variables as actually used.
# Matching uses the four MATCH_VARS clipped at development 1st/99th percentiles
# (then z-scored); the regression uses REG_COVS with ret_21/ret_126/vol_60 clipped
# at development cut-offs. Reports weighted distribution summaries, not only means.
def _wq(x, w, q):
    o = np.argsort(x)
    x, w = x[o], w[o]
    cw = np.cumsum(w) / w.sum()
    return float(np.interp(q, cw, x))


def balance_detailed(st: pd.DataFrame, cuts: dict, zscale: dict) -> pd.DataFrame:
    rows = []
    s = st.copy()
    t = s["treated"] == 1
    for form in ("raw", "as used"):
        for v in REG_COVS:
            raw = s[v].astype(float)
            lo, hi = -np.inf, np.inf
            if form == "as used":
                if v in zscale:
                    lo, hi = zscale[v][0], zscale[v][1]
                elif v in cuts:
                    lo, hi = cuts[v]
            x = raw.clip(lo, hi)
            xt = x[t].dropna().values
            mc = (~t) & x.notna()
            xc, wc = x[mc].values, s.loc[mc, "w"].values
            if len(xt) < 3 or len(xc) < 3:
                continue
            cm = np.average(xc, weights=wc)
            cv = np.average((xc - cm) ** 2, weights=wc)
            sd = np.sqrt((xt.var(ddof=1) + cv) / 2)
            out_t, out_c = raw[t].dropna(), raw[mc]
            rows.append({"form": form, "variable": v, "clip_lo": lo, "clip_hi": hi,
                         "n_treated": len(xt), "n_control": len(xc),
                         "treated_mean": xt.mean(), "control_mean": cm,
                         "treated_median": float(np.median(xt)), "control_median": _wq(xc, wc, 0.5),
                         "treated_p10": float(np.quantile(xt, 0.1)), "control_p10": _wq(xc, wc, 0.1),
                         "treated_p90": float(np.quantile(xt, 0.9)), "control_p90": _wq(xc, wc, 0.9),
                         "std_diff_mean": (xt.mean() - cm) / sd if sd > 0 else np.nan,
                         "variance_ratio": xt.var(ddof=1) / cv if cv > 0 else np.nan,
                         "treated_share_clipped": float(((out_t < lo) | (out_t > hi)).mean()),
                         "control_share_clipped": float(((out_c < lo) | (out_c > hi)).mean())})
    b = pd.DataFrame(rows)
    return b
