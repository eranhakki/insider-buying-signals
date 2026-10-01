# Does a second insider add information?

An incremental-information study of Form 4 insider purchase clusters, 2006–2026, **revised after an independent review**.
Paper: [`paper/paper.pdf`](paper/paper.pdf). What changed and why: [`POST_REVIEW_CHANGES.md`](POST_REVIEW_CHANGES.md). Data audit: [`docs/DATA_AUDIT.md`](docs/DATA_AUDIT.md). Analysis plan and pre-results deviations: [`docs/ANALYSIS_PLAN.md`](docs/ANALYSIS_PLAN.md).

## Question

When a second, distinct officer or director buys shares within 30 days of a first disclosed insider purchase, does the stock's later return differ from that of a comparable company where only one insider has bought *so far*? Only information public at each disclosure date is used.

## Result

**The held-out test fails to detect a reliable incremental effect. It does not show that the effect is zero.**

| 60-day incremental return, regression-adjusted | Development 2006–2018 | Held-out test 2019–mid-2026 |
|---|---|---|
| Original (pre-review) | +0.58 pp, 95% CI [+0.08, +1.08] pp, p = 0.022, n = 8,886 | **+0.35 pp**, 95% CI [-0.40, +1.10] pp, p = 0.359, n = 5,072 |
| Corrected price data (post-review sensitivity) | +0.58 pp, 95% CI [+0.08, +1.08] pp, p = 0.022, n = 8,879 | **+0.36 pp**, 95% CI [-0.39, +1.11] pp, p = 0.346, n = 5,070 |
| Corrected, 20-day | +0.52 pp, p = 0.002 | +0.18 pp, p = 0.414 |

The corrected numbers were computed after the held-out results had been seen, so they are sensitivity analyses, not a new out-of-sample test.

* The development-period premium was concentrated in illiquid stocks: in stocks priced ≥ $5 with ≥ $1m median daily dollar volume it is +0.31 pp (p = 0.357, n = 3,815) in development and -0.17 pp (p = 0.641, n = 2,532) in the test period.
* In the test period 2 of 29 pre-listed robustness variants reach p < 0.05: entry at the filing-day close (an upper bound that can precede publication) and one role subgroup among about thirty.
* Adding the second-buyer flag to an out-of-sample return model changes test-period R² by +0.00008.
* The base effect also weakened: the calendar-time alpha against SPY of first-buy signals is +8.2% a year in development and -2.2% in the test period.

## Post-review revision in brief

* **Price errors fixed.** A dormant $0.001 quote before SKYX's Nasdaq listing produced a prior return of 13,269 and dominated the balance table. All 4,203 one-day moves of 3× or more in the price file were classified on data evidence; stale quotes, spikes and spliced histories are fixed at source, and unexplained moves of 10× or more are treated as breaks in pre-signal windows only. 9 treated signals and 19 control rows of the original samples are affected; the full pipeline was rerun. The estimate barely moves because matching and regression always used clipped variables.
* **Filing audit completed.** All 35 sampled filings were read on EDGAR. Of 15 included purchases, 2 were not discretionary open-market buys (an IPO allocation; company-directed buying) and 1 was probably a private placement; 2 eligible purchases were wrongly excluded; one 10b5-1 plan was not flagged. A stricter post-review filter gives a test-period estimate of +0.52 pp (95% CI [-0.25, +1.28], p = 0.185, n = 4,791).
* **Claims tightened.** The sample is *P-coded Form 4 purchases screened for identifiable non-market transactions*, not "every open-market purchase"; survivorship is described as a real limit on the historical comparison.

**Most important limitation: survivorship.** The price source is keyed by ticker, so only 42.4% of 2006 disclosures can be priced (rising to 95.4% by 2025). Firms that later failed, were acquired or had tickers reused are under-represented, most of all in the development period where the only significant estimate was found. Similar second-buyer rates among priced and unpriced episodes (27.3% vs 26.6%) show only that the treatment occurs at a similar rate; they do not show the bias is harmless.

## Data

| Source | Use |
|---|---|
| [SEC Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets), 2006Q1–2026Q2 | Form 4 purchases, reporting owners (CIK), footnotes, amendments |
| SEC EDGAR submissions API | SIC codes, current tickers |
| Tiingo EOD (subscription) | raw and adjusted daily prices; SPY, IWM, sector ETFs; listing/delisting dates |

Sample: 862,147 P-code rows → 502,689 screened eligible legs → 265,512 disclosures (10,879 issuers) → 192,222 priced → 91,704 first-buy episodes → 20,536 single-buyer episodes with a second buyer. Full table: `output/tables/sample_construction.csv`.

## Reproduce

Requires Python ≥ 3.11 and a Tiingo API key.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. download (on a machine that can reach sec.gov and api.tiingo.com; ~1–3 h, resumable)
export TIINGO_API_KEY=...            # never written to any output
export SEC_CONTACT="Your Name you@example.com"
python scripts/download_data.py      # -> insider_data_export.zip
unzip insider_data_export.zip -d data/raw/

# 2. analysis: original (v1) and corrected (v2) pipelines, documents, integrity checks
bash run_all.sh
```

`run_all.sh` first reruns the original pipeline with `PRICE_QUALITY=v1` (outputs in `output/v1_reproduced/`, checked against the preserved originals in `output/original_v1/`), then the corrected pipeline: `s01` filters → `r01` price-quality classification → `s02`–`s08` → `r02` impact of the price rule → `r03` post-review filter sensitivity → `s09` figures → `s10` numbers → `s11` documents → `s13` export → `s12` integrity.

## Integrity

`output/integrity_report.md`: automated checks, all passing — data checksums, plan and freeze hashes, archived frozen code, v1 reproduction equal to the preserved originals, independent re-derivation of the headline estimates, and a scan confirming every number in the README, paper, audit and `POST_REVIEW_CHANGES.md` traces to `output/numbers.json` or a listed design constant. `docs/REPRODUCTION_LOG.md` records the clean-environment reruns and what could not be verified.

## Layout

```
scripts/      download_data.py; s01–s13 pipeline; r01–r03 post-review steps
src/          config (PRICE_QUALITY switch, frozen parameters), prices, matching, statistics, plotting
archive/      v1_frozen_code: exact copies of the code frozen before the test period
docs/         ANALYSIS_PLAN.md, FREEZE_before_test.txt, DATA_AUDIT.md, audit/filing_audit_35.csv, REPRODUCTION_LOG.md
output/       tables/ (incl. post_review/), figures/, results/, numbers.json, integrity_report.md,
              original_v1/ (preserved originals), v1_reproduced/ (regenerated originals)
paper/        paper.pdf and its template
```

## Limitations in brief

Survivorship in the price source (above); residual misclassification of code-P purchases (private, IPO and company-directed purchases that are not footnoted); indirect holdings (≈31% of eligible legs) and related entities with different CIKs; unrecorded reverse splits below 10× cannot be separated from genuine moves; no market capitalisation (dollar volume is the size proxy); filing date but not publication time; the development effect sits in illiquid stocks; results are associations, not causal effects; post-review corrections were made after seeing the test results.
