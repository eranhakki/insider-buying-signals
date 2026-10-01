"""Step 10: collect every number quoted in the paper/README from the output
tables into output/numbers.json (documents are filled from this file only)."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402

T = C.TABLES


def pct(x, d=2, sign=True):
    return f"{x*100:+.{d}f}%" if sign else f"{x*100:.{d}f}%"


def pp(x, d=2):
    """A difference of returns, in percentage points."""
    return f"{x*100:+.{d}f} pp"


def n(x):
    return f"{int(x):,}"


def main():
    N = {}
    legs = pd.read_csv(T / "sample_construction_legs.csv")
    N["legs_all"] = n(legs.legs_remaining.iloc[0])
    N["legs_eligible"] = n(legs.legs_remaining.iloc[-1])
    N["legs_fn_screened"] = n(legs.loc[legs.step.str.startswith("footnote"), "legs_removed"].iloc[0])
    N["legs_funds"] = n(legs.loc[legs.step.str.startswith("issuer not"), "legs_removed"].iloc[0])
    N["legs_not_od"] = n(legs.loc[legs.step.str.startswith("owner is"), "legs_removed"].iloc[0])
    ds = pd.read_csv(T / "disclosure_summary.csv", index_col=0)["value"]
    for k in ds.index:
        N[f"ds_{k}"] = n(ds[k])
    sc = pd.read_csv(T / "sample_construction.csv")
    g = dict(zip(sc.step, sc["count"]))
    N["disclosures"] = n(g["grouped into disclosures (issuer x filing date x owner group)"])
    N["disclosures_priced"] = n(g["disclosures with a validated price link"])
    N["disclosures_priced_share"] = pct(int(g["disclosures with a validated price link"]) / int(g["grouped into disclosures (issuer x filing date x owner group)"]), 1, False)
    N["episodes"] = n(g["first-buy episodes (W = 30)"])
    N["clusters"] = n(g["  of which same-day clusters"])
    N["single"] = n(g["  of which single-buyer starts"])
    N["single_second"] = n(g["  single-buyer starts with a second buyer within 30 days"])
    N["single_second_share"] = pct(int(g["  single-buyer starts with a second buyer within 30 days"]) / int(g["  of which single-buyer starts"]), 1, False)
    for t in ["FB_single", "FB_cluster", "SB"]:
        for p in ["dev", "test"]:
            N[f"ev_n_{t}_{p}"] = n(g[f"event study {t} {p}: priced, price >= $1, 60d return"])

    et = pd.read_csv(T / "event_study_table.csv")
    for _, r in et.iterrows():
        k = f"es_{r.period}_{r.event}_{r.h}_{r.measure.replace('-', '')}"
        N[k + "_mean"] = pct(r["mean"])
        N[k + "_ci"] = f"[{r.lo*100:+.2f}, {r.hi*100:+.2f}]"
        N[k + "_median"] = pct(r["median"])
        N[k + "_pos"] = pct(r["share_pos"], 1, False)
        N[k + "_p10"] = pct(r["p10"], 0)
        N[k + "_p90"] = pct(r["p90"], 0)
    ct = pd.read_csv(T / "calendar_time.csv")
    for _, r in ct.iterrows():
        N[f"ct_{r.period}_{r.event}_{r.horizon}_alpha"] = pct(r.alpha_annualised, 1)
        N[f"ct_{r.period}_{r.event}_{r.horizon}_t"] = f"{r.alpha_t:.2f}"
        N[f"ct_{r.period}_{r.event}_{r.horizon}_madj"] = pct((1 + r.mkt_adj_daily_mean) ** 252 - 1, 1)

    inc = pd.read_csv(T / "incremental_primary.csv")
    for _, r in inc.iterrows():
        k = f"inc_{r.period}_{int(r.h)}"
        N[k + "_n"] = n(r.n_treated)
        N[k + "_issuers"] = n(r.treated_issuers)
        N[k + "_ctrl_rows"] = n(r.n_control_rows)
        N[k + "_ctrl_eps"] = n(r.n_control_episodes)
        N[k + "_mt"] = pct(r.mean_treated)
        N[k + "_mc"] = pct(r.mean_control)
        N[k + "_md"] = pp(r.match_diff)
        N[k + "_md_ci"] = f"[{r.match_lo*100:+.2f}, {r.match_hi*100:+.2f}]"
        N[k + "_boot_ci"] = f"[{r.boot_lo*100:+.2f}, {r.boot_hi*100:+.2f}]"
        N[k + "_reg"] = pp(r.reg_coef)
        N[k + "_reg_ci"] = f"[{r.reg_lo*100:+.2f}, {r.reg_hi*100:+.2f}]"
        N[k + "_reg_p"] = f"{r.reg_p:.3f}"
        N[k + "_reg_n"] = n(r.reg_n)
        N[k + "_hi"] = f"{r.reg_hi*100:.1f}"
    for p in ["dev", "test"]:
        b = pd.read_csv(T / f"balance_{p}.csv")
        bb = b.dropna(subset=["std_diff"])
        N[f"bal_{p}_max"] = f"{bb.std_diff.abs().max():.2f}"
        N[f"bal_{p}_max_var"] = bb.loc[bb.std_diff.abs().idxmax(), "variable"]
        N[f"bal_{p}_max_ex_rep"] = f"{bb[bb.variable != 'n_repeats_asof'].std_diff.abs().max():.2f}"

    rb = pd.read_csv(T / "robustness.csv")
    r60 = rb[rb.h == 60]
    test = r60[r60.period == "test"]
    N["rb_n_checks"] = n(test["check"].nunique() - 1)
    N["rb_test_sig_count"] = n(((test.reg_p < 0.05) & (test.check != "Primary specification")).sum())
    N["rb_test_pmin"] = f"{test[test.check != 'Primary specification'].reg_p.min():.3f}"
    N["rb_test_range"] = f"{test.reg_coef.min()*100:+.2f} to {test.reg_coef.max()*100:+.2f} pp"
    for _, r in r60.iterrows():
        key = "".join(ch for ch in r.check.lower().replace(">=", "ge").replace("<", "lt") if ch.isalnum())[:40]
        N[f"rb_{r.period}_{key}"] = f"{r.reg_coef*100:+.2f} pp (p = {r.reg_p:.3f}, n = {int(r.n_treated):,})"
    loo = pd.read_csv(T / "leave_one_year_out.csv")
    dv = loo[loo.period == "dev"]
    N["loo_dev_range"] = f"{dv.reg_coef.min()*100:+.2f} to {dv.reg_coef.max()*100:+.2f} pp"
    N["loo_dev_pmax"] = f"{dv.reg_p.max():.3f}"
    tv = loo[loo.period == "test"]
    N["loo_test_range"] = f"{tv.reg_coef.min()*100:+.2f} to {tv.reg_coef.max()*100:+.2f} pp"
    N["loo_test_pmin"] = f"{tv.reg_p.min():.3f}"
    by = pd.read_csv(T / "robustness_by_year.csv")
    N["by_dev_pos_years"] = f"{int((by[by.period=='dev'].match_diff > 0).sum())} of {int((by.period=='dev').sum())}"
    N["by_test_pos_years"] = f"{int((by[by.period=='test'].match_diff > 0).sum())} of {int((by.period=='test').sum())}"

    pc = pd.read_csv(T / "predictive_check.csv")
    N["pred_r2_diff"] = f"{pc.oos_r2.iloc[2]:+.5f}"
    N["pred_ic_diff"] = f"{pc.mean_monthly_rank_ic.iloc[2]:+.4f}"
    N["pred_ic_base"] = f"{pc.mean_monthly_rank_ic.iloc[0]:+.3f}"
    N["pred_ic_base_t"] = f"{pc.ic_t.iloc[0]:.1f}"
    N["pred_r2_base"] = f"{pc.oos_r2.iloc[0]:+.4f}"

    cov = pd.read_csv(T / "coverage_by_year.csv").set_index("year")
    N["cov_2006"] = pct(cov.loc[2006, "disclosures_priced"], 1, False)
    N["cov_2018"] = pct(cov.loc[2018, "disclosures_priced"], 1, False)
    N["cov_2025"] = pct(cov.loc[2025, "disclosures_priced"], 1, False)
    mis = pd.read_csv(T / "missingness_by_type.csv")
    for _, r in mis.iterrows():
        N[f"mis_{r.period}_{'priced' if r.priced else 'unpriced'}"] = pct(r.share_with_second_buyer, 1, False)
        N[f"mis_{r.period}_{'priced' if r.priced else 'unpriced'}_n"] = n(r.episodes)
    dl = pd.read_csv(T / "delisting.csv")
    N["delist_max"] = pct(dl.delisted_60.max(), 2, False)
    N["incomplete_max"] = pct(dl.incomplete_60.max(), 2, False)
    ca = pd.read_csv(T / "corporate_actions.csv")
    N["unexplained_window_max"] = f"{ca.unexplained_adj_jump.max()*100:.2f}%"
    N["split_share"] = f"{ca.split_in_window.min()*100:.1f}–{ca.split_in_window.max()*100:.1f}%"
    cas = pd.read_csv(T / "corporate_actions_summary.csv", index_col=0).iloc[:, 0]
    N["unexplained_jumps"] = n(cas["unexplained_adjustment_jumps"])
    N["split_events"] = n(cas["split_events_in_price_file"])
    tu = pd.read_csv(T / "tiingo_universe.csv", index_col=0).iloc[:, 0]
    N["tiingo_usd"] = n(tu["tiingo_usd_stock_tickers"])
    N["tiingo_ended"] = pct(tu["ended_before_2026"], 0, False)
    fl = pd.read_csv(T / "filing_lag.csv")
    N["lag_2bd_min"] = pct(fl.within_2bd.min(), 0, False)
    N["lag_2bd_max"] = pct(fl.within_2bd.max(), 0, False)
    ra = pd.read_csv(T / "residual_ambiguity.csv", index_col=0)["value"]
    N["amb_buyback"] = pct(ra["buyback_like_footnote_share"], 1, False)
    N["amb_buyback_n"] = n(ra["buyback_like_legs"])
    N["amb_indirect"] = pct(ra["indirect_ownership_share"], 0, False)
    pm = pd.read_csv(T / "price_match_summary.csv", index_col=0)
    for k in pm.index:
        N["pm_" + "".join(ch for ch in k.lower() if ch.isalnum())[:30]] = f"{int(pm.loc[k,'disclosures']):,} ({pm.loc[k,'share']*100:.1f}%)"
    ex = pd.read_csv(T / "extreme_prices.csv")
    N["extreme_rows"] = n(len(ex))
    st = pd.read_parquet(C.INTER / "stacked_primary.parquet", columns=["pair"])
    N["stacked_rows"] = n(len(st))
    raw_facts(N)
    if C.PRICE_QUALITY == "v2":
        post_review(N)
    (C.TABLES.parent / "numbers.json").write_text(json.dumps(N, indent=1, ensure_ascii=False))
    print(len(N), "numbers written")


def raw_facts(N):
    """Counts quoted in the documents that come straight from the raw export."""
    man = json.loads((C.RAW / "manifest.json").read_text())
    N["raw_price_rows_m"] = f"{man['files']['tiingo_prices.parquet']['rows'] / 1e6:.1f}"
    N["edgar_issuers"] = n(man["files"]["edgar_companies.parquet"]["rows"])
    N["sec_quarters"] = n(pd.read_parquet(C.RAW / "sec_counts_trans_code.parquet")["quarter"].nunique())
    stt = pd.read_parquet(C.RAW / "tiingo_price_status.parquet")
    N["tickers_ok_no_window"] = n(((stt.status == "ok") & (stt.rows_kept == 0)).sum())
    N["tickers_ok"] = n((stt.status == "ok").sum())
    N["tickers_requested"] = n(len(stt))


def ci_binom(k, n_, a=0.05):
    from scipy.stats import beta
    lo = 0.0 if k == 0 else beta.ppf(a / 2, k, n_ - k + 1)
    hi = 1.0 if k == n_ else beta.ppf(1 - a / 2, k + 1, n_ - k)
    return lo, hi


def post_review(N):
    """POST-REVIEW numbers: original (v1) estimates from the preserved snapshot, price-quality
    rule impact, EDGAR audit tallies, filter sensitivity, detailed balance."""
    V1 = C.ROOT / "output" / "original_v1" / "tables"
    inc = pd.read_csv(V1 / "incremental_primary.csv")
    for _, r in inc.iterrows():
        k = f"v1_inc_{r.period}_{int(r.h)}"
        N[k + "_n"] = n(r.n_treated)
        N[k + "_reg"] = pp(r.reg_coef)
        N[k + "_reg_ci"] = f"[{r.reg_lo*100:+.2f}, {r.reg_hi*100:+.2f}]"
        N[k + "_reg_p"] = f"{r.reg_p:.3f}"
        N[k + "_md"] = pp(r.match_diff)
        N[k + "_md_ci"] = f"[{r.match_lo*100:+.2f}, {r.match_hi*100:+.2f}]"
        N[k + "_boot_ci"] = f"[{r.boot_lo*100:+.2f}, {r.boot_hi*100:+.2f}]"
        N[k + "_ctrl_eps"] = n(r.n_control_episodes)
        N[k + "_issuers"] = n(r.treated_issuers)
    P = T / "post_review"
    fs = pd.read_csv(P / "price_flags_summary.csv").set_index("class")
    for c in fs.index:
        N[f"pq_moves_{c}"] = n(fs.loc[c, "moves"])
        N[f"pq_tickers_{c}"] = n(fs.loc[c, "tickers"])
    N["pq_moves_total"] = n(fs["moves"].sum())
    N["pq_moves_flagged"] = n(fs.drop(index="plausible_move")["moves"].sum())
    tot = pd.read_csv(P / "quality_removed_totals.csv").set_index("period")
    for per in ["dev", "test"]:
        for c in ["treated_signals_removed", "control_rows_removed", "matched_issuers_affected",
                  "event_study_events_removed", "event_study_issuers_affected"]:
            N[f"pq_{per}_{c}"] = n(tot.loc[per, c])
    N["pq_treated_removed_total"] = n(tot["treated_signals_removed"].sum())
    N["pq_controls_removed_total"] = n(tot["control_rows_removed"].sum())
    N["pq_events_removed_total"] = n(tot["event_study_events_removed"].sum())
    ex = pd.read_csv(P / "extreme_obs_trace.csv")
    N["ex_rows"] = n(len(ex))
    vc = ex["class"].value_counts()
    for c in ["stale_placeholder", "data_gap_splice", "reversing_spike", "implausible_magnitude", "plausible_move",
              "gradual (no single-day move of 3x or more)"]:
        N["ex_" + "".join(ch for ch in c.lower() if ch.isalnum())[:24]] = n(vc.get(c, 0))
    sk = ex[ex["ticker"] == "SKYX"].iloc[0]
    N["skyx_ret21"] = f"{sk.ret_21:,.0f}"
    N["skyx_before"] = f"${sk.close_before:.3f}"
    N["skyx_after"] = f"${sk.close_after:.2f}"
    N["skyx_zero_days"] = n(sk.zero_volume_days_of_prior_10)
    # balance: v1 raw table vs as-used, and v2
    b1 = pd.read_csv(T.parent / "original_v1" / "tables" / "balance_test.csv").set_index("variable")
    N["bal_v1_test_ret21_treated_mean"] = f"{b1.loc['ret_21', 'treated_mean']:.2f}"
    N["bal_v1_test_ret21_control_mean"] = f"{b1.loc['ret_21', 'control_mean']:.2f}"
    N["bal_v1_test_ret21_sd"] = f"{b1.loc['ret_21', 'std_diff']:.3f}"
    bv1 = pd.read_csv(P / "balance_detailed_v1_test.csv")
    x = bv1[(bv1.form == "raw") & (bv1.variable == "ret_21")].iloc[0]
    N["bal_v1_raw_ret21_vr"] = f"{x.variance_ratio:,.0f}"
    N["bal_v1_raw_ret21_med_t"] = pct(x.treated_median, 1)
    N["bal_v1_raw_ret21_med_c"] = pct(x.control_median, 1)
    x = bv1[(bv1.form == "as used") & (bv1.variable == "ret_21")].iloc[0]
    N["bal_v1_used_ret21_sd"] = f"{x.std_diff_mean:+.3f}"
    N["bal_v1_used_ret21_vr"] = f"{x.variance_ratio:.2f}"
    for per in ["dev", "test"]:
        bd = pd.read_csv(T / f"balance_detailed_{per}.csv")
        u = bd[bd.form == "as used"]
        N[f"bald_{per}_max_sd"] = f"{u.std_diff_mean.abs().max():.2f}"
        N[f"bald_{per}_max_sd_var"] = u.loc[u.std_diff_mean.abs().idxmax(), "variable"]
        uu = u[u.variable != "n_repeats_asof"]
        N[f"bald_{per}_max_sd_ex_rep"] = f"{uu.std_diff_mean.abs().max():.2f}"
        N[f"bald_{per}_vr_range"] = f"{u.variance_ratio.min():.2f}–{u.variance_ratio.max():.2f}"
        r = bd[(bd.form == "raw") & (bd.variable == "ret_21")].iloc[0]
        N[f"bald_{per}_raw_ret21_vr"] = f"{r.variance_ratio:.2f}"
        N[f"bald_{per}_raw_ret21_mean_t"] = pct(r.treated_mean, 1)
        N[f"bald_{per}_raw_ret21_mean_c"] = pct(r.control_mean, 1)
        N[f"bald_{per}_raw_ret21_med_t"] = pct(r.treated_median, 1)
        N[f"bald_{per}_raw_ret21_med_c"] = pct(r.control_median, 1)
    # EDGAR audit
    au = pd.read_csv(C.ROOT / "docs" / "audit" / "filing_audit_35.csv")
    N["aud_n"] = n(len(au))
    N["aud_inspected"] = n(au["inspected_on_edgar"].sum())
    for smp in ["included", "excluded", "footnote-screened"]:
        N[f"aud_n_{smp.replace('-', '_')}"] = n((au["sample"] == smp).sum())
    for v in ["correct", "false_positive", "probable_false_positive", "false_negative", "flag_error"]:
        N[f"aud_{v}"] = n((au["verdict"] == v).sum())
    inc_ = au[au["sample"] == "included"]
    k2 = int((inc_["verdict"] == "false_positive").sum())
    k3 = int(inc_["verdict"].isin(["false_positive", "probable_false_positive"]).sum())
    lo, hi = ci_binom(k3, len(inc_))
    N["aud_fp_rate_incl_probable"] = pct(k3 / len(inc_), 0, False)
    N["aud_fp_rate_ci"] = f"{lo*100:.0f}–{hi*100:.0f}%"
    lo, hi = ci_binom(k2, len(inc_))
    N["aud_fp_rate_confirmed"] = pct(k2 / len(inc_), 0, False)
    N["aud_fp_rate_confirmed_ci"] = f"{lo*100:.0f}–{hi*100:.0f}%"
    # filter sensitivity
    fc = pd.read_csv(P / "filter_sensitivity_counts.csv")
    for _, r in fc.iterrows():
        key = "".join(ch for ch in r.reason.lower() if ch.isalnum())[:20]
        N[f"fc_{key}"] = n(r.disclosures)
        N[f"fc_{key}_share"] = pct(r.share_of_disclosures, 1, False)
    fe = pd.read_csv(P / "filter_sensitivity_estimates.csv")
    for _, r in fe.iterrows():
        key = "".join(ch for ch in r.check.lower() if ch.isalnum())[:14]
        N[f"fe_{key}_{r.period}_{int(r.h)}"] = (f"{r.reg_coef*100:+.2f} pp (95% CI [{r.reg_lo*100:+.2f}, {r.reg_hi*100:+.2f}], "
                                                f"p = {r.reg_p:.3f}, n = {int(r.n_treated):,})")
    fnp = pd.read_csv(P / "filter_false_negative_prevalence.csv")
    N["fn_other_title_legs"] = n(fnp.form4_P_legs_excluded.iloc[0])
    N["fn_llc_legs"] = n(fnp.form4_P_legs_excluded.iloc[1])
    N["fn_other_title_share"] = pct(fnp.as_share_of_eligible_legs.iloc[0], 2, False)
    ac = pd.read_csv(P / "audited_cases_in_samples.csv")
    N["aud_fp_in_matched"] = n((ac.get("in_matched_test_as", pd.Series(dtype=str)).fillna("") != "").sum())
    N["aud_fp_in_events"] = n((ac.get("in_event_study_as", pd.Series(dtype=str)).fillna("") != "").sum())
    # change in the headline
    cur = pd.read_csv(T / "incremental_primary.csv")
    for per in ["dev", "test"]:
        for h in C.HORIZONS:
            a = inc[(inc.period == per) & (inc.h == h)].iloc[0]
            b = cur[(cur.period == per) & (cur.h == h)].iloc[0]
            N[f"delta_{per}_{h}"] = f"{(b.reg_coef - a.reg_coef)*100:+.3f} pp"
            N[f"delta_n_{per}_{h}"] = f"{int(b.n_treated - a.n_treated):+,}"


if __name__ == "__main__":
    main()
