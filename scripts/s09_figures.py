"""Step 9: figures and the extra summary tables used in the paper."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src import config as C  # noqa: E402
from src.plotstyle import AQUA, BLUE, GRAY, INK2, ORANGE, apply_style  # noqa: E402
from src.prices import PriceStore  # noqa: E402
from src.stats import describe  # noqa: E402
from s04_event_study import TYPES, LABEL, usable  # noqa: E402

apply_style()
PER = {"dev": "Development 2006–2018", "test": "Test 2019–mid-2026"}


def fig_coverage():
    cov = pd.read_csv(C.TABLES / "coverage_by_year.csv")
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    ax[0].plot(cov["year"], cov["disclosures_priced"] * 100, color=BLUE, marker="o", ms=4)
    ax[0].set_ylim(0, 100)
    ax[0].set_title("Share of eligible disclosures with a validated price series")
    ax[0].set_ylabel("%")
    ax[0].annotate("Unpriced early firms are mostly\ndelisted or reused tickers", xy=(2007, 47), xytext=(2011, 25),
                   fontsize=8, color=INK2, arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.8))
    ax[1].plot(cov["year"], cov["second_rate_priced"] * 100, color=BLUE, marker="o", ms=4, label="Priced episodes")
    ax[1].plot(cov["year"], cov["second_rate_unpriced"] * 100, color=ORANGE, marker="o", ms=4, label="Unpriced episodes")
    ax[1].set_ylim(0, 40)
    ax[1].set_title("Single-buyer episodes that gain a second buyer (%)")
    ax[1].legend(loc="lower left", fontsize=8.5)
    for a in ax:
        a.axvspan(2018.5, 2026.5, color="#f0efec", zorder=0)
        a.text(2022.5, a.get_ylim()[1] * 0.95, "test", ha="center", fontsize=8, color=INK2)
    fig.tight_layout()
    fig.savefig(C.FIGS / "fig1_coverage.png", dpi=180)


def event_table():
    ev = pd.read_parquet(C.INTER / "events_W30.parquet")
    ev = ev[usable(ev)]
    rows = []
    for per in ("dev", "test"):
        for t in TYPES:
            x = ev[(ev["period"] == per) & (ev["etype"] == t)]
            for h in C.HORIZONS:
                for m, col in [("raw", f"ret_{C.ENTRY}_h{h}"), ("SPY-adj", f"xret_{C.ENTRY}_h{h}"),
                               ("IWM-adj", f"xret_iwm_h{h}")]:
                    d = describe(x[col], x["issuer_cik"], x["month"])
                    d.update({"period": per, "event": t, "h": h, "measure": m})
                    rows.append(d)
    tab = pd.DataFrame(rows)
    tab.to_csv(C.TABLES / "event_study_table.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9), sharey=True)
    colors = {"FB_single": BLUE, "FB_cluster": AQUA, "SB": ORANGE}
    for ax, m in zip(axes, ["SPY-adj", "IWM-adj"]):
        for i, per in enumerate(("dev", "test")):
            for j, t in enumerate(TYPES):
                r = tab[(tab.period == per) & (tab.event == t) & (tab.h == 60) & (tab.measure == m)].iloc[0]
                xpos = i * 4 + j
                ax.errorbar(xpos, r["mean"] * 100, yerr=[[(r["mean"] - r["lo"]) * 100], [(r["hi"] - r["mean"]) * 100]],
                            fmt="o", color=colors[t], ms=7, capsize=3, lw=1.6, label=LABEL[t] if i == 0 else None)
                ax.plot(xpos, r["median"] * 100, marker="_", ms=14, color=INK2, mew=1.5)
        ax.axhline(0, color="#888", lw=0.8)
        ax.set_xticks([1, 5])
        ax.set_xticklabels([PER["dev"], PER["test"]])
        ax.set_title(f"60-day {m.replace('-adj', '')}-adjusted return after disclosure")
    axes[0].set_ylabel("%  (dot = mean ± 95% CI, dash = median)")
    axes[0].legend(fontsize=8, loc="lower left")
    fig.text(0.01, 0.01, "CIs: standard errors clustered by issuer and signal month. Means are not winsorised.",
             fontsize=7.5, color="#666")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(C.FIGS / "fig3_event_means.png", dpi=180)
    return tab


def fig_main():
    r = pd.read_csv(C.TABLES / "incremental_primary.csv")
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ylabels = []
    for i, (per, h) in enumerate([("dev", 20), ("dev", 60), ("test", 20), ("test", 60)]):
        x = r[(r.period == per) & (r.h == h)].iloc[0]
        y = 3 - i
        c = BLUE if per == "dev" else ORANGE
        ax.errorbar(x.reg_coef * 100, y, xerr=[[(x.reg_coef - x.reg_lo) * 100], [(x.reg_hi - x.reg_coef) * 100]],
                    fmt="o", color=c, ms=8, capsize=4, lw=2)
        ax.errorbar(x.match_diff * 100, y - 0.25, xerr=[[(x.match_diff - x.match_lo) * 100], [(x.match_hi - x.match_diff) * 100]],
                    fmt="s", color=c, ms=5, capsize=3, lw=1.2, alpha=0.6)
        ylabels.append((y, f"{PER[per].split(' ')[0]} · {h}-day\n(n = {int(x.n_treated):,} signals)"))
        ax.text(x.reg_hi * 100 + 0.08, y, f"{x.reg_coef*100:+.2f}%  (p = {x.reg_p:.3f})", va="center", fontsize=8.5)
    ax.axvline(0, color="#888", lw=0.8)
    ax.set_yticks([y for y, _ in ylabels])
    ax.set_yticklabels([l for _, l in ylabels], fontsize=8.5)
    ax.set_xlabel("Second-buyer signal minus matched single-buyer episodes, SPY-adjusted return (pp)")
    ax.set_title("Incremental return of a second distinct buyer")
    ax.set_xlim(-1.0, 2.0)
    fig.text(0.01, 0.01, "Circle: regression-adjusted (primary). Square: raw matched difference. 95% CIs, two-way clustered (issuer, month).",
             fontsize=7.3, color="#666")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(C.FIGS / "fig4_main_result.png", dpi=180)


def fig_time():
    by = pd.read_csv(C.TABLES / "robustness_by_year.csv")
    fig, ax = plt.subplots(1, 2, figsize=(11.5, 3.9))
    c = np.where(by["period"] == "dev", BLUE, ORANGE)
    for (_, r), cc in zip(by.iterrows(), c):
        ax[0].errorbar(r["year"], r["match_diff"] * 100, yerr=[[(r["match_diff"] - r["match_lo"]) * 100],
                                                                 [(r["match_hi"] - r["match_diff"]) * 100]],
                       fmt="o", color=cc, ms=5, capsize=2, lw=1.2)
    ax[0].axhline(0, color="#888", lw=0.8)
    ax[0].set_title("Matched 60-day difference by signal year (pp)")
    ax[0].axvspan(2018.5, 2026.5, color="#f0efec", zorder=0)
    ax[0].set_ylabel("pp  (95% CI, clustered)")
    # calendar-time cumulative market-adjusted return
    ps = PriceStore()
    ev = pd.read_parquet(C.INTER / "events_W30.parquet")
    ev = ev[usable(ev) & ev["entry_idx"].ge(0)]
    spy = ps.tix[C.BENCH]
    mret = pd.Series(ps.adj[spy, 1:] / ps.adj[spy, :-1] - 1, index=ps.dates[1:])
    for t, col in [("FB_single", BLUE), ("SB", ORANGE)]:
        x = ev[ev["etype"] == t]
        r, e = x["row"].values, x["entry_idx"].values
        h = 60
        di = e[:, None] + np.arange(1, h + 1)[None, :]
        ok = di < len(ps.dates)
        rr = np.repeat(r, h).reshape(-1, h)[ok]
        dd = di[ok]
        dr = ps.adj[rr, dd] / ps.adj[rr, dd - 1] - 1
        s = pd.DataFrame({"d": dd, "r": dr}).dropna()
        s = s[np.abs(s["r"]) < 1]
        port = s.groupby("d")["r"].mean()
        n = s.groupby("d").size()
        port = port[n >= 10]
        port.index = ps.dates[port.index]
        xs = (port - mret.reindex(port.index)).fillna(0)
        cum = (np.log1p(xs)).cumsum()
        ax[1].plot(cum.index, cum.values * 100, color=col, lw=1.6, label=LABEL[t])
    ax[1].axvspan(pd.Timestamp("2019-01-01"), pd.Timestamp("2026-09-30"), color="#f0efec", zorder=0)
    ax[1].set_title("Calendar-time portfolio, cumulative log return vs SPY")
    ax[1].set_ylabel("% (log)")
    ax[1].legend(fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(C.FIGS / "fig5_over_time.png", dpi=180)


def fig_robust():
    r = pd.read_csv(C.TABLES / "robustness.csv")
    r = r[(r["h"] == 60)].copy()
    order = list(dict.fromkeys(r["check"]))
    fig, ax = plt.subplots(1, 2, figsize=(12, 0.34 * len(order) + 1.4), sharey=True)
    for a, per in zip(ax, ("dev", "test")):
        x = r[r["period"] == per].set_index("check").reindex(order)
        y = np.arange(len(order))[::-1]
        c = np.where(x["too_small"].fillna(True), GRAY, BLUE if per == "dev" else ORANGE)
        for yy, (_, row), cc in zip(y, x.iterrows(), c):
            if pd.isna(row.get("reg_coef")):
                continue
            a.errorbar(row["reg_coef"] * 100, yy, xerr=[[(row["reg_coef"] - row["reg_lo"]) * 100], [(row["reg_hi"] - row["reg_coef"]) * 100]],
                       fmt="o", color=cc, ms=4.5, capsize=2, lw=1.1)
        a.axvline(0, color="#888", lw=0.8)
        prim = x.loc["Primary specification", "reg_coef"] * 100
        a.axvline(prim, color=BLUE if per == "dev" else ORANGE, lw=0.8, ls="--")
        a.set_title(PER[per])
        a.set_xlabel("Regression-adjusted 60-day difference (pp, 95% CI)")
    ax[0].set_yticks(np.arange(len(order))[::-1])
    ax[0].set_yticklabels([f"{o}  [n={int(r[(r.check == o) & (r.period == 'test')]['n_treated'].iloc[0]):,} test]" for o in order], fontsize=7.6)
    fig.text(0.01, 0.005, "Grey: fewer than 100 treated signals in that period (too small for a claim). Dashed line: primary estimate.",
             fontsize=7.5, color="#666")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(C.FIGS / "fig6_robustness.png", dpi=180)


if __name__ == "__main__":
    import shutil
    shutil.copy(C.FIGS / "fig_car_paths.png", C.FIGS / "fig2_car_paths.png")  # written by s04
    fig_coverage()
    event_table()
    fig_main()
    if (C.TABLES / "robustness.csv").exists():
        fig_time()
        fig_robust()
