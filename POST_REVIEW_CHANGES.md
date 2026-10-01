# Post-review changes

An independent review (30 September 2026) raised a price-data problem, an
incomplete filing audit and several claims that needed tighter wording. Every
change below was made **after the held-out test-period results had been seen**.
The revised estimates are therefore **post-review sensitivity analyses, not a
new untouched out-of-sample test**. The original outputs are preserved
unchanged in `output/original_v1/` and can be regenerated exactly with
`PRICE_QUALITY=v1` (the pipeline writes them to `output/v1_reproduced/`, and
`scripts/s12_integrity.py` checks they match).

## Headline: original and corrected estimates side by side

Regression-adjusted incremental return of a second-buyer signal over landmark-matched single-buyer episodes (winsorised SPY-adjusted return, percentage points, 95% CI clustered by issuer and month).

| Period | Horizon | Original (v1) | n | Corrected (v2, post-review) | n |
|---|---|---|---|---|---|
| 2006–2018 | 20 days | +0.52 pp [+0.19, +0.85], p = 0.002 | 8,886 | +0.52 pp [+0.19, +0.85], p = 0.002 | 8,879 |
| 2006–2018 | 60 days | +0.58 pp [+0.08, +1.08], p = 0.022 | 8,886 | +0.58 pp [+0.08, +1.08], p = 0.022 | 8,879 |
| 2019–mid-2026 | 20 days | +0.18 pp [-0.25, +0.61], p = 0.414 | 5,072 | +0.18 pp [-0.25, +0.60], p = 0.414 | 5,070 |
| 2019–mid-2026 | 60 days | **+0.35 pp** [-0.40, +1.10], p = 0.359 | 5,072 | **+0.36 pp** [-0.39, +1.11], p = 0.346 | 5,070 |

Month-block bootstrap CI of the raw matched 60-day difference, test period: original [-0.46, +1.23], corrected [-0.47, +1.24].

**The conclusion does not change.** The held-out estimate fails to detect a reliable incremental effect; it does not show that the effect is zero (corrected 95% interval [-0.39, +1.11] pp over 60 days).

## 1. Price-data errors (the extreme `ret_21` values)

**What was wrong.** The test-period balance table reported a treated mean prior 21-day return of 2.57 (as a fraction, i.e. several hundred per cent) against -0.04 for controls. One observation drove it: SQL Technologies (SKYX), second-buyer signal of 16 February 2022, `ret_21` = 13,269. Tracing the raw Tiingo rows shows a dormant quote of $0.001 with zero volume on 10 of the 10 trading days before the stock began trading at $11.85 on its Nasdaq listing (10 February 2022). No split or corporate action is recorded; the "return" is a placeholder price, not a trade. The same pattern, and others, affect a small number of rows.

**How it was traced.** `scripts/r01_price_quality.py` scans every series in the price file for one-day moves of 3× or more (4,203 moves) and classifies each on data evidence — raw and adjusted close, split records within ±3 days, zero-volume days, missing days, and whether the move reverses within 3 days. `scripts/r02_quality_impact.py` traces each of the 60 reviewer-flagged rows (`ret_21` > 200% or `ret_126` > 1000%) to the largest move in its covariate window: `tables/post_review/extreme_obs_trace.csv`. All classified moves with raw observations: `tables/post_review/price_jumps_classified.csv`.

| Class (evidence) | Moves in price file | Treatment |
|---|---|---|
| stale placeholder: constant price, zero volume on ≥ 5 of prior 10 days | 463 | **fixed at source**: dormant quotes set to missing; no return may span the jump |
| data gap / splice: ≥ 20 missing trading days before the move (e.g. old and new equity after a bankruptcy) | 894 | **fixed at source**: no return may span it (most such gaps lie between the trimmed download windows and never enter a calculation) |
| reversing spike: move undone within 3 trading days | 799 | **fixed at source**: spike days set to missing |
| implausible magnitude: ≥ 10× or ≤ −90% in one day, no split recorded, no other signature (often an unrecorded reverse split in a sub-$1 OTC stock) | 485 | **price-quality rule**: cannot be resolved; treated as a break in *covariate* (pre-signal) windows only, so no event is excluded because of the size of its future return |
| 3×–10× moves with none of the above | 1,562 | kept as genuine (e.g. KaloBios, Nov 2015; Karuna, Nov 2019) |

The thresholds were set from the observed error patterns, before any corrected estimate was computed, and are not tuned: 3× defines what is inspected; 10× is the plausibility bound for an unexplained one-day move.

**What it removes** (original samples re-evaluated against the corrected prices; by year in `tables/post_review/quality_removed_summary.csv`):

| | 2006–2018 | 2019–mid-2026 |
|---|---|---|
| treated second-buyer signals | 7 | 2 |
| control rows | 15 | 4 |
| issuers affected in the matched sample | 16 | 6 |
| event-study events (issuers) | 4 (4) | 1 (1) |

