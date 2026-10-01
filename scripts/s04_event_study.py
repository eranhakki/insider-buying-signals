"""Step 4: event-level returns and the descriptive event study.

Event types (W = 30):
  FB_single  first-buy signal, one initial buyer group        (date F)
  FB_cluster first-buy signal with >=2 distinct buyers same day (date F)
  SB         second-buyer signal                              (date S)

Usage: python s04_event_study.py [--final]
  without --final, summaries are written for the development period only.

Outputs: intermediate/events_W30.parquet; tables/event_study_*.csv; figures.
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402
from src.prices import PriceStore, covariates, event_returns  # noqa: E402
from src.sectors import sector_etf_at  # noqa: E402
from src.stats import capm_alpha, describe, newey_west_mean  # noqa: E402
from src.plotstyle import COLORS, apply_style  # noqa: E402

TYPES = ["FB_single", "FB_cluster", "SB"]
LABEL = {"FB_single": "First buy (single buyer)", "FB_cluster": "First buy (2+ buyers same day)",
         "SB": "Second-buyer disclosure"}


def period_of(d: pd.Series) -> pd.Series:
    return np.select([d.between(C.DEV_START, C.DEV_END), d.between(C.TEST_START, C.TEST_END)],
                     ["dev", "test"], default="out")


def make_events(ep: pd.DataFrame) -> pd.DataFrame:
    fb = ep.assign(etype=np.where(ep["same_day_cluster"], "FB_cluster", "FB_single"), date=ep["F"],
                   tkr=ep["ticker"], match_primary=ep["init_match_primary"], match_strict=ep["init_match_strict"],
                   role=ep["init_role"], value=ep["init_value"], plan=ep["init_plan"], late=ep["init_late"])
    sb = ep[ep["has_second"]].assign(etype="SB", date=lambda x: x["S"],
                                     tkr=lambda x: x["second_ticker"].fillna(x["ticker"]),
                                     match_primary=lambda x: x["second_match_primary"],
                                     match_strict=lambda x: x["second_match_strict"],
                                     role=lambda x: x["second_role"], value=lambda x: x["second_value"],
                                     plan=lambda x: x["second_plan"], late=lambda x: x["second_late"])
    cols = ["issuer_cik", "issuer_name", "sic", "F", "S", "lag", "etype", "date", "tkr", "match_primary",
            "match_strict", "role", "value", "plan", "late", "init_value", "init_role", "init_top",
            "second_role", "second_value", "second_top", "same_day_cluster"]
    ev = pd.concat([fb[cols], sb[cols]], ignore_index=True)
    ev["event_id"] = np.arange(len(ev))
    return ev


def add_returns(ps: PriceStore, ev: pd.DataFrame) -> pd.DataFrame:
    rows = ps.row(ev["tkr"].fillna(""))
    cov = covariates(ps, rows, ev["date"])
    ev = pd.concat([ev.reset_index(drop=True), cov], axis=1)
    ev["row"] = rows
    # benchmarks: SPY (primary), IWM, sector ETF
    sect = [sector_etf_at(s, d) for s, d in zip(ev["sic"], ev["date"])]
    ev["sector_etf"] = sect
    for rule in C.ENTRY_VARIANTS:
        for h in C.HORIZONS:
            r = event_returns(ps, rows, ev["date"], rule, h)
            tag = f"{rule}_h{h}"
            ev[f"ret_{tag}"] = r["ret"].values
            ev[f"xret_{tag}"] = r["xret"].values
            if rule == C.ENTRY:
                ev[f"incomplete_h{h}"] = r["incomplete"].values
                ev[f"delisted_h{h}"] = r["delisted"].values
                ev[f"entry_idx"] = r["entry_idx"].values
                ev[f"end_idx_h{h}"] = r["end_idx"].values
                ri = event_returns(ps, rows, ev["date"], rule, h, bench="IWM")
                ev[f"xret_iwm_h{h}"] = ri["xret"].values
                srows = ps.row(ev["sector_etf"])
                rs = event_returns(ps, rows, ev["date"], rule, h, bench_rows=srows)
                ev[f"xret_sector_h{h}"] = rs["xret"].values
    ev["period"] = period_of(ev["date"])
    ev["month"] = ev["date"].dt.to_period("M").astype(str)
    ev["year"] = ev["date"].dt.year
    return ev


def usable(ev: pd.DataFrame) -> pd.Series:
    return ev["match_primary"].fillna(False).astype(bool) & (ev["px"] >= C.MIN_PRICE) & ev["row"].ge(0)


def summaries(ev: pd.DataFrame, periods: list[str]):
    out = []
    for per in periods:
        e = ev[(ev["period"] == per) if per != "all_shown" else ev["period"].isin(periods)]
        for t in TYPES:
            x = e[e["etype"] == t]
            for h in C.HORIZONS:
                for kind in ("ret", "xret"):
                    col = f"{kind}_{C.ENTRY}_h{h}"
                    d = describe(x[col], x["issuer_cik"], x["month"])
                    d.update({"period": per, "event": t, "horizon": h,
                              "measure": "raw" if kind == "ret" else "SPY-adjusted",
                              "issuers": x.loc[x[col].notna(), "issuer_cik"].nunique()})
                    out.append(d)
    return pd.DataFrame(out)


def by_year(ev: pd.DataFrame, periods: list[str]):
    e = ev[ev["period"].isin(periods)]
    rows = []
    for (y, t), x in e.groupby(["year", "etype"]):
        col = f"xret_{C.ENTRY}_h{C.PRIMARY_H}"
        d = describe(x[col], x["issuer_cik"], x["month"])
        d.update({"year": y, "event": t})
        rows.append(d)
    return pd.DataFrame(rows)


def car_paths(ps: PriceStore, ev: pd.DataFrame, H: int = 60) -> dict:
    spy = ps.tix[C.BENCH]
    res = {}
    for t in TYPES:
        x = ev[(ev["etype"] == t) & ev["entry_idx"].ge(0)]
        r, e = x["row"].values, x["entry_idx"].values
        e = e[e + H < len(ps.dates)]
        r = r[: len(e)] if len(r) != len(e) else r
        keep = x["entry_idx"].values + H < len(ps.dates)
        r, e = x["row"].values[keep], x["entry_idx"].values[keep]
        k = np.arange(0, H + 1)
        P = ps.adj[r[:, None], e[:, None] + k[None, :]].astype(float)
        P = pd.DataFrame(P).ffill(axis=1).values
        M = ps.adj[spy, e[:, None] + k[None, :]].astype(float)
        car = P / P[:, [0]] - M / M[:, [0]]
        res[t] = (np.nanmean(car, 0), np.nanstd(car, 0) / np.sqrt(np.sum(~np.isnan(car), 0)), len(r))
    return res


def calendar_time(ps: PriceStore, ev: pd.DataFrame, h: int) -> pd.DataFrame:
    """Equal-weight daily portfolio of all events in their holding window (entry+1..entry+h)."""
    spy = ps.tix[C.BENCH]
    mret = pd.Series(ps.adj[spy, 1:] / ps.adj[spy, :-1] - 1, index=ps.dates[1:])
    out = []
    for t in TYPES:
        x = ev[(ev["etype"] == t) & ev["entry_idx"].ge(0)]
        r, e = x["row"].values, x["entry_idx"].values
        k = np.arange(1, h + 1)
        di = e[:, None] + k[None, :]
        ok = di < len(ps.dates)
        rr = np.repeat(r, h).reshape(-1, h)[ok]
        dd = di[ok]
        dr = ps.adj[rr, dd] / ps.adj[rr, dd - 1] - 1
        s = pd.DataFrame({"d": dd, "r": dr}).dropna()
        s = s[np.abs(s["r"]) < 1.0]  # guard against bad ticks (|daily ret| >= 100%)
        port = s.groupby("d")["r"].mean()
        n = s.groupby("d").size()
        port.index = ps.dates[port.index]
        n.index = port.index
        port = port[n >= 10]
        a = capm_alpha(port, mret)
        nw = newey_west_mean(port - mret.reindex(port.index))
        out.append({"event": t, "horizon": h, "days": a["n_days"], "avg_names": float(n[n >= 10].mean()),
                    "mkt_adj_daily_mean": nw["mean"], "mkt_adj_t": nw["t"],
                    "capm_alpha_daily": a["alpha"], "alpha_t": a["alpha_t"], "beta": a["beta"],
                    "alpha_annualised": (1 + a["alpha"]) ** 252 - 1})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    args = ap.parse_args()
    periods = ["dev", "test"] if args.final else ["dev"]
    suffix = "" if args.final else "_devonly"

    f = C.INTER / "events_W30.parquet"
    ps = PriceStore()
    if not f.exists():
        ep = pd.read_parquet(C.INTER / f"episodes_W{C.WINDOW}.parquet")
        ev = add_returns(ps, make_events(ep))
        ev.to_parquet(f, index=False)
    ev = pd.read_parquet(f)
    evu = ev[usable(ev)].copy()

    s = summaries(evu, periods)
    s.to_csv(C.TABLES / f"event_study_summary{suffix}.csv", index=False)
    print(s[s["measure"] == "SPY-adjusted"][["period", "event", "horizon", "n", "issuers", "mean", "lo", "hi",
                                              "median", "share_pos"]].round(4).to_string(index=False))
    by_year(evu, periods).to_csv(C.TABLES / f"event_study_by_year{suffix}.csv", index=False)

    ct = []
    for per in periods:
        for h in C.HORIZONS:
            c = calendar_time(ps, evu[evu["period"] == per], h)
            c.insert(0, "period", per)
            ct.append(c)
    ct = pd.concat(ct)
    ct.to_csv(C.TABLES / f"calendar_time{suffix}.csv", index=False)
    print(ct.round(5).to_string(index=False))

    apply_style()
    fig, axes = plt.subplots(1, len(periods), figsize=(6.2 * len(periods), 4.2), squeeze=False, sharey=True)
    for ax, per in zip(axes[0], periods):
        paths = car_paths(ps, evu[evu["period"] == per])
        for t in TYPES:
            m, se, n = paths[t]
            k = np.arange(len(m))
            ax.plot(k, m * 100, color=COLORS[t], lw=2, label=f"{LABEL[t]} (n={n:,})")
            ax.fill_between(k, (m - 1.96 * se) * 100, (m + 1.96 * se) * 100, color=COLORS[t], alpha=0.15, lw=0)
        ax.axhline(0, color="#888", lw=0.8)
        ax.set_title({"dev": "Development 2006–2018", "test": "Test 2019–mid-2026"}[per])
        ax.set_xlabel("Trading days after entry (t+1 close)")
    axes[0][0].set_ylabel("Mean SPY-adjusted return, %")
    axes[0][0].legend(loc="upper left", fontsize=8.5)
    fig.text(0.01, 0.01, "Bands: ±1.96 × naive SE of the mean (ignores overlap; for shape only — see clustered tables).",
             fontsize=7.5, color="#666")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(C.FIGS / f"fig_car_paths{suffix}.png", dpi=180)


if __name__ == "__main__":
    main()
