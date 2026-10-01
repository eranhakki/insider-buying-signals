"""Step 7: data audit tables.

  audit_sample.csv            35 filings for manual review (EDGAR links, accession numbers)
  filing_lag.csv              disclosure timing distribution by year
  coverage_by_year.csv        disclosures, episodes, priced share, second-buyer rate by pricing status
  missingness_by_type.csv     is pricing coverage different for second-buyer vs single episodes?
  corporate_actions.csv       split / adjustment checks in event windows
  delisting.csv               incomplete / delisted windows by event type and period
  sample_construction.csv     full flow from P-code legs to the matched test sample
  extreme_prices.csv          matched rows with implausible prior returns
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402
from src.incremental import dev_cuts  # noqa: E402


def edgar_link(cik, acc):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index.htm"


def main():
    legs = pd.read_parquet(C.INTER / "legs_all.parquet")
    d = pd.read_parquet(C.INTER / "disclosures_matched.parquet")
    ep = pd.read_parquet(C.INTER / "episodes_W30.parquet")
    ev = pd.read_parquet(C.INTER / "events_W30.parquet")
    st = pd.read_parquet(C.INTER / "stacked_primary.parquet")
    rng = np.random.default_rng(C.SEED)

    # 1. manual audit sample
    inc = legs[legs["eligible"]].sample(15, random_state=C.SEED)
    exc = legs[~legs["eligible"] & ~legs["fail_step"].str.startswith("footnote")
               & legs["DOCUMENT_TYPE"].eq("4")].sample(15, random_state=C.SEED)
    fns = legs[legs["fail_step"].str.startswith("footnote")].sample(5, random_state=C.SEED)
    a = pd.concat([inc.assign(sample="included"), exc.assign(sample="excluded"), fns.assign(sample="footnote-screened")])
    a["edgar_link"] = [edgar_link(c, x) if pd.notna(c) else "" for c, x in zip(a["issuer_cik"], a["ACCESSION_NUMBER"])]
    a["exclusion_reason"] = a["fail_step"].replace("", "— (included)")
    a["footnote_excerpt"] = (a["footnotes"].fillna("") + " " + a["REMARKS"].fillna("")).str.slice(0, 300)
    cols = ["sample", "ACCESSION_NUMBER", "ISSUERNAME", "ISSUERTRADINGSYMBOL", "owner_names", "titles",
            "any_officer", "any_director", "DOCUMENT_TYPE", "filing_date", "trans_date", "SECURITY_TITLE", "shares",
            "price", "exclusion_reason", "footnote_excerpt", "edgar_link"]
    a[cols].to_csv(C.TABLES / "audit_sample.csv", index=False)

    # 1b. which footnote keywords did the screen hit (first match per leg)
    fsc = legs[legs["fail_step"].str.startswith("footnote")]
    txt = (fsc["footnotes"].fillna("") + " " + fsc["REMARKS"].fillna("")).str.lower()
    txt.str.findall(C.FOOTNOTE_EXCLUDE_RE).str[0].value_counts().rename_axis("keyword").rename("legs").to_csv(
        C.TABLES / "footnote_hits.csv")

    # 1c. residual ambiguity among eligible legs (cannot be resolved from the data)
    e = legs[legs["eligible"]]
    t = (e["footnotes_all"].fillna("") + " " + e["REMARKS"].fillna("")).str.lower()
    bb = t.str.contains(r"repurchase program|share repurchase|buyback|buy-back|manage dilution|not directly for the individual")
    nd = pd.read_parquet(C.RAW / "sec_nonderiv_trans.parquet",
                         columns=["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "DIRECT_INDIRECT_OWNERSHIP"])
    m = e[["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]].merge(
        nd.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"]), on=["ACCESSION_NUMBER", "NONDERIV_TRANS_SK"], how="left")
    pd.Series({"eligible_legs": len(e), "buyback_like_footnote_share": bb.mean(), "buyback_like_legs": int(bb.sum()),
               "indirect_ownership_share": (m["DIRECT_INDIRECT_OWNERSHIP"] == "I").mean(),
               "weighted_avg_price_footnote_share": t.str.contains("weighted average").mean()}).to_csv(
        C.TABLES / "residual_ambiguity.csv", header=["value"])

    # 2. filing lag
    lag = d.assign(year=d["filing_date"].dt.year).groupby("year")["filing_lag_bd"].agg(
        n="size", median="median", p90=lambda s: s.quantile(0.9),
        within_2bd=lambda s: (s <= 2).mean(), over_4bd=lambda s: (s > 4).mean())
    lag.to_csv(C.TABLES / "filing_lag.csv")

    # 3. coverage by year and missingness by type
    ep["year"] = ep["F"].dt.year
    ep["priced"] = ep["init_match_primary"].fillna(False).astype(bool)
    single = ep[~ep["same_day_cluster"]]
    cov = single.groupby("year").agg(episodes=("F", "size"), priced_share=("priced", "mean"),
                                     second_rate_priced=("has_second", lambda s: s[single.loc[s.index, "priced"]].mean()),
                                     second_rate_unpriced=("has_second", lambda s: s[~single.loc[s.index, "priced"]].mean()))
    dy = d.assign(year=d["filing_date"].dt.year).groupby("year").agg(disclosures=("disc_id", "size"),
                                                                    disclosures_priced=("match_primary", "mean"))
    cov = dy.join(cov)
    cov.to_csv(C.TABLES / "coverage_by_year.csv")
    mis = single.assign(period=np.where(single["year"] <= 2018, "dev", "test")).groupby(["period", "priced"])[
        "has_second"].agg(["size", "mean"]).rename(columns={"size": "episodes", "mean": "share_with_second_buyer"})
    mis.to_csv(C.TABLES / "missingness_by_type.csv")

    # 4. corporate actions inside event windows (primary timing, h = 60)
    p = pd.read_parquet(C.RAW / "tiingo_prices.parquet", columns=["ticker", "date", "close", "adjClose", "splitFactor", "divCash"])
    p["date"] = pd.to_datetime(p["date"])
    p = p.sort_values(["ticker", "date"])
    p["f"] = p["adjClose"] / p["close"]
    p["f_chg"] = p.groupby("ticker")["f"].pct_change()
    splits = p[p["splitFactor"].ne(1) & p["splitFactor"].notna()]
    # adjustment factor jumps without a recorded split or dividend = suspicious
    unexplained = p[(p["f_chg"].abs() > 0.2) & p["splitFactor"].eq(1) & p["divCash"].fillna(0).eq(0)]
    e = ev[ev["match_primary"].fillna(False).astype(bool) & ev["entry_idx"].ge(0)].copy()
    dates = pd.DatetimeIndex(np.load(C.INTER / "price_store.npz", allow_pickle=True)["dates"])
    e["d0"] = dates[e["entry_idx"].clip(0, len(dates) - 1)]
    e["d1"] = dates[e["end_idx_h60"].clip(0, len(dates) - 1)]
    sp = splits.groupby("ticker")["date"].apply(np.array).to_dict()
    ux = unexplained.groupby("ticker")["date"].apply(np.array).to_dict()
    e["split_in_window"] = [any((x > a) & (x <= b)) if t in sp else False for t, a, b in zip(e["tkr"], e["d0"], e["d1"])
                            for x in [sp.get(t, np.array([], "datetime64[ns]"))]]
    e["unexplained_adj_jump"] = [any((x > a) & (x <= b)) if t in ux else False for t, a, b in zip(e["tkr"], e["d0"], e["d1"])
                                 for x in [ux.get(t, np.array([], "datetime64[ns]"))]]
    ca = e.groupby(["period", "etype"]).agg(events=("event_id", "size"), split_in_window=("split_in_window", "mean"),
                                           unexplained_adj_jump=("unexplained_adj_jump", "mean"))
    ca.to_csv(C.TABLES / "corporate_actions.csv")
    pd.Series({"tickers_with_prices": p["ticker"].nunique(), "split_events_in_price_file": len(splits),
               "unexplained_adjustment_jumps": len(unexplained)}).to_csv(C.TABLES / "corporate_actions_summary.csv")

    # 5. delisting / incomplete windows
    dl = e.groupby(["period", "etype"]).agg(events=("event_id", "size"),
                                           incomplete_60=("incomplete_h60", "mean"), delisted_60=("delisted_h60", "mean"))
    dl.to_csv(C.TABLES / "delisting.csv")
    sd = st.groupby(["period", "treated"]).agg(rows=("pair", "size"), incomplete_60=("incomplete60", "mean"),
                                               delisted_60=("delisted60", "mean"))
    sd.to_csv(C.TABLES / "delisting_matched.csv")
    sup = pd.read_parquet(C.RAW / "tiingo_supported_tickers.parquet")
    sup = sup[(sup["priceCurrency"] == "USD") & (sup["assetType"] == "Stock")]
    sup["end"] = pd.to_datetime(sup["endDate"], errors="coerce")
    pd.Series({"tiingo_usd_stock_tickers": len(sup), "ended_before_2026": float((sup["end"] < "2026-01-01").mean()),
               "ended_before_2012": float((sup["end"] < "2012-01-01").mean())}).to_csv(C.TABLES / "tiingo_universe.csv")

    # 6. sample construction (full flow)
    sc_legs = pd.read_csv(C.TABLES / "sample_construction_legs.csv")
    summ = pd.read_csv(C.TABLES / "disclosure_summary.csv", index_col=0)["value"]
    usable = ev["match_primary"].fillna(False).astype(bool) & (ev["px"] >= C.MIN_PRICE)
    flow = [(r["step"], r["legs_remaining"], "legs") for _, r in sc_legs.iterrows()]
    flow += [("after removing cross-filing duplicates", int(summ["eligible_legs"] - summ["duplicate_legs_removed"]), "legs"),
             ("grouped into disclosures (issuer x filing date x owner group)", len(d), "disclosures"),
             ("disclosures with a validated price link", int(d["match_primary"].sum()), "disclosures"),
             ("first-buy episodes (W = 30)", len(ep), "episodes"),
             ("  of which same-day clusters", int(ep["same_day_cluster"].sum()), "episodes"),
             ("  of which single-buyer starts", int((~ep["same_day_cluster"]).sum()), "episodes"),
             ("  single-buyer starts with a second buyer within 30 days", int((~ep["same_day_cluster"] & ep["has_second"]).sum()), "episodes")]
    for t in ["FB_single", "FB_cluster", "SB"]:
        for per in ["dev", "test"]:
            m = (ev["etype"] == t) & (ev["period"] == per)
            flow.append((f"event study {t} {per}: priced, price >= $1, 60d return", int((m & usable & ev[f"xret_{C.ENTRY}_h60"].notna()).sum()), "events"))
    for per in ["dev", "test"]:
        s = st[(st["period"] == per)]
        flow.append((f"matched test {per}: second-buyer signals with >=1 control", int((s["treated"] == 1).sum()), "signals"))
        flow.append((f"matched test {per}: control rows (distinct episodes)",
                     f"{int((s['treated'] == 0).sum())} ({s.loc[s['treated'] == 0, 'ep_id'].nunique()})", "rows"))
    pd.DataFrame(flow, columns=["step", "count", "unit"]).to_csv(C.TABLES / "sample_construction.csv", index=False)

    # 7. extreme prior returns in the matched sample
    x = st[(st["ret_21"] > 2) | (st["ret_126"] > 10)][["period", "treated", "issuer_name", "ticker", "date", "ret_21",
                                                        "ret_126", "px", "y60"]]
    x.to_csv(C.TABLES / "extreme_prices.csv", index=False)
    print(pd.read_csv(C.TABLES / "sample_construction.csv").to_string(index=False))
    print(cov.round(3).to_string())
    print(mis.round(3))
    print(ca.round(4)); print(dl.round(4)); print(sd.round(4))
    print(lag.round(2).to_string())


if __name__ == "__main__":
    main()
