# Data audit

Every figure below is generated from `output/tables/` (see `scripts/s07_audit.py`
and `scripts/s10_numbers.py`). Links go to the SEC's EDGAR archive.

## 1. Sources

| Source | What | Access / date | Licence / constraint |
|---|---|---|---|
| [SEC Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) | Forms 3/4/5, {{sec_quarters}} quarterly zips 2006Q1–2026Q2 ([readme](https://www.sec.gov/files/insider_transactions_readme.pdf)) | downloaded 29–30 Sep 2026 by `scripts/download_data.py`; SHA-256 of each derived table in `data/raw/insider_data_export/manifest.json` | US government data, public; SEC fair-access rules (declared User-Agent, ≤10 requests/s) |
| SEC EDGAR submissions API (`data.sec.gov/submissions/CIK##########.json`) | issuer SIC, current tickers, former names, entity type | same run, {{edgar_issuers}} issuers | public |
| Tiingo end-of-day API | daily raw and adjusted OHLCV, dividends, split factors | same run; subscriber's Tiingo Power key | licensed to the subscriber: raw prices are **not** redistributed in this project |
| Tiingo `supported_tickers.zip` | listing / delisting dates for {{tiingo_usd}} USD stock tickers | same run | as above |

CRSP was not available. The workspace used for the analysis could not reach
sec.gov or Tiingo, so the download ran on the author's computer and the export
zip was uploaded; checksums were verified on arrival (all ten files matched).
One SEC quarter (2026Q2) was fetched during the setup test and reused from cache,
so it has no separate log line; its derived rows are included in the checksummed
tables.

## 2. Purchase filter (exact logic, in order)

Implemented in `scripts/s01_purchases.py`, parameters in `src/config.py`.

1. `DOCUMENT_TYPE == "4"` (original Form 4; 4/A, 5 and 3 excluded).
2. `TRANS_CODE == "P"` and `TRANS_ACQUIRED_DISP_CD == "A"`.
3. At least one reporting owner with relationship containing OFFICER or DIRECTOR ({{legs_not_od}} legs removed; mostly 10% owners and funds).
4. Security title matches `common|ordinary|class [a-c]|shares|stock` and not `preferred|pref|warrant|note(s)|debenture|unit(s)|right(s)|option|depositary|ads|bond|convertible|series x pref`.
5. `TRANS_SHARES > 0` and `TRANS_PRICEPERSHARE > 0`.
6. `EQUITY_SWAP_INVOLVED` and `NOT_SUBJECT_SEC16` not true.
7. Transaction date on or before filing date and at most 365 days earlier.
8. **Footnote screen** ({{legs_fn_screened}} legs removed) on footnotes referenced by transaction fields (`SECURITY_TITLE_FN`, `TRANS_DATE_FN`, `DEEMED_EXECUTION_DATE_FN`, `EQUITY_SWAP_TRANS_CD_FN`, `TRANS_TIMELINESS_FN`, `TRANS_SHARES_FN`, `TRANS_PRICEPERSHARE_FN`, `TRANS_ACQUIRED_DISP_CD_FN`) and the filing's REMARKS: private placement, privately negotiated, subscription agreement, (directly) from the issuer/company, registered direct, (underwritten / initial) public offering, IPO, directed share, rights offering, employee stock purchase / ESPP, dividend reinvestment / DRIP, 401(k), conversion of, in exchange for, exchange offer, pursuant to / in connection with the merger, merger consideration, spin-off. The largest categories were dividend reinvestment, employee stock purchase plans and directed-share/IPO allocations (counts by keyword in `output/tables/footnote_hits.csv`).
9. Registered / closed-end funds removed ({{legs_funds}} legs): EDGAR SIC 6722/6726, or blank EDGAR SIC plus a fund-style name. BDCs are kept.

Result: {{legs_eligible}} eligible legs → {{disclosures}} disclosures from {{ds_issuers}} issuers.

**Deviations from the written plan** (all made before any return was computed, logged with reasons in `docs/ANALYSIS_PLAN.md`): the fund rule (EDGAR has no SIC for funds), duplicate handling (identical lots within one filing are kept), and the footnote screen was narrowed to transaction footnotes after a hand review showed the original version was removing purchases whose *holdings* footnotes mentioned an old merger, a past gift, or a currency conversion.

## 3. Duplicates, amendments, joint filers

* Identical legs (same issuer, owner group, trade date, shares, price) in *different* accessions filed the same day are treated as duplicate filings: {{ds_duplicate_legs_removed}} legs dropped.
* Same-day accessions for one issuer whose owner sets overlap are merged into one disclosure ({{ds_multi_accession_disclosures}} disclosures span more than one accession).
* Joint filings (several reporting owners on one accession) are one buyer group ({{ds_joint_filer_disclosures}} disclosures). Buyers are distinct only if owner-CIK sets are disjoint.
* **Amendments.** Signals use the original Form 4 filing date only. {{ds_amendment_P_legs_checked}} eligible-looking P legs in 4/A filings were checked against original Form 4 rows (same issuer, owner group, trade date, shares within 1%); {{ds_amendment_only_legs}} have no matching original. Adding them at their amendment date is a robustness check (test-period estimate {{rb_test_adding4aonlypurchases4062amendmentdisclo}}).
* 10b5-1 plan purchases flagged: {{ds_plan_10b5_1_disclosures}} disclosures (footnotes referenced by the purchase line or remarks, or the `AFF10B5ONE` field from 2023). **Post-review:** the audit found a plan stated in a footnote attached to a holding line (Broadway Financial), which this flag misses; a filing-wide flag marks {{fc_revised10b51flagfili}} disclosures, and excluding them leaves the test estimate at {{fe_excluding10b51_test_60}}. Late filings (> 4 business days): {{ds_late_filed_disclosures}}.

## 4. Issuer-to-price matching

Candidates: the symbol on the Form 4 (OTC suffixes such as `.OB`/`.PK` stripped; `.`→`-`), then current EDGAR tickers. Check: reported price ÷ Tiingo *unadjusted* close on the trade date (or up to five trading days earlier).

| Outcome | Disclosures |
|---|---|
| matched (issuer median ratio 0.8–1.25, event ratio 0.67–1.5) | {{pm_matched}} |
| of which strict (event ratio 0.9–1.1) | {{pm_strictmatch0911}} |
| no Tiingo prices near the event (symbol absent or reused) | {{pm_notiingopricesneareventabsento}} |
| symbol has prices but no link passes the price check | {{pm_nolinkpassespricecheck}} |
| event price outside [0.67, 1.5] | {{pm_eventpriceoutside06715}} |
| no usable symbol on the filing or in EDGAR | {{pm_nousablesymbol}} |

A random sample of 300 failed matches is in `output/tables/failed_price_matches_sample.csv`; the year-by-year match rate is in `price_match_by_year.csv` (from {{cov_2006}} in 2006 to {{cov_2025}} in 2025). Ticker history cannot be resolved reliably with a ticker-keyed price source: Tiingo lists e.g. three different securities under `AAC` since 2014 and none for the 2006-era company, and {{tickers_ok_no_window}} symbols that returned Tiingo data had no prices inside the requested event windows.

## 5. Disclosure timing

The bulk data give `FILING_DATE` only. EDGAR assigns Forms 3/4/5 submitted up to 10 p.m. ET that day's date, so publication can follow the close. Primary entry is the close of the first trading day after the filing date; t+1 open, t+2 close and t+0 close (upper bound) are sensitivity checks. Filing lag (business days from trade to filing): median 1 in every year; {{lag_2bd_min}}–{{lag_2bd_max}} of disclosures per year within two business days (`filing_lag.csv`).

## 6. Corporate actions and price quality

Tiingo split- and dividend-adjusted closes are used for returns; unadjusted closes for the price-match check and dollar volume. {{split_events}} split records in the price file; {{split_share}} of event windows contain a split; {{unexplained_jumps}} jumps in the adjustment factor (adjClose/close) larger than 20% occur without a recorded split or dividend (at most {{unexplained_window_max}} of event windows contain one). Daily returns of ±100% or more are excluded from calendar-time portfolios.

**Post-review price-quality correction** (`scripts/r01_price_quality.py`, `r02_quality_impact.py`; full detail in `POST_REVIEW_CHANGES.md`). The original version relied on winsorisation for extreme prices. An independent review traced the extreme test-period balance value to SKYX, whose Tiingo series holds a {{skyx_before}} quote with zero volume on {{skyx_zero_days}} of the 10 days before it began trading at {{skyx_after}} (`ret_21` = {{skyx_ret21}}). Every one-day move of 3× or more in the price file ({{pq_moves_total}}) is now classified from raw evidence:

| Class | Moves | Treatment |
|---|---|---|
| stale placeholder (constant price, zero volume ≥ 5 of prior 10 days) | {{pq_moves_stale_placeholder}} | dormant quotes set to missing; no return spans the jump |
| data gap / splice (≥ 20 missing trading days) | {{pq_moves_data_gap_splice}} | no return spans it (most are gaps between trimmed download windows) |
| reversing spike (undone within 3 days) | {{pq_moves_reversing_spike}} | spike days set to missing |
| implausible magnitude (≥ 10× or ≤ −90%, no split, no other signature) | {{pq_moves_implausible_magnitude}} | break in pre-signal covariate windows only |
| 3×–10× without an error signature | {{pq_moves_plausible_move}} | kept |

Of the {{ex_rows}} matched rows in the original sample with `ret_21` > 200% or `ret_126` > 1000% (`tables/post_review/extreme_obs_trace.csv`), {{ex_gradualnosingledaymoveof}} reflect gradual moves with no single-day move of 3× or more and {{ex_plausiblemove}} a 3×–10× move without an error signature; the rest carry an error signature or break the plausibility rule. Rows removed: {{pq_treated_removed_total}} treated signals, {{pq_controls_removed_total}} control rows, {{pq_events_removed_total}} event-study events (by year: `quality_removed_summary.csv`). Unrecorded reverse splits smaller than 10× cannot be separated from genuine moves and remain.

## 7. Delisting and survivorship

* Tiingo includes delisted securities ({{tiingo_ended}} of USD stock tickers ended before 2026), but coverage of firms that disappeared before about 2010 is patchy: only {{cov_2006}} of 2006 disclosures can be priced, against {{cov_2025}} in 2025.
* The priced development-period sample is therefore tilted toward surviving firms. In-window delistings are rare: at most {{delist_max}} of events per type and period hit the end of their price series inside the 60-day window ({{incomplete_max}} incomplete) — implausibly low for small caps, and itself evidence that failing firms are under-represented.
* In the development period, {{mis_dev_priced}} of priced single-buyer episodes gained a second buyer versus {{mis_dev_unpriced}} of unpriced ones (n = {{mis_dev_priced_n}} and {{mis_dev_unpriced_n}}); in the test period {{mis_test_priced}} vs {{mis_test_unpriced}} (only {{mis_test_unpriced_n}} unpriced). Similar treatment *rates* do not show that survivorship bias is harmless: the returns of the unpriced firms are unobserved, and the incremental estimate would be biased if the second-buyer premium differed among firms that later disappeared.
* Delisting sensitivity (applies only to firms that are priced): an extra −30% at the last price gives a test estimate of {{rb_test_delistingextra30atlastprice}}; dropping incomplete windows gives {{rb_test_delistingcompletewindowsonly}}.

## 8. What cannot be determined reliably

* Whether a code-P purchase was on the open market: explicit private placements, offerings and plans are screened, but the audit (§9) shows IPO allocations, company-directed buying and probable private placements that no footnote identifies.
* Whose money: {{amb_indirect}} of eligible legs are held indirectly (trusts, spouses, IRAs, family entities); {{amb_buyback}} ({{amb_buyback_n}} legs) carry buyback-like footnotes such as purchases by a controlled company "primarily to manage dilution".
* Whether two CIKs are the same economic buyer (a person and an entity filing separately).
* Exact publication time; market capitalisation (not in the data; dollar volume is the size proxy).

## 9. Manual audit

A random sample (seed 20260930) of 15 included, 15 excluded and 5 footnote-screened legs was drawn before the review (`output/tables/audit_sample.csv`). The original report read eight of these on EDGAR and checked one against dataset footnote text. **Post-review, all {{aud_inspected}} original submissions were read on EDGAR** (30 September 2026); the full record, with links and notes, is `docs/audit/filing_audit_35.csv`.

{{table:audit_full}}

**Summary.** {{aud_correct}} of {{aud_n}} classifications are correct. Among the {{aud_n_included}} included purchases: {{aud_false_positive}} confirmed false positives (Calamos: company-directed buying "to manage dilution"; Metropolitan Bank: IPO allocation at the $35.00 IPO price, 8 November 2017 — IPO completed 10 November 2017), {{aud_probable_false_positive}} probable false positive (eNucleus: likely private placement, below the $1 floor), and {{aud_flag_error}} missed 10b5-1 flag (Broadway Financial). Among excluded filings: {{aud_false_negative}} false negatives (an EVP whose filing ticks "Other"; "LLC interests" that are the issuer's listed equity). All 5 footnote-screened filings were correctly screened.

The confirmed-plus-probable false-positive share among included purchases is {{aud_fp_rate_incl_probable}} (exact 95% CI {{aud_fp_rate_ci}}; confirmed only: {{aud_fp_rate_confirmed}}, CI {{aud_fp_rate_confirmed_ci}}). With 15 draws the rate is imprecise, but misclassification is clearly not negligible. The two false-negative patterns are rare in the full data ({{fn_other_title_legs}} and {{fn_llc_legs}} Form 4 purchase legs). The pre-specified filter is unchanged; a post-review stricter filter (exclusion or buyback wording anywhere in the filing, IPO-window purchases) removes {{fc_anyofacstricterfilte}} disclosures and gives a test-period estimate of {{fe_stricterfilter_test_60}} (`tables/post_review/filter_sensitivity_estimates.csv`).
