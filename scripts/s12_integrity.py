"""Step 12: research-integrity checks. Writes output/integrity_report.md and
exits non-zero if any hard check fails.

1. raw-data checksums against the download manifest
2. analysis plan: original hash reproducible; code unchanged since the pre-test freeze
3. headline estimate re-derived with independent code (statsmodels formula API)
4. event-study headline means re-derived from the event file
5. counts reconciled across parquet files, tables and documents
6. every number quoted in README/paper comes from numbers.json; no unfilled placeholders
7. figures referenced in the paper exist
8. no API key or raw licensed prices in the shippable tree
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as cfg  # noqa: E402  (not 'C': patsy's C() is used in formulas)

R = []


def check(name, ok, detail="", hard=True):
    R.append((name, bool(ok), detail, hard))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# Numbers typed directly into the document templates (not inserted from numbers.json), with the reason each is allowed.
DECLARED = {
    # design constants from docs/ANALYSIS_PLAN.md and src/config.py
    "0", "1", "2", "3", "4", "5", "10", "14", "15", "20", "21", "30", "60", "90", "99", "126", "300", "365", "1,000",
    "0.05", "0.67", "0.8", "0.9", "1.1", "1.25", "1.5", "$1", "$5", "1%", "10%", "20%", "95%", "100%", "200%", "1000%",
    "−30%", "−90%", "3×", "10×", "85%",
    # section / table / figure numbers and version labels
    "5.1", "5.2", "5.3", "5.4", "7.1", "7.2", "6", "7", "8", "9", "3.11", "256", "401", "500", "6722", "6726",
    # hand-audit facts recorded in docs/audit/filing_audit_35.csv
    "$0.28", "2.5", "$35.00", "16", "29",
    # dates
    "20260930"}


def literal_scan(root):
    bad = set()
    for f in ["paper/paper_template.md", "docs/README_template.md", "docs/DATA_AUDIT_template.md",
              "docs/POST_REVIEW_CHANGES_template.md"]:
        t = (root / f).read_text()
        if "# References" in t:
            t = t[: t.index("# References")]
        t = re.sub(r"^---.*?^---", "", t, flags=re.S | re.M)
        t = re.sub(r"```.*?```", "", t, flags=re.S)
        t = re.sub(r"\{\{[^}]*\}\}", "", t)
        t = re.sub(r"\]\([^)]*\)", "]", t)
        t = re.sub(r"https?://\S+", "", t)
        t = re.sub(r"`[^`]*`", "", t)
        for m in re.finditer(r"(?<![\w.])[-+−]?\$?\d[\d,]*(?:\.\d+)?%?×?", t):
            tok = m.group(0).rstrip(",")
            if tok in DECLARED or (tok.isdigit() and 1986 <= int(tok) <= 2026):
                continue
            bad.add(f"{f}:{tok}")
    return sorted(bad)


def main():
    root = cfg.ROOT
    # 1. raw data
    man = json.loads((cfg.RAW / "manifest.json").read_text())
    bad = [f for f, v in man["files"].items() if sha(cfg.RAW / f) != v["sha256"]]
    check("Raw data files match download-manifest SHA-256", not bad, f"{len(man['files'])} files; mismatches: {bad}")

    # 2. plan and freeze
    plan = (root / "docs" / "ANALYSIS_PLAN.md").read_text()
    recorded = (root / "docs" / "ANALYSIS_PLAN.sha256").read_text().split()[0]
    original = plan[: plan.index("## Deviations")] + "## Deviations\n\n(none yet)\n"
    check("Original analysis plan reproducible from current file (deviations only appended)",
          hashlib.sha256(original.encode()).hexdigest() == recorded, f"recorded {recorded[:12]}…")
    fz = (root / "docs" / "FREEZE_before_test.txt").read_text().splitlines()[1:]
    changed = []
    arch = root / "archive" / "v1_frozen_code"
    for line in fz:
        h, f = line.split()
        if f.startswith("docs/"):
            continue
        if sha(arch / f) != h:
            changed.append(f)
    check("Archived v1 code is byte-identical to the code frozen before the test period", not changed,
          f"{len(fz) - 1} files; mismatches: {changed or 'none'}")
    # POST-REVIEW: the live code runs the frozen logic under PRICE_QUALITY=v1; its outputs must equal the originals
    orig, rep = root / "output" / "original_v1" / "tables", root / "output" / "v1_reproduced" / "tables"
    same, diff = 0, []
    for f in ["sample_construction_legs.csv", "disclosure_summary.csv", "price_match_summary.csv",
              "event_study_summary.csv", "calendar_time.csv", "incremental_primary.csv", "balance_dev.csv", "balance_test.csv"]:
        if not (rep / f).exists():
            diff.append(f + " (missing)")
            continue
        a, b = pd.read_csv(orig / f), pd.read_csv(rep / f)
        num = a.select_dtypes("number").columns
        ok = a.shape == b.shape and np.allclose(a[num].values.astype(float), b[num].values.astype(float), rtol=1e-9,
                                                atol=1e-12, equal_nan=True)
        same += ok
        if not ok:
            diff.append(f)
    check("Regenerated original (v1) outputs equal the preserved originals", not diff,
          f"{same} tables identical; differing: {diff or 'none'}")

    # 3. headline re-derivation
    st = pd.read_parquet(cfg.INTER / "stacked_primary.parquet")
    cuts = {k: tuple(v) for k, v in json.loads((cfg.INTER / "dev_cuts.json").read_text()).items()}
    inc = pd.read_csv(cfg.TABLES / "incremental_primary.csv")
    for per in ["dev", "test"]:
        s = st[st.period == per].copy()
        s["y"] = s["y60"].clip(*cuts["y60"])
        s = s[s.y.notna()]
        pairs = set(s[s.treated == 1].pair) & set(s[s.treated == 0].pair)
        s = s[s.pair.isin(pairs)].copy()
        nc = s[s.treated == 0].groupby("pair").size()
        s["w"] = np.where(s.treated == 1, 1.0, 1.0 / s.pair.map(nc))
        diff = (s[s.treated == 1].set_index("pair").y - s[s.treated == 0].groupby("pair").y.mean()).mean()
        for c in ["ret_21", "ret_126", "vol_60"]:
            s[c] = s[c].clip(*cuts[c])
        s["officer_init"] = (s.init_role == "officer").astype(float)
        s["top_init"] = s.init_top.astype(float)
        f = ("y ~ treated + ret_21 + ret_126 + log_dv + log_price + vol_60 + log_init_value + n_repeats_asof + lag_k"
             " + officer_init + top_init + C(year) + C(sic_div)")
        s = s.dropna(subset=["ret_21", "ret_126", "log_dv", "log_price", "vol_60", "log_init_value"])
        g = np.column_stack([pd.factorize(s.issuer_cik.astype(str))[0], pd.factorize(s.month)[0]])
        m = smf.wls(f, data=s, weights=s.w).fit(cov_type="cluster", cov_kwds={"groups": g})
        row = inc[(inc.period == per) & (inc.h == 60)].iloc[0]
        check(f"{per}: matched difference re-derived", abs(diff - row.match_diff) < 1e-10,
              f"{diff:.6f} vs table {row.match_diff:.6f}")
        check(f"{per}: regression coefficient re-derived (formula API)", abs(m.params["treated"] - row.reg_coef) < 1e-8,
              f"{m.params['treated']:.6f} vs {row.reg_coef:.6f}")
        check(f"{per}: two-way clustered SE re-derived", abs(m.bse["treated"] - row.reg_se) < 1e-8,
              f"{m.bse['treated']:.6f} vs {row.reg_se:.6f}")

    # 4. event-study means
    ev = pd.read_parquet(cfg.INTER / "events_W30.parquet")
    u = ev[ev.match_primary.fillna(False).astype(bool) & (ev.px >= cfg.MIN_PRICE) & ev.row.ge(0)]
    et = pd.read_csv(cfg.TABLES / "event_study_table.csv")
    for per, t in [("dev", "SB"), ("test", "FB_single")]:
        x = u[(u.period == per) & (u.etype == t)][f"xret_{cfg.ENTRY}_h60"].dropna()
        tv = et[(et.period == per) & (et.event == t) & (et.h == 60) & (et.measure == "SPY-adj")].iloc[0]
        check(f"Event study {per} {t} mean and N re-derived", abs(x.mean() - tv["mean"]) < 1e-10 and len(x) == tv.n,
              f"{x.mean():.6f}/{len(x)} vs {tv['mean']:.6f}/{int(tv.n)}")

    # 5. counts
    d = pd.read_parquet(cfg.INTER / "disclosures_matched.parquet")
    sc = pd.read_csv(cfg.TABLES / "sample_construction.csv")
    g = dict(zip(sc.step, sc["count"]))
    check("Disclosure count: parquet = sample table", len(d) == int(g["grouped into disclosures (issuer x filing date x owner group)"]))
    ep = pd.read_parquet(cfg.INTER / "episodes_W30.parquet")
    check("Episode count: parquet = sample table", len(ep) == int(g["first-buy episodes (W = 30)"]))
    rb = pd.read_csv(cfg.TABLES / "robustness.csv")
    p0 = rb[(rb.check == "Primary specification") & (rb.h == 60)].set_index("period")
    check("Robustness table primary row = primary table",
          all(abs(p0.loc[p, "reg_coef"] - inc[(inc.period == p) & (inc.h == 60)].reg_coef.iloc[0]) < 1e-12 for p in ["dev", "test"]))

    # 6. documents
    N = json.loads((root / "output" / "numbers.json").read_text())
    for doc in ["README.md", "paper/paper.md", "docs/DATA_AUDIT.md", "POST_REVIEW_CHANGES.md"]:
        txt = (root / doc).read_text()
        check(f"{doc}: no unfilled placeholders", "{{" not in txt)
        for k in ["inc_test_60_reg", "inc_test_60_reg_ci"]:
            if doc != "docs/DATA_AUDIT.md":
                check(f"{doc}: quotes {k} = {N[k]}", N[k] in txt)
    v1 = pd.read_csv(root / "output" / "original_v1" / "tables" / "incremental_primary.csv")
    x = v1[(v1.period == "test") & (v1.h == 60)].iloc[0]
    check("numbers.json original (v1) test estimate equals the preserved v1 table",
          N["v1_inc_test_60_reg"] == f"{x.reg_coef*100:+.2f} pp" and N["v1_inc_test_60_n"] == f"{int(x.n_treated):,}",
          f"{N['v1_inc_test_60_reg']} (n = {N['v1_inc_test_60_n']})")
    for doc in ["README.md", "paper/paper.md", "POST_REVIEW_CHANGES.md"]:
        txt = (root / doc).read_text()
        check(f"{doc}: quotes both the original and the corrected test estimate",
              N["v1_inc_test_60_reg"] in txt and N["inc_test_60_reg"] in txt and N["v1_inc_test_60_reg_ci"] in txt)
    bad = literal_scan(root)
    check("Every number written directly in a document template is a declared design constant, date or label "
          "(all other numbers are inserted from numbers.json)", not bad, f"undeclared literals: {bad or 'none'}")
    for k, col in [("inc_test_60_n", "n_treated"), ("inc_dev_60_n", "n_treated")]:
        per = k.split("_")[1]
        check(f"numbers.json {k} matches table", N[k] == f"{int(inc[(inc.period == per) & (inc.h == 60)][col].iloc[0]):,}")

    # 7. figures
    pm = (root / "paper" / "paper.md").read_text()
    figs = re.findall(r"\]\((\.\./output/figures/[^)]+)\)", pm)
    missing = [f for f in figs if not (root / "paper" / f).resolve().exists()]
    check("All figures referenced in the paper exist", not missing and len(figs) >= 6, f"{len(figs)} referenced; missing {missing}")
    check("Paper PDF exists", (root / "paper" / "paper.pdf").exists())

    # 8. secrets / licensed data in shippable tree
    ship = [p for p in root.rglob("*") if p.is_file() and "data/raw" not in str(p) and "output/intermediate" not in str(p)
            and ".venv" not in str(p) and p.suffix in {".py", ".md", ".csv", ".json", ".txt", ".sh", ".tex"}]
    hits = [str(p.relative_to(root)) for p in ship if re.search(r"Token [0-9a-f]{40}|token=[0-9a-f]{40}", p.read_text(errors="ignore"))]
    check("No Tiingo API key in any shippable file", not hits, f"{len(ship)} files scanned")
    big = [str(p.relative_to(root)) for p in root.rglob("*.parquet") if "data/raw" not in str(p) and "output/intermediate" not in str(p) and ".venv" not in str(p) and "output/results" not in str(p)]
    check("No raw price files outside data/raw and output/intermediate", not big, str(big))

    lines = ["# Integrity report", "", f"Generated by `scripts/s12_integrity.py`.", "",
             "| Check | Result | Detail |", "|---|---|---|"]
    for name, ok, det, hard in R:
        lines.append(f"| {name} | {'PASS' if ok else ('FAIL' if hard else 'WARN')} | {det} |")
    (root / "output" / "integrity_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if not all(ok for _, ok, _, hard in R if hard):
        sys.exit(1)


if __name__ == "__main__":
    main()