After removal the whole pipeline was rerun (matching picks replacement controls from the corrected pool). Effect on the primary 60-day estimate: -0.002 pp (development) and +0.009 pp (test).

**Balance.** The original table showed a standardised difference of 0.020 for `ret_21`, which looked reassuring only because the SKYX value inflated the standard deviation (treated/control variance ratio 606,376). The matching and regression never used the raw value — they use variables clipped at development 1st/99th percentiles — and on those the original balance was fine (standardised difference -0.008, variance ratio 1.14; medians -4.4% vs -3.9%). The balance tables now report means, weighted medians, 10th/90th percentiles, variance ratios and the share of values clipped, on both raw and as-used variables (`tables/balance_detailed_*.csv`). Corrected test period, as used: largest |standardised difference| 0.14 (n_repeats_asof; 0.08 excluding repeat purchases), variance ratios 0.97–1.54.

## 2. Filing audit completed

All 35 sampled filings (15 included, 15 excluded, 5 footnote-screened) were read on EDGAR; findings and links are in `docs/audit/filing_audit_35.csv`. Previously eight had been read on EDGAR and one checked from dataset text; now all have been read.

| Verdict | Filings |
|---|---|
| correct | 29 |
| false positive — included but not a discretionary open-market purchase (Calamos: company-directed buying to "manage dilution"; Metropolitan Bank: IPO allocation at the $35.00 IPO price) | 2 |
| probable false positive (eNucleus: 2.5m shares at $0.28 plus warrants; fits a private placement, not stated) | 1 |
| false negative — excluded but eligible (J.B. Hunt EVP recorded as "Other"; Macquarie "LLC interests") | 2 |
| flag error — correctly included but 10b5-1 plan not flagged (Broadway Financial) | 1 |

Among the 15 randomly sampled *included* purchases, 2 are confirmed and 1 probable false positives (20%; exact 95% CI 4–48%). The sample is too small to pin the rate down, but a material minority of retained P-code purchases may not be discretionary open-market buys.

**Could this change the conclusion?** A post-review stricter filter targets the patterns found: exclusion wording anywhere in the filing (not only on the purchase line), buyback / company-directed wording, and IPO-window purchases. It removes 19,281 disclosures (7.3%); rule A is deliberately broad and also removes genuine purchases whose holding footnotes mention, say, an old dividend-reinvestment plan, so it over-excludes. The pre-specified filter is unchanged; results:

| | 60-day estimate, 2006–2018 | 60-day estimate, 2019–mid-2026 |
|---|---|---|
| pre-specified filter (corrected prices) | +0.58 pp (95% CI [+0.08, +1.08], p = 0.022, n = 8,879) | +0.36 pp (95% CI [-0.39, +1.11], p = 0.346, n = 5,070) |
| stricter filter (post-review) | +0.57 pp (95% CI [+0.07, +1.06], p = 0.026, n = 8,391) | +0.52 pp (95% CI [-0.25, +1.28], p = 0.185, n = 4,791) |
| excluding 10b5-1 plans, filing-wide flag (post-review) | +0.62 pp (95% CI [+0.11, +1.13], p = 0.017, n = 8,739) | +0.37 pp (95% CI [-0.37, +1.12], p = 0.328, n = 4,982) |

The filing-wide 10b5-1 flag marks 11,616 disclosures against 11,541 for the original line-level flag. The false-negative patterns are rare: 1,977 Form 4 purchase legs from owners who ticked "Other" but give an officer title, 1,319 with "LLC interest" titles. Of the audited misclassified filings, 0 entered the matched test and 1 the event study (`tables/post_review/audited_cases_in_samples.csv`).

## 3. Wording tightened

* The sample is described as **P-coded Form 4 purchases by officers and directors, screened for identifiable non-market transactions, with residual misclassification** — not "every open-market purchase".
* Survivorship: the report explains that only 42.4% of 2006 disclosures could be priced, that the missing firms are disproportionately ones that later failed, were acquired or had tickers reused, and that similar second-buyer *rates* among priced and unpriced episodes do **not** show the bias is harmless — they say nothing about how the missing firms' returns behaved.
* The held-out finding is stated as a failure to detect a reliable incremental effect, with the interval, not as evidence that the effect is zero.
* Balance is described from medians and as-used variables, not from a mean inflated by one erroneous value.

## 4. Code and verification

* `PRICE_QUALITY=v1|v2` (default v2). v1 runs the archived, frozen logic exactly (`archive/v1_frozen_code/` holds byte-identical copies of the frozen files; their hashes match `docs/FREEZE_before_test.txt`).
* New steps: `r01_price_quality.py`, `r02_quality_impact.py`, `r03_filter_sensitivity.py`; `s05` also writes `balance_detailed_*.csv`.
* `run_all.sh` regenerates both versions from the raw export; `s12_integrity.py` now also checks that the regenerated v1 outputs equal the preserved originals, and that every number in the README, paper, audit and this file appears in `output/numbers.json` (or is a listed design constant).
