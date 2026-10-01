"""Price store: Tiingo prices as dense (ticker x trading-day) float32 matrices
on the SPY trading calendar, plus helpers for returns and covariates."""
from __future__ import annotations

import re

import bottleneck as bn
import numpy as np
import pandas as pd

from . import config as C


class PriceStore:
    def __init__(self, cache: bool = True, quality: str | None = None):
        self.quality = quality or C.PRICE_QUALITY
        f = C.PRICE_CACHE
        if cache and f.exists():
            z = np.load(f, allow_pickle=True)
            self.dates = pd.DatetimeIndex(z["dates"])
            self.tickers = list(z["tickers"])
            for k in ("adj", "adjo", "close", "dv", "dvmed60", "last_idx"):
                setattr(self, k, z[k])
        else:
            self._build()
            np.savez(f, dates=self.dates.values, tickers=np.array(self.tickers, dtype=object),
                     adj=self.adj, adjo=self.adjo, close=self.close, dv=self.dv,
                     dvmed60=self.dvmed60, last_idx=self.last_idx)
        self.tix = {t: i for i, t in enumerate(self.tickers)}
        self.d64 = self.dates.values.astype("datetime64[D]")
        self.breaks_all, self.breaks_cov = {}, {}
        if self.quality == "v2":
            self._apply_quality_fixes()

    # POST-REVIEW: corrections from scripts/r01_price_quality.py (see that file for the classes)
    def _apply_quality_fixes(self):
        fl = pd.read_parquet(C.PRICE_FLAGS).rename(columns={"class": "cls"})
        touched = set()
        for x in fl.itertuples(index=False):
            r = int(x.row)
            if x.cls == "stale_placeholder":
                sl = slice(int(x.run_start_idx), int(x.prev_idx) + 1)       # the dormant quotes
                self.breaks_all.setdefault(r, []).append(int(x.jump_idx))
            elif x.cls == "reversing_spike":
                sl = slice(int(x.jump_idx), int(x.rev_end_idx))             # the spike days
            elif x.cls == "data_gap_splice":
                self.breaks_all.setdefault(r, []).append(int(x.jump_idx))
                continue
            elif x.cls == "implausible_magnitude":
                self.breaks_cov.setdefault(r, []).append(int(x.jump_idx))
                continue
            else:
                continue
            for m in (self.adj, self.adjo, self.close, self.dv):
                m[r, sl] = np.nan
            touched.add(r)
        if touched:
            rows = np.array(sorted(touched))
            self.dvmed60[rows] = bn.move_median(self.dv[rows], window=60, min_count=20, axis=1)
            has = ~np.isnan(self.adj[rows])
            self.last_idx[rows] = np.where(has.any(1), has.shape[1] - 1 - np.argmax(has[:, ::-1], axis=1), -1)
        self.breaks_all = {r: np.array(sorted(v)) for r, v in self.breaks_all.items()}
        self.breaks_cov = {r: np.array(sorted(v)) for r, v in self.breaks_cov.items()}

    def spans_break(self, rows, lo, hi, which: str = "all") -> np.ndarray:
        """True where a series break lies in (lo, hi] for that row: a return over the window
        would compare prices from two different regimes. which='cov' adds implausible-magnitude breaks."""
        out = np.zeros(len(rows), bool)
        if self.quality != "v2":
            return out
        rows, lo, hi = np.asarray(rows), np.asarray(lo), np.asarray(hi)
        for src in ([self.breaks_all] if which == "all" else [self.breaks_all, self.breaks_cov]):
            for r, b in src.items():
                ii = np.where(rows == r)[0]
                if len(ii) == 0:
                    continue
                k = np.searchsorted(b, lo[ii], side="right")         # first break > lo
                out[ii] |= (k < len(b)) & (b[np.minimum(k, len(b) - 1)] <= hi[ii])
        return out

    def _build(self):
        p = pd.read_parquet(C.RAW / "tiingo_prices.parquet")
        p["date"] = pd.to_datetime(p["date"])
        spy = p[p["ticker"] == C.BENCH].sort_values("date")
        self.dates = pd.DatetimeIndex(spy["date"].unique())
        self.tickers = sorted(p["ticker"].unique())
        tix = {t: i for i, t in enumerate(self.tickers)}
        di = pd.Series(np.arange(len(self.dates)), index=self.dates)
        p = p[p["date"].isin(self.dates)]
        r = p["ticker"].map(tix).values
        c = di.reindex(p["date"]).values
        shape = (len(self.tickers), len(self.dates))
        mats = {}
        for name, col in [("adj", "adjClose"), ("adjo", "adjOpen"), ("close", "close")]:
            m = np.full(shape, np.nan, dtype=np.float32)
            m[r, c] = p[col].values.astype(np.float32)
            m[m <= 0] = np.nan
            mats[name] = m
        dv = np.full(shape, np.nan, dtype=np.float32)
        dv[r, c] = (p["close"].values * p["volume"].values).astype(np.float32)
        self.adj, self.adjo, self.close, self.dv = mats["adj"], mats["adjo"], mats["close"], dv
        # median daily dollar volume over the 60 trading days ending at each day
        self.dvmed60 = bn.move_median(dv, window=60, min_count=20, axis=1).astype(np.float32)
        # last trading-day index with a price, per ticker (delisting / end of data)
        has = ~np.isnan(self.adj)
        self.last_idx = np.where(has.any(1), has.shape[1] - 1 - np.argmax(has[:, ::-1], axis=1), -1)

    # ---------------------------------------------------------------- dates
    def idx_on_or_before(self, d) -> np.ndarray:
        d = np.asarray(pd.to_datetime(d).values.astype("datetime64[D]"))
        return np.searchsorted(self.d64, d, side="right") - 1

    def idx_after(self, d) -> np.ndarray:
        d = np.asarray(pd.to_datetime(d).values.astype("datetime64[D]"))
        return np.searchsorted(self.d64, d, side="right")

    def row(self, tickers) -> np.ndarray:
        return np.array([self.tix.get(t, -1) for t in tickers])


