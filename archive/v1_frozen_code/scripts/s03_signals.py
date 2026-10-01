"""Step 3: first-buy episodes and second-buyer signals, for W = 30 (primary),
14 and 60 days. Built on ALL eligible disclosures (price match is applied
later), because the public saw every filing whether or not we can price it.

Output: output/intermediate/episodes_W{W}.parquet  (one row per episode)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402


def build(d: pd.DataFrame, W: int) -> pd.DataFrame:
    d = d.sort_values(["issuer_cik", "filing_date", "disc_id"]).reset_index(drop=True)
    recs = []
    for cik, g in d.groupby("issuer_cik", sort=False):
        dates = g["filing_date"].values.astype("datetime64[D]")
        owners = [set(o.split("|")) for o in g["owners"]]
        n = len(g)
        idx = g.index.values
        i = 0
        # a disclosure starts an episode if the previous disclosure (any) is >= W days earlier
        prev_gap = np.r_[np.inf, np.diff(dates).astype(int)]
        starts = np.where(prev_gap > 0)[0]  # first disclosure of each distinct date
        for s in starts:
            # any disclosure in [F-W, F)?
            F = dates[s]
            lo = np.searchsorted(dates, F - np.timedelta64(W, "D"), side="left")
            if lo < s:
                continue
            same = np.where(dates == F)[0]
            init_owners = set().union(*[owners[j] for j in same])
            n_init_groups = len(same)
            end = np.searchsorted(dates, F + np.timedelta64(W, "D"), side="right")
            later = range(same[-1] + 1, end)
            second = None
            repeats = []
            for j in later:
                if owners[j] & init_owners:
                    repeats.append(dates[j])
                elif second is None:
                    second = j
            first_rows = g.loc[idx[same]]
            rec = {
                "issuer_cik": cik, "W": W, "F": pd.Timestamp(F),
                "first_disc_ids": "|".join(first_rows["disc_id"]),
                "n_init_groups": n_init_groups, "same_day_cluster": n_init_groups >= 2,
                "init_owners": "|".join(sorted(init_owners)),
                "init_value": first_rows["value"].sum(),
                "init_role": "officer" if first_rows["any_officer"].any() else "director_only",
                "init_top": bool(first_rows["any_top"].any()),
                "init_plan": bool(first_rows["plan_10b5_1"].any()),
                "init_late": bool(first_rows["late_filed"].any()),
                "init_vwap": first_rows["value"].sum() / first_rows["shares"].sum(),
                "init_match_primary": bool(first_rows["match_primary"].all()) if "match_primary" in g else None,
                "init_match_strict": bool(first_rows["match_strict"].all()) if "match_strict" in g else None,
                "ticker": first_rows["ticker"].dropna().iloc[0] if "ticker" in g and first_rows["ticker"].notna().any() else None,
                "sic": first_rows["sic"].iloc[0], "issuer_name": first_rows["issuer_name"].iloc[0],
                "repeat_dates": [pd.Timestamp(x) for x in repeats],
            }
            if second is not None:
                S = dates[second]
                srows = g.loc[idx[np.where(dates == S)[0]]]
                srows = srows[[not (set(o.split("|")) & init_owners) for o in srows["owners"]]]
                rec.update({
                    "S": pd.Timestamp(S), "lag": int((S - F).astype(int)),
                    "second_disc_ids": "|".join(srows["disc_id"]),
                    "second_value": srows["value"].sum(),
                    "second_role": "officer" if srows["any_officer"].any() else "director_only",
                    "second_top": bool(srows["any_top"].any()),
                    "second_plan": bool(srows["plan_10b5_1"].any()),
                    "second_late": bool(srows["late_filed"].any()),
                    "second_match_primary": bool(srows["match_primary"].all()),
                    "second_match_strict": bool(srows["match_strict"].all()),
                    "second_ticker": srows["ticker"].dropna().iloc[0] if srows["ticker"].notna().any() else None,
                    "second_vwap": srows["value"].sum() / srows["shares"].sum(),
                    "n_second_groups": len(srows),
                })
            recs.append(rec)
    ep = pd.DataFrame(recs)
    ep["has_second"] = ep["S"].notna() if "S" in ep else False
    return ep


def main():
    d = pd.read_parquet(C.INTER / "disclosures_matched.parquet")
    ws = [int(a) for a in sys.argv[1:]] or [C.WINDOW] + C.ALT_WINDOWS
    for W in ws:
        ep = build(d, W)
        ep.to_parquet(C.INTER / f"episodes_W{W}.parquet", index=False)
        print(f"W={W}: episodes={len(ep):,}  same-day clusters={ep.same_day_cluster.sum():,}  "
              f"with second buyer={ep.has_second.sum():,}  "
              f"(second among single-start: {ep.loc[~ep.same_day_cluster, 'has_second'].mean():.3f})")


if __name__ == "__main__":
    main()
