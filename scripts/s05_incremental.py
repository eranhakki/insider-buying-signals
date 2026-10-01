"""Step 5: primary incremental-information test (landmark matching).

Usage: python s05_incremental.py [--final]
Without --final only development-period estimates are written; the test-period
estimate is produced once, with --final, after the specification is frozen.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402
from src.incremental import Spec, add_outcomes, balance, balance_detailed, build_pairs, dev_cuts, estimate, load_episodes  # noqa: E402
from src.prices import PriceStore  # noqa: E402


def run_spec(ps, spec: Spec, zscale=None):
    ep = load_episodes(spec)
    st, zs = build_pairs(ps, ep, spec, zscale)
    st = add_outcomes(ps, st, spec)
    return st, zs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    args = ap.parse_args()
    ps = PriceStore()
    spec = Spec()
    f = C.INTER / "stacked_primary.parquet"
    if f.exists():
        st = pd.read_parquet(f)
        zs = json.loads((C.INTER / "zscale.json").read_text())
    else:
        st, zs = run_spec(ps, spec)
        st.to_parquet(f, index=False)
        (C.INTER / "zscale.json").write_text(json.dumps({k: list(map(float, v)) for k, v in zs.items()}))
    dev = st[st["period"] == "dev"]
    cuts = dev_cuts(dev)
    (C.INTER / "dev_cuts.json").write_text(json.dumps({k: list(map(float, v)) for k, v in cuts.items()}))

    periods = ["dev", "test"] if args.final else ["dev"]
    rows = []
    for per in periods:
        s = st[st["period"] == per]
        for h in C.HORIZONS:
            r = estimate(s, h, cuts, boot=C.BOOT)
            r["period"] = per
            rows.append(r)
        b = balance(s)
        b.insert(0, "period", per)
        b.to_csv(C.TABLES / f"balance_{per}.csv", index=False)
        # POST-REVIEW: distribution summaries on raw and as-used (clipped) variables
        bd = balance_detailed(s, cuts, zs)
        bd.insert(0, "period", per)
        bd.to_csv(C.TABLES / f"balance_detailed_{per}.csv", index=False)
        print(f"\n--- balance ({per})\n", b.round(3).to_string(index=False))
    res = pd.DataFrame(rows)
    suffix = "" if args.final else "_devonly"
    res.to_csv(C.TABLES / f"incremental_primary{suffix}.csv", index=False)
    cols = ["period", "h", "n_treated", "treated_issuers", "n_control_episodes", "mean_treated", "mean_control",
            "match_diff", "match_lo", "match_hi", "boot_lo", "boot_hi", "reg_coef", "reg_lo", "reg_hi", "reg_p"]
    print(res[cols].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