def norm_symbol(s) -> str | None:
    if s is None or (isinstance(s, float) and np.isnan(s)) or s is pd.NA:
        return None
    s = str(s).strip().upper().lstrip("$")
    s = re.split(r"[\s,;]+", s)[0] if s else s
    s = re.sub(r"\.(OB|PK|OTC|OTCBB|BB|Q)$", "", s)
    s = s.replace(".", "-").replace("/", "-")
    if s in {"", "NONE", "N/A", "NA", "NULL", "-", "--"} or not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", s):
        return None
    return s


def entry_index(ps: PriceStore, filing_dates, rule: str) -> np.ndarray:
    after = ps.idx_after(filing_dates)          # first trading day strictly after D
    if rule in ("t1_close", "t1_open"):
        return after
    if rule == "t2_close":
        return after + 1
    if rule == "t0_close":
        return ps.idx_on_or_before(filing_dates)
    raise ValueError(rule)


def event_returns(ps: PriceStore, rows: np.ndarray, filing_dates, rule: str, h: int,
                  bench: str = C.BENCH, bench_rows: np.ndarray | None = None) -> pd.DataFrame:
    """Buy-and-hold returns from entry to entry+h trading days.

    Entry must have a price on the entry day or within the next 2 trading days.
    If the series ends before the horizon the return runs to the last price
    (flag `incomplete`, `delisted` if Tiingo has no later data at all)."""
    n = len(rows)
    T = len(ps.dates)
    e0 = entry_index(ps, filing_dates, rule)
    out = {k: np.full(n, np.nan) for k in ("ret", "bret", "entry_px")}
    incomplete = np.zeros(n, bool)
    delisted = np.zeros(n, bool)
    e_used = np.full(n, -1)
    use_open = rule == "t1_open"
    for shift in (0, 1, 2):
        need = np.isnan(out["entry_px"]) & (rows >= 0) & (e0 + shift < T)
        if not need.any():
            break
        ii = np.where(need)[0]
        m = ps.adjo if (use_open and shift == 0) else ps.adj
        px = m[rows[ii], e0[ii] + shift]
        ok = ~np.isnan(px)
        out["entry_px"][ii[ok]] = px[ok]
        e_used[ii[ok]] = e0[ii[ok]] + shift
    good = ~np.isnan(out["entry_px"])
    tgt = np.where(good, e_used + h, -1)
    in_range = good & (tgt < T)
    end_used = np.full(n, -1)
    brow = ps.tix[bench]
    for i in np.where(in_range)[0]:
        r, a, b = rows[i], e_used[i], tgt[i]
        seg = ps.adj[r, a:b + 1]
        j = np.where(~np.isnan(seg))[0][-1]           # last available price at or before target
        out["ret"][i] = seg[j] / out["entry_px"][i] - 1.0
        end_used[i] = a + j
        if j < (b - a) - 5:
            incomplete[i] = True
            delisted[i] = ps.last_idx[r] < b
        br = brow if bench_rows is None else bench_rows[i]
        if br is None or br < 0:
            continue
        # benchmark over exactly the same days the stock was held
        m0 = ps.adjo[br, a] if (use_open and a == e0[i]) else ps.adj[br, a]
        out["bret"][i] = ps.adj[br, a + j] / m0 - 1.0
    df = pd.DataFrame({"entry_idx": e_used, "end_idx": end_used, "ret": out["ret"], "bench_ret": out["bret"],
                       "incomplete": incomplete, "delisted": delisted})
    df["xret"] = df["ret"] - df["bench_ret"]
    df.loc[~in_range, ["ret", "xret"]] = np.nan
    if ps.quality == "v2":   # POST-REVIEW: no return across a splice or stale-quote break
        brk = ps.spans_break(rows, e_used - 1, np.where(in_range, tgt, -1), "all") & in_range
        df.loc[brk, ["ret", "xret"]] = np.nan
        df["quality_break"] = brk
    return df


