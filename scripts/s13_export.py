"""Step 13: event-level and matched-sample results for reviewers.
Returns and signal attributes only - no raw Tiingo price levels are exported."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402


def main():
    out = C.ROOT / "output" / "results"
    out.mkdir(exist_ok=True)
    ev = pd.read_parquet(C.INTER / "events_W30.parquet")
    u = ev[ev.match_primary.fillna(False).astype(bool) & (ev.px >= C.MIN_PRICE) & ev.row.ge(0)]
    cols = (["event_id", "etype", "period", "issuer_cik", "issuer_name", "tkr", "sic", "date", "F", "S", "lag", "role",
             "value", "plan", "late", "ret_21", "ret_126", "log_dv", "vol_60"]
            + [c for c in ev.columns if c.startswith(("ret_t", "xret_"))] + ["incomplete_h60", "delisted_h60"])
    u[cols].to_parquet(out / "events_W30_returns.parquet", index=False, compression="zstd")
    st = pd.read_parquet(C.INTER / "stacked_primary.parquet")
    sc = ["pair", "treated", "w", "ep_id", "issuer_cik", "issuer_name", "ticker", "period", "date", "F", "S", "lag_k",
          "dist", "init_role", "init_top", "init_value", "second_role", "second_value", "n_repeats_asof", "ret_21",
          "ret_126", "log_dv", "vol_60", "year", "month", "y20", "y60", "incomplete60", "delisted60"]
    st[sc].to_parquet(out / "matched_sample_primary.parquet", index=False, compression="zstd")
    print("exported", len(u), "events and", len(st), "matched rows")


if __name__ == "__main__":
    main()
