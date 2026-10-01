"""Step 11: fill the paper / README / audit templates from output/numbers.json
and the tables, then render the paper to PDF with pandoc + xelatex.
Fails if any {{placeholder}} is left unfilled."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as C  # noqa: E402

T = C.TABLES
N = json.loads((C.ROOT / "output" / "numbers.json").read_text())


def md(df: pd.DataFrame, caption: str = "") -> str:
    out = df.to_markdown(index=False, disable_numparse=True)
    return out + (f"\n\n: {caption}" if caption else "")


def table_sample():
    sc = pd.read_csv(T / "sample_construction.csv")
    inc = pd.read_csv(T / "incremental_primary.csv")
    for per in ["dev", "test"]:
        x = inc[(inc.period == per) & (inc.h == C.PRIMARY_H)].iloc[0]
        sc.loc[len(sc)] = [f"matched test {per}: signals with a 60-day outcome (primary estimate)", str(int(x.n_treated)), "signals"]
    sc["step"] = sc["step"].str.replace(">=", "≥").str.replace("event study ", "Event study: ").str.replace(
        "matched test ", "Matched test: ").str.replace("FB_single", "first buy (single)").str.replace(
        "FB_cluster", "first buy (same-day cluster)").str.replace(" SB ", " second buyer ")
    sc["count"] = sc["count"].map(lambda v: f"{int(v):,}" if str(v).isdigit() else v)
    sc = sc.rename(columns={"step": "Step", "count": "Remaining", "unit": "Unit"})
    return md(sc, "Sample construction, from every P-code row in the SEC data sets to the matched test sample. "
                  "Leg-level filters are applied in order; each row shows what remains.")


def table_events():
    t = pd.read_csv(T / "event_study_table.csv")
    t = t[t.h == 60]
    lab = {"FB_single": "First buy, single buyer", "FB_cluster": "First buy, 2+ buyers same day", "SB": "Second-buyer disclosure"}
    rows = []
    for per in ["dev", "test"]:
        for ev in ["FB_single", "FB_cluster", "SB"]:
            x = t[(t.period == per) & (t.event == ev)].set_index("measure")
            s, i = x.loc["SPY-adj"], x.loc["IWM-adj"]
            rows.append({"Period": {"dev": "Dev", "test": "Test"}[per], "Signal": lab[ev], "N": f"{int(s.n):,}",
                         "Issuers": "", "Raw mean": f"{x.loc['raw', 'mean']*100:+.2f}",
                         "SPY-adj mean [95% CI]": f"{s['mean']*100:+.2f} [{s.lo*100:+.2f}, {s.hi*100:+.2f}]",
                         "SPY-adj median": f"{s['median']*100:+.2f}",
                         "IWM-adj mean [95% CI]": f"{i['mean']*100:+.2f} [{i.lo*100:+.2f}, {i.hi*100:+.2f}]",
                         "% > 0": f"{s.share_pos*100:.0f}"})
    df = pd.DataFrame(rows).drop(columns=["Issuers"])
    return md(df, "Event study, 60 trading days from the t+1 close, in percent. CIs from standard errors clustered by "
                  "issuer and signal month. Means are not winsorised.")


def table_main():
    r = pd.read_csv(T / "incremental_primary.csv")
    rows = []
    for _, x in r.iterrows():
        rows.append({"Period": {"dev": "2006–18 (dev)", "test": "2019–26 (test)"}[x.period], "Horizon": f"{int(x.h)}d",
                     "Signals (issuers)": f"{int(x.n_treated):,} ({int(x.treated_issuers):,})",
                     "Control episodes": f"{int(x.n_control_episodes):,}",
                     "Treated mean": f"{x.mean_treated*100:+.2f}", "Control mean": f"{x.mean_control*100:+.2f}",
                     "Matched diff [95% CI]": f"{x.match_diff*100:+.2f} [{x.match_lo*100:+.2f}, {x.match_hi*100:+.2f}]",
                     "Regression-adjusted [95% CI]": f"**{x.reg_coef*100:+.2f}** [{x.reg_lo*100:+.2f}, {x.reg_hi*100:+.2f}]",
                     "p": f"{x.reg_p:.3f}"})
    return md(pd.DataFrame(rows), "Primary incremental test: second-buyer signal vs up to five landmark-matched single-buyer "
                                  "episodes. Winsorised SPY-adjusted returns in percentage points. Regression-adjusted "
                                  "estimate is primary; SEs clustered by issuer and month.")


def table_balance():
    rows = []
    lab = {"ret_21": "prior 21-day return", "ret_126": "prior 126-day return", "log_dv": "log median $ volume",
           "log_price": "log price", "vol_60": "60-day volatility", "log_init_value": "log initial purchase $",
           "n_repeats_asof": "repeat buys by initial buyer", "lag_k": "episode age (days)"}
    for per in ["dev", "test"]:
        b = pd.read_csv(T / f"balance_detailed_{per}.csv")
        b = b[b.form == "as used"]
        for _, x in b.iterrows():
            rows.append({"Period": {"dev": "Dev", "test": "Test"}[per], "Variable (as used)": lab.get(x.variable, x.variable),
                         "Treated mean / median": f"{x.treated_mean:.3f} / {x.treated_median:.3f}",
                         "Control mean / median": f"{x.control_mean:.3f} / {x.control_median:.3f}",
                         "Treated p10–p90": f"{x.treated_p10:.2f} – {x.treated_p90:.2f}",
                         "Control p10–p90": f"{x.control_p10:.2f} – {x.control_p90:.2f}",
                         "Std. diff.": f"{x.std_diff_mean:+.3f}", "Var. ratio": f"{x.variance_ratio:.2f}"})
    return md(pd.DataFrame(rows), "Matched balance on the variables as used (clipped at development 1st/99th percentiles), "
                                  "corrected data. Control statistics weighted 1/number of controls. Raw-variable versions: "
                                  "output/tables/balance_detailed_*.csv.")


def table_revision():
    a = pd.read_csv(C.ROOT / "output" / "original_v1" / "tables" / "incremental_primary.csv")
    b = pd.read_csv(T / "incremental_primary.csv")
    rows = []
    for per in ["dev", "test"]:
        for h in C.HORIZONS:
            x = a[(a.period == per) & (a.h == h)].iloc[0]
            y = b[(b.period == per) & (b.h == h)].iloc[0]
            rows.append({"Period": {"dev": "2006–18", "test": "2019–26"}[per], "Horizon": f"{h}d",
                         "Original (v1) [95% CI]": f"{x.reg_coef*100:+.2f} [{x.reg_lo*100:+.2f}, {x.reg_hi*100:+.2f}]",
                         "p (v1)": f"{x.reg_p:.3f}", "n (v1)": f"{int(x.n_treated):,}",
                         "Corrected (post-review) [95% CI]": f"{y.reg_coef*100:+.2f} [{y.reg_lo*100:+.2f}, {y.reg_hi*100:+.2f}]",
                         "p": f"{y.reg_p:.3f}", "n": f"{int(y.n_treated):,}"})
    return md(pd.DataFrame(rows), "Original and post-review corrected incremental estimates (regression-adjusted, pp). "
                                  "The corrected estimates are sensitivity analyses computed after the test results were seen.")


def table_audit():
    au = pd.read_csv(C.ROOT / "docs" / "audit" / "filing_audit_35.csv")
    lab = {"correct": "correct", "false_positive": "false positive (included, not discretionary open-market)",
           "probable_false_positive": "probable false positive", "false_negative": "false negative (excluded, eligible)",
           "flag_error": "correct inclusion, 10b5-1 flag missed"}
    t = au.groupby(["sample", "verdict"]).size().rename("filings").reset_index()
    t["verdict"] = t["verdict"].map(lab)
    t = t.rename(columns={"sample": "Audit sample", "verdict": "Verdict after reading the filing on EDGAR", "filings": "Filings"})
    t["Filings"] = t["Filings"].astype(str)
    return md(t, "Hand audit of all 35 randomly sampled filings (docs/audit/filing_audit_35.csv).")


def table_audit_full():
    au = pd.read_csv(C.ROOT / "docs" / "audit" / "filing_audit_35.csv")
    t = pd.DataFrame({"#": au["idx"].astype(str), "Sample": au["sample"],
                      "Accession": [f"[{a}]({u})" for a, u in zip(au["ACCESSION_NUMBER"], au["edgar_link"])],
                      "Issuer": au["ISSUERNAME"], "What the filing shows": au["edgar_finding"],
                      "Verdict": au["verdict"].str.replace("_", " ")})
    return md(t)


TABLES = {"audit_full": table_audit_full, "sample": table_sample, "events": table_events, "main": table_main, "balance": table_balance,
          "revision": table_revision, "audit": table_audit}


def fill(text: str) -> str:
    text = re.sub(r"\{\{table:(\w+)\}\}", lambda m: TABLES[m.group(1)](), text)
    text = re.sub(r"\{\{(\w+)\}\}", lambda m: N[m.group(1)], text)
    left = re.findall(r"\{\{[^}]*\}\}", text)
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")
    return text


def main():
    paper = fill((C.ROOT / "paper" / "paper_template.md").read_text())
    (C.ROOT / "paper" / "paper.md").write_text(paper)
    targets = {"README_template.md": "README.md", "DATA_AUDIT_template.md": "docs/DATA_AUDIT.md",
               "POST_REVIEW_CHANGES_template.md": "POST_REVIEW_CHANGES.md"}
    for name, dest in targets.items():
        f = C.ROOT / "docs" / name
        if f.exists():
            (C.ROOT / dest).write_text(fill(f.read_text()))
    cmd = ["pandoc", "paper.md", "-o", "paper.pdf", "--pdf-engine=xelatex", "--resource-path=.:..",
           "-V", "tables=true"]
    subprocess.run(cmd, cwd=C.ROOT / "paper", check=True)
    print("built paper/paper.pdf")


if __name__ == "__main__":
    main()
