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
| 2006–2018 | 20 days | {{v1_inc_dev_20_reg}} {{v1_inc_dev_20_reg_ci}}, p = {{v1_inc_dev_20_reg_p}} | {{v1_inc_dev_20_n}} | {{inc_dev_20_reg}} {{inc_dev_20_reg_ci}}, p = {{inc_dev_20_reg_p}} | {{inc_dev_20_n}} |
| 2006–2018 | 60 days | {{v1_inc_dev_60_reg}} {{v1_inc_dev_60_reg_ci}}, p = {{v1_inc_dev_60_reg_p}} | {{v1_inc_dev_60_n}} | {{inc_dev_60_reg}} {{inc_dev_60_reg_ci}}, p = {{inc_dev_60_reg_p}} | {{inc_dev_60_n}} |
| 2019–mid-2026 | 20 days | {{v1_inc_test_20_reg}} {{v1_inc_test_20_reg_ci}}, p = {{v1_inc_test_20_reg_p}} | {{v1_inc_test_20_n}} | {{inc_test_20_reg}} {{inc_test_20_reg_ci}}, p = {{inc_test_20_reg_p}} | {{inc_test_20_n}} |
| 2019–mid-2026 | 60 days | **{{v1_inc_test_60_reg}}** {{v1_inc_test_60_reg_ci}}, p = {{v1_inc_test_60_reg_p}} | {{v1_inc_test_60_n}} | **{{inc_test_60_reg}}** {{inc_test_60_reg_ci}}, p = {{inc_test_60_reg_p}} | {{inc_test_60_n}} |

Month-block bootstrap CI of the raw matched 60-day difference, test period: original {{v1_inc_test_60_boot_ci}}, corrected {{inc_test_60_boot_ci}}.

**The conclusion does not change.** The held-out estimate fails to detect a reliable incremental effect; it does not show that the effect is zero (corrected 95% interval {{inc_test_60_reg_ci}} pp over 60 days).

## 1. Price-data errors (the extreme `ret_21` values)

**What was wrong.** The test-period balance table reported a treated mean prior 21-day return of {{bal_v1_test_ret21_treated_mean}} (as a fraction, i.e. several hundred per cent) against {{bal_v1_test_ret21_control_mean}} for controls. One observation drove it: SQL Technologies (SKYX), second-buyer signal of 16 February 2022, `ret_21` = {{skyx_ret21}}. Tracing the raw Tiingo rows shows a dormant quote of {{skyx_before}} with zero volume on {{skyx_zero_days}} of the 10 trading days before the stock began trading at {{skyx_after}} on its Nasdaq listing (10 February 2022). No split or corporate action is recorded; the "return" is a placeholder price, not a trade. The same pattern, and others, affect a small number of rows.

**How it was traced.** `scripts/r01_price_quality.py` scans every series in the price file for one-day moves of 3× or more ({{pq_moves_total}} moves) and classifies each on data evidence — raw and adjusted close, split records within ±3 days, zero-volume days, missing days, and whether the move reverses within 3 days. `scripts/r02_quality_impact.py` traces each of the {{ex_rows}} reviewer-flagged rows (`ret_21` > 200% or `ret_126` > 1000%) to the largest move in its covariate window: `tables/post_review/extreme_obs_trace.csv`. All classified moves with raw observations: `tables/post_review/price_jumps_classified.csv`.

| Class (evidence) | Moves in price file | Treatment |
|---|---|---|
| stale placeholder: constant price, zero volume on ≥ 5 of prior 10 days | {{pq_moves_stale_placeholder}} | **fixed at source**: dormant quotes set to missing; no return may span the jump |
| data gap / splice: ≥ 20 missing trading days before the move (e.g. old and new equity after a bankruptcy) | {{pq_moves_data_gap_splice}} | **fixed at source**: no return may span it (most such gaps lie between the trimmed download windows and never enter a calculation) |
| reversing spike: move undone within 3 trading days | {{pq_moves_reversing_spike}} | **fixed at source**: spike days set to missing |
| implausible magnitude: ≥ 10× or ≤ −90% in one day, no split recorded, no other signature (often an unrecorded reverse split in a sub-$1 OTC stock) | {{pq_moves_implausible_magnitude}} | **price-quality rule**: cannot be resolved; treated as a break in *covariate* (pre-signal) windows only, so no event is excluded because of the size of its future return |
| 3×–10× moves with none of the above | {{pq_moves_plausible_move}} | kept as genuine (e.g. KaloBios, Nov 2015; Karuna, Nov 2019) |

The thresholds were set from the observed error patterns, before any corrected estimate was computed, and are not tuned: 3× defines what is inspected; 10× is the plausibility bound for an unexplained one-day move.

**What it removes** (original samples re-evaluated against the corrected prices; by year in `tables/post_review/quality_removed_summary.csv`):

| | 2006–2018 | 2019–mid-2026 |
|---|---|---|
| treated second-buyer signals | {{pq_dev_treated_signals_removed}} | {{pq_test_treated_signals_removed}} |
| control rows | {{pq_dev_control_rows_removed}} | {{pq_test_control_rows_removed}} |
| issuers affected in the matched sample | {{pq_dev_matched_issuers_affected}} | {{pq_test_matched_issuers_affected}} |
| event-study events (issuers) | {{pq_dev_event_study_events_removed}} ({{pq_dev_event_study_issuers_affected}}) | {{pq_test_event_study_events_removed}} ({{pq_test_event_study_issuers_affected}}) |