def covariates(ps: PriceStore, rows: np.ndarray, asof_dates) -> pd.DataFrame:
    """Known-at-time covariates using prices up to the last trading day <= as-of date."""
    d0 = ps.idx_on_or_before(asof_dates)
    n = len(rows)
    res = {k: np.full(n, np.nan) for k in ("ret_21", "ret_126", "log_dv", "log_price", "vol_60", "px")}
    ok = (rows >= 0) & (d0 >= 130)
    ii = np.where(ok)[0]
    r, d = rows[ii], d0[ii]
    # most recent price within 5 days (ffill)
    p0 = ps.adj[r, d]
    for back in range(1, 6):
        miss = np.isnan(p0)
        p0[miss] = ps.adj[r[miss], d[miss] - back]
    res["ret_21"][ii] = p0 / ps.adj[r, d - 21] - 1
    res["ret_126"][ii] = p0 / ps.adj[r, d - 126] - 1
    res["log_dv"][ii] = np.log(np.maximum(ps.dvmed60[r, d], 1.0))
    c0 = ps.close[r, d]
    for back in range(1, 6):
        miss = np.isnan(c0)
        c0[miss] = ps.close[r[miss], d[miss] - back]
    res["px"][ii] = c0
    res["log_price"][ii] = np.log(c0)
    # 60-day realised volatility of daily returns
    win = np.arange(-60, 1)
    block = ps.adj[r[:, None], d[:, None] + win[None, :]]
    lr = np.diff(np.log(block), axis=1)
    res["vol_60"][ii] = np.nanstd(lr, axis=1) * np.sqrt(252)
    if ps.quality == "v2":   # POST-REVIEW: covariate window may not span any break
        brk = ps.spans_break(rows[ii], d - 127, d, "cov")
        for k in ("ret_21", "ret_126", "vol_60"):
            res[k][ii[brk]] = np.nan
    return pd.DataFrame(res)
