"""Step 2: link issuers to Tiingo tickers and validate each link with the
reported purchase price.

Output: output/intermediate/disclosures_matched.parquet
Tables: price_match_summary.csv, price_match_by_year.csv, failed_price_matches.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402
from src.prices import PriceStore, norm_symbol  # noqa: E402


def main():
    ps = PriceStore()
    print(f"price store: {len(ps.tickers):,} tickers x {len(ps.dates):,} days")
    d = pd.read_parquet(C.INTER / "disclosures.parquet")

    # candidate tickers, in priority order
    def cands(r):
        out = []
        for t in [r["sec_symbol"]] + (str(r["edgar_tickers"]).split("|") if pd.notna(r["edgar_tickers"]) else []):
            t = norm_symbol(t)
            if t and t not in out:
                out.append(t)
        return out
    d["cands"] = d.apply(cands, axis=1)
    long = d[["disc_id", "issuer_cik", "trans_date_max", "vwap", "cands"]].explode("cands").dropna(subset=["cands"])
    long["rank"] = long.groupby("disc_id").cumcount()
    long["row"] = ps.row(long["cands"])
    long = long[long["row"] >= 0].copy()
    # unadjusted close on the transaction date (or the previous trading day, up to 5 days back)
    ti = ps.idx_on_or_before(long["trans_date_max"])
    px = np.full(len(long), np.nan)
    r = long["row"].values
    for back in range(0, 6):
        miss = np.isnan(px) & (ti - back >= 0)
        px[miss] = ps.close[r[miss], ti[miss] - back]
    long["close_on_trade"] = px
    long["ratio"] = long["vwap"] / long["close_on_trade"]
    med = long.groupby(["issuer_cik", "cands"])["ratio"].median().rename("issuer_ticker_median")
    long = long.join(med, on=["issuer_cik", "cands"])
    lo, hi = C.MATCH_ISSUER_BAND
    long["link_ok"] = long["issuer_ticker_median"].between(lo, hi)
    usable = long[long["link_ok"] & long["ratio"].notna()].sort_values(["disc_id", "rank"])
    best = usable.drop_duplicates("disc_id")[["disc_id", "cands", "rank", "ratio", "issuer_ticker_median"]]
    best = best.rename(columns={"cands": "ticker", "rank": "cand_rank"})
    d = d.merge(best, on="disc_id", how="left")

    has_any_cand = d["cands"].str.len() > 0
    tried = long.groupby("disc_id").size()
    d["n_cands_with_prices"] = d["disc_id"].map(tried).fillna(0).astype(int)
    lo_e, hi_e = C.MATCH_EVENT_BAND
    lo_s, hi_s = C.MATCH_STRICT_BAND
    d["match_status"] = np.select(
        [~has_any_cand, d["n_cands_with_prices"] == 0, d["ticker"].isna(),
         ~d["ratio"].between(lo_e, hi_e), d["ratio"].between(lo_e, hi_e)],
        ["no usable symbol", "no Tiingo prices near event (absent or reused symbol)", "no link passes price check",
         "event price outside [0.67,1.5]", "matched"], default="other")
    d["match_primary"] = d["match_status"].eq("matched")
    d["match_strict"] = d["match_primary"] & d["ratio"].between(lo_s, hi_s)
    d["ticker_source"] = np.where(d["cand_rank"] == 0, "Form 4 symbol", np.where(d["cand_rank"] > 0, "EDGAR current ticker", ""))
    d = d.drop(columns=["cands"])
    d.to_parquet(C.INTER / "disclosures_matched.parquet", index=False)

    s = d["match_status"].value_counts().rename("disclosures").to_frame()
    s["share"] = s["disclosures"] / len(d)
    s.loc["strict match [0.9,1.1]", "disclosures"] = int(d["match_strict"].sum())
    s.loc["strict match [0.9,1.1]", "share"] = d["match_strict"].mean()
    s.to_csv(C.TABLES / "price_match_summary.csv")
    print(s)
    print(d.loc[d.match_primary, "ticker_source"].value_counts())
    y = d.assign(year=d["filing_date"].dt.year).groupby("year").agg(
        disclosures=("disc_id", "size"), matched=("match_primary", "mean"), strict=("match_strict", "mean"),
        not_in_tiingo=("match_status", lambda x: (x == "no Tiingo prices near event (absent or reused symbol)").mean()),
        no_link=("match_status", lambda x: (x == "no link passes price check").mean()))
    y.to_csv(C.TABLES / "price_match_by_year.csv")
    print(y.round(3))
    fails = d[~d["match_primary"]].sample(min(300, (~d["match_primary"]).sum()), random_state=C.SEED)
    fails[["disc_id", "issuer_cik", "issuer_name", "sec_symbol", "edgar_tickers", "filing_date", "vwap",
           "ratio", "match_status"]].to_csv(C.TABLES / "failed_price_matches_sample.csv", index=False)


if __name__ == "__main__":
    main()