After removal the whole pipeline was rerun (matching picks replacement controls from the corrected pool). Effect on the primary 60-day estimate: {{delta_dev_60}} (development) and {{delta_test_60}} (test).

**Balance.** The original table showed a standardised difference of {{bal_v1_test_ret21_sd}} for `ret_21`, which looked reassuring only because the SKYX value inflated the standard deviation (treated/control variance ratio {{bal_v1_raw_ret21_vr}}). The matching and regression never used the raw value — they use variables clipped at development 1st/99th percentiles — and on those the original balance was fine (standardised difference {{bal_v1_used_ret21_sd}}, variance ratio {{bal_v1_used_ret21_vr}}; medians {{bal_v1_raw_ret21_med_t}} vs {{bal_v1_raw_ret21_med_c}}). The balance tables now report means, weighted medians, 10th/90th percentiles, variance ratios and the share of values clipped, on both raw and as-used variables (`tables/balance_detailed_*.csv`). Corrected test period, as used: largest |standardised difference| {{bald_test_max_sd}} ({{bald_test_max_sd_var}}; {{bald_test_max_sd_ex_rep}} excluding repeat purchases), variance ratios {{bald_test_vr_range}}.

## 2. Filing audit completed

All {{aud_n}} sampled filings ({{aud_n_included}} included, {{aud_n_excluded}} excluded, {{aud_n_footnote_screened}} footnote-screened) were read on EDGAR; findings and links are in `docs/audit/filing_audit_35.csv`. Previously eight had been read on EDGAR and one checked from dataset text; now all have been read.

| Verdict | Filings |
|---|---|
| correct | {{aud_correct}} |
| false positive — included but not a discretionary open-market purchase (Calamos: company-directed buying to "manage dilution"; Metropolitan Bank: IPO allocation at the $35.00 IPO price) | {{aud_false_positive}} |
| probable false positive (eNucleus: 2.5m shares at $0.28 plus warrants; fits a private placement, not stated) | {{aud_probable_false_positive}} |
| false negative — excluded but eligible (J.B. Hunt EVP recorded as "Other"; Macquarie "LLC interests") | {{aud_false_negative}} |
| flag error — correctly included but 10b5-1 plan not flagged (Broadway Financial) | {{aud_flag_error}} |

Among the {{aud_n_included}} randomly sampled *included* purchases, {{aud_false_positive}} are confirmed and {{aud_probable_false_positive}} probable false positives ({{aud_fp_rate_incl_probable}}; exact 95% CI {{aud_fp_rate_ci}}). The sample is too small to pin the rate down, but a material minority of retained P-code purchases may not be discretionary open-market buys.

**Could this change the conclusion?** A post-review stricter filter targets the patterns found: exclusion wording anywhere in the filing (not only on the purchase line), buyback / company-directed wording, and IPO-window purchases. It removes {{fc_anyofacstricterfilte}} disclosures ({{fc_anyofacstricterfilte_share}}); rule A is deliberately broad and also removes genuine purchases whose holding footnotes mention, say, an old dividend-reinvestment plan, so it over-excludes. The pre-specified filter is unchanged; results:

| | 60-day estimate, 2006–2018 | 60-day estimate, 2019–mid-2026 |
|---|---|---|
| pre-specified filter (corrected prices) | {{fe_primaryprespec_dev_60}} | {{fe_primaryprespec_test_60}} |
| stricter filter (post-review) | {{fe_stricterfilter_dev_60}} | {{fe_stricterfilter_test_60}} |
| excluding 10b5-1 plans, filing-wide flag (post-review) | {{fe_excluding10b51_dev_60}} | {{fe_excluding10b51_test_60}} |

The filing-wide 10b5-1 flag marks {{fc_revised10b51flagfili}} disclosures against {{fc_original10b51flag}} for the original line-level flag. The false-negative patterns are rare: {{fn_other_title_legs}} Form 4 purchase legs from owners who ticked "Other" but give an officer title, {{fn_llc_legs}} with "LLC interest" titles. Of the audited misclassified filings, {{aud_fp_in_matched}} entered the matched test and {{aud_fp_in_events}} the event study (`tables/post_review/audited_cases_in_samples.csv`).

## 3. Wording tightened

* The sample is described as **P-coded Form 4 purchases by officers and directors, screened for identifiable non-market transactions, with residual misclassification** — not "every open-market purchase".
* Survivorship: the report explains that only {{cov_2006}} of 2006 disclosures could be priced, that the missing firms are disproportionately ones that later failed, were acquired or had tickers reused, and that similar second-buyer *rates* among priced and unpriced episodes do **not** show the bias is harmless — they say nothing about how the missing firms' returns behaved.
* The held-out finding is stated as a failure to detect a reliable incremental effect, with the interval, not as evidence that the effect is zero.
* Balance is described from medians and as-used variables, not from a mean inflated by one erroneous value.

## 4. Code and verification

* `PRICE_QUALITY=v1|v2` (default v2). v1 runs the archived, frozen logic exactly (`archive/v1_frozen_code/` holds byte-identical copies of the frozen files; their hashes match `docs/FREEZE_before_test.txt`).
* New steps: `r01_price_quality.py`, `r02_quality_impact.py`, `r03_filter_sensitivity.py`; `s05` also writes `balance_detailed_*.csv`.
* `run_all.sh` regenerates both versions from the raw export; `s12_integrity.py` now also checks that the regenerated v1 outputs equal the preserved originals, and that every number in the README, paper, audit and this file appears in `output/numbers.json` (or is a listed design constant).
