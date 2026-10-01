# Data audit

Every figure below is generated from `output/tables/` (see `scripts/s07_audit.py`
and `scripts/s10_numbers.py`). Links go to the SEC's EDGAR archive.

## 1. Sources

| Source | What | Access / date | Licence / constraint |
|---|---|---|---|
| [SEC Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) | Forms 3/4/5, 82 quarterly zips 2006Q1–2026Q2 ([readme](https://www.sec.gov/files/insider_transactions_readme.pdf)) | downloaded 29–30 Sep 2026 by `scripts/download_data.py`; SHA-256 of each derived table in `data/raw/insider_data_export/manifest.json` | US government data, public; SEC fair-access rules (declared User-Agent, ≤10 requests/s) |
| SEC EDGAR submissions API (`data.sec.gov/submissions/CIK##########.json`) | issuer SIC, current tickers, former names, entity type | same run, 12,959 issuers | public |
| Tiingo end-of-day API | daily raw and adjusted OHLCV, dividends, split factors | same run; subscriber's Tiingo Power key | licensed to the subscriber: raw prices are **not** redistributed in this project |
| Tiingo `supported_tickers.zip` | listing / delisting dates for 42,784 USD stock tickers | same run | as above |

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
3. At least one reporting owner with relationship containing OFFICER or DIRECTOR (225,386 legs removed; mostly 10% owners and funds).
4. Security title matches `common|ordinary|class [a-c]|shares|stock` and not `preferred|pref|warrant|note(s)|debenture|unit(s)|right(s)|option|depositary|ads|bond|convertible|series x pref`.
5. `TRANS_SHARES > 0` and `TRANS_PRICEPERSHARE > 0`.
6. `EQUITY_SWAP_INVOLVED` and `NOT_SUBJECT_SEC16` not true.
7. Transaction date on or before filing date and at most 365 days earlier.
8. **Footnote screen** (17,403 legs removed) on footnotes referenced by transaction fields (`SECURITY_TITLE_FN`, `TRANS_DATE_FN`, `DEEMED_EXECUTION_DATE_FN`, `EQUITY_SWAP_TRANS_CD_FN`, `TRANS_TIMELINESS_FN`, `TRANS_SHARES_FN`, `TRANS_PRICEPERSHARE_FN`, `TRANS_ACQUIRED_DISP_CD_FN`) and the filing's REMARKS: private placement, privately negotiated, subscription agreement, (directly) from the issuer/company, registered direct, (underwritten / initial) public offering, IPO, directed share, rights offering, employee stock purchase / ESPP, dividend reinvestment / DRIP, 401(k), conversion of, in exchange for, exchange offer, pursuant to / in connection with the merger, merger consideration, spin-off. The largest categories were dividend reinvestment, employee stock purchase plans and directed-share/IPO allocations (counts by keyword in `output/tables/footnote_hits.csv`).
9. Registered / closed-end funds removed (24,489 legs): EDGAR SIC 6722/6726, or blank EDGAR SIC plus a fund-style name. BDCs are kept.

Result: 502,689 eligible legs → 265,512 disclosures from 10,879 issuers.

**Deviations from the written plan** (all made before any return was computed, logged with reasons in `docs/ANALYSIS_PLAN.md`): the fund rule (EDGAR has no SIC for funds), duplicate handling (identical lots within one filing are kept), and the footnote screen was narrowed to transaction footnotes after a hand review showed the original version was removing purchases whose *holdings* footnotes mentioned an old merger, a past gift, or a currency conversion.

## 3. Duplicates, amendments, joint filers

* Identical legs (same issuer, owner group, trade date, shares, price) in *different* accessions filed the same day are treated as duplicate filings: 2,294 legs dropped.
* Same-day accessions for one issuer whose owner sets overlap are merged into one disclosure (3,221 disclosures span more than one accession).
* Joint filings (several reporting owners on one accession) are one buyer group (9,560 disclosures). Buyers are distinct only if owner-CIK sets are disjoint.
* **Amendments.** Signals use the original Form 4 filing date only. 16,955 eligible-looking P legs in 4/A filings were checked against original Form 4 rows (same issuer, owner group, trade date, shares within 1%); 7,515 have no matching original. Adding them at their amendment date is a robustness check (test-period estimate +0.35 pp (p = 0.369, n = 5,085)).
* 10b5-1 plan purchases flagged: 11,541 disclosures (footnotes referenced by the purchase line or remarks, or the `AFF10B5ONE` field from 2023). **Post-review:** the audit found a plan stated in a footnote attached to a holding line (Broadway Financial), which this flag misses; a filing-wide flag marks 11,616 disclosures, and excluding them leaves the test estimate at +0.37 pp (95% CI [-0.37, +1.12], p = 0.328, n = 4,982). Late filings (> 4 business days): 14,428.

## 4. Issuer-to-price matching

Candidates: the symbol on the Form 4 (OTC suffixes such as `.OB`/`.PK` stripped; `.`→`-`), then current EDGAR tickers. Check: reported price ÷ Tiingo *unadjusted* close on the trade date (or up to five trading days earlier).

| Outcome | Disclosures |
|---|---|
| matched (issuer median ratio 0.8–1.25, event ratio 0.67–1.5) | 192,222 (72.4%) |
| of which strict (event ratio 0.9–1.1) | 182,141 (68.6%) |
| no Tiingo prices near the event (symbol absent or reused) | 46,467 (17.5%) |
| symbol has prices but no link passes the price check | 20,443 (7.7%) |
| event price outside [0.67, 1.5] | 2,088 (0.8%) |
| no usable symbol on the filing or in EDGAR | 4,292 (1.6%) |

A random sample of 300 failed matches is in `output/tables/failed_price_matches_sample.csv`; the year-by-year match rate is in `price_match_by_year.csv` (from 42.4% in 2006 to 95.4% in 2025). Ticker history cannot be resolved reliably with a ticker-keyed price source: Tiingo lists e.g. three different securities under `AAC` since 2014 and none for the 2006-era company, and 2,974 symbols that returned Tiingo data had no prices inside the requested event windows.

## 5. Disclosure timing

The bulk data give `FILING_DATE` only. EDGAR assigns Forms 3/4/5 submitted up to 10 p.m. ET that day's date, so publication can follow the close. Primary entry is the close of the first trading day after the filing date; t+1 open, t+2 close and t+0 close (upper bound) are sensitivity checks. Filing lag (business days from trade to filing): median 1 in every year; 84%–92% of disclosures per year within two business days (`filing_lag.csv`).

## 6. Corporate actions and price quality

Tiingo split- and dividend-adjusted closes are used for returns; unadjusted closes for the price-match check and dollar volume. 2,665 split records in the price file; 0.8–1.0% of event windows contain a split; 892 jumps in the adjustment factor (adjClose/close) larger than 20% occur without a recorded split or dividend (at most 0.02% of event windows contain one). Daily returns of ±100% or more are excluded from calendar-time portfolios.

**Post-review price-quality correction** (`scripts/r01_price_quality.py`, `r02_quality_impact.py`; full detail in `POST_REVIEW_CHANGES.md`). The original version relied on winsorisation for extreme prices. An independent review traced the extreme test-period balance value to SKYX, whose Tiingo series holds a $0.001 quote with zero volume on 10 of the 10 days before it began trading at $11.85 (`ret_21` = 13,269). Every one-day move of 3× or more in the price file (4,203) is now classified from raw evidence:

| Class | Moves | Treatment |
|---|---|---|
| stale placeholder (constant price, zero volume ≥ 5 of prior 10 days) | 463 | dormant quotes set to missing; no return spans the jump |
| data gap / splice (≥ 20 missing trading days) | 894 | no return spans it (most are gaps between trimmed download windows) |
| reversing spike (undone within 3 days) | 799 | spike days set to missing |
| implausible magnitude (≥ 10× or ≤ −90%, no split, no other signature) | 485 | break in pre-signal covariate windows only |
| 3×–10× without an error signature | 1,562 | kept |

Of the 60 matched rows in the original sample with `ret_21` > 200% or `ret_126` > 1000% (`tables/post_review/extreme_obs_trace.csv`), 44 reflect gradual moves with no single-day move of 3× or more and 6 a 3×–10× move without an error signature; the rest carry an error signature or break the plausibility rule. Rows removed: 9 treated signals, 19 control rows, 5 event-study events (by year: `quality_removed_summary.csv`). Unrecorded reverse splits smaller than 10× cannot be separated from genuine moves and remain.

## 7. Delisting and survivorship

* Tiingo includes delisted securities (38% of USD stock tickers ended before 2026), but coverage of firms that disappeared before about 2010 is patchy: only 42.4% of 2006 disclosures can be priced, against 95.4% in 2025.
* The priced development-period sample is therefore tilted toward surviving firms. In-window delistings are rare: at most 0.25% of events per type and period hit the end of their price series inside the 60-day window (0.27% incomplete) — implausibly low for small caps, and itself evidence that failing firms are under-represented.
* In the development period, 27.3% of priced single-buyer episodes gained a second buyer versus 26.6% of unpriced ones (n = 35,149 and 18,417); in the test period 26.8% vs 22.6% (only 1,942 unpriced). Similar treatment *rates* do not show that survivorship bias is harmless: the returns of the unpriced firms are unobserved, and the incremental estimate would be biased if the second-buyer premium differed among firms that later disappeared.
* Delisting sensitivity (applies only to firms that are priced): an extra −30% at the last price gives a test estimate of +0.37 pp (p = 0.334, n = 5,070); dropping incomplete windows gives +0.38 pp (p = 0.320, n = 5,063).

## 8. What cannot be determined reliably

* Whether a code-P purchase was on the open market: explicit private placements, offerings and plans are screened, but the audit (§9) shows IPO allocations, company-directed buying and probable private placements that no footnote identifies.
* Whose money: 31% of eligible legs are held indirectly (trusts, spouses, IRAs, family entities); 0.6% (3,200 legs) carry buyback-like footnotes such as purchases by a controlled company "primarily to manage dilution".
* Whether two CIKs are the same economic buyer (a person and an entity filing separately).
* Exact publication time; market capitalisation (not in the data; dollar volume is the size proxy).

## 9. Manual audit

A random sample (seed 20260930) of 15 included, 15 excluded and 5 footnote-screened legs was drawn before the review (`output/tables/audit_sample.csv`). The original report read eight of these on EDGAR and checked one against dataset footnote text. **Post-review, all 35 original submissions were read on EDGAR** (30 September 2026); the full record, with links and notes, is `docs/audit/filing_audit_35.csv`.

| #   | Sample            | Accession                                                                                                                 | Issuer                                 | What the filing shows                                                                                                                                    | Verdict                 |
|:----|:------------------|:--------------------------------------------------------------------------------------------------------------------------|:---------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------|:------------------------|
| 0   | included          | [0001181431-06-054820](https://www.sec.gov/Archives/edgar/data/29806/000118143106054820/0001181431-06-054820-index.htm)   | CONSTAR INTERNATIONAL INC              | Director; 7 lots, 827 shares, P, direct; footnote 'Purchases made pursuant to 10b5-1 plan'                                                               | correct                 |
| 1   | included          | [0001209191-14-066312](https://www.sec.gov/Archives/edgar/data/1007330/000120919114066312/0001209191-14-066312-index.htm) | PRGX GLOBAL, INC.                      | Director; P 4,361 @ $5.2695 (31 Oct 2014) and 15,639 @ $5.2192 (3 Nov); weighted-average footnotes                                                       | correct                 |
| 2   | included          | [0001415889-22-001573](https://www.sec.gov/Archives/edgar/data/31462/000141588922001573/0001415889-22-001573-index.htm)   | ECOLAB INC.                            | Director; P 5,000 @ $179.391; weighted-average footnote                                                                                                  | correct                 |
| 3   | included          | [0001209191-07-060583](https://www.sec.gov/Archives/edgar/data/1359841/000120919107060583/0001209191-07-060583-index.htm) | Hanesbrands Inc.                       | Director; 14 lots P on 29 Oct 2007 @ $29.23-29.37, all held by spouse (disclaimed)                                                                       | correct                 |
| 4   | included          | [0001534122-18-000032](https://www.sec.gov/Archives/edgar/data/1108630/000153412218000032/0001534122-18-000032-index.htm) | Live Current Media Inc.                | Director; P 1,000 and 1,500 @ $0.06, direct; no footnotes                                                                                                | correct                 |
| 5   | included          | [0001221432-16-000123](https://www.sec.gov/Archives/edgar/data/1299033/000122143216000123/0001221432-16-000123-index.htm) | Calamos Asset Management, Inc. /DE/    | Chairman/CEO + family entity; 30 purchases by Calamos Investments LLC 'primarily to manage dilution'                                                     | false positive          |
| 6   | included          | [0001181431-08-059610](https://www.sec.gov/Archives/edgar/data/1001171/000118143108059610/0001181431-08-059610-index.htm) | BROADWAY FINANCIAL CORP \DE\           | Director (also 'employed by a 9% owner'); P 100 @ $5.2495 via Williams Group Holdings LLC; F2: 'effected pursuant to a Rule 10b5-1 trading plan'         | flag error              |
| 7   | included          | [0001209191-13-009488](https://www.sec.gov/Archives/edgar/data/944809/000120919113009488/0001209191-13-009488-index.htm)  | Opko Health, Inc.                      | CEO & Chairman (+ trust); 6 purchases, 57,500 sh @ $6.71-6.76, indirect via Frost Gamma Investments Trust                                                | correct                 |
| 8   | included          | [0001132651-08-000009](https://www.sec.gov/Archives/edgar/data/1132651/000113265108000009/0001132651-08-000009-index.htm) | AMES NATIONAL CORP                     | Director; P 450 @ $20.64 and 250 @ $19.90 via revocable family trust                                                                                     | correct                 |
| 9   | included          | [0001225208-17-013429](https://www.sec.gov/Archives/edgar/data/1282266/000122520817013429/0001225208-17-013429-index.htm) | WINDSTREAM HOLDINGS, INC.              | Director; P 1,000 @ $2.10 and 1,000 @ $2.00, direct                                                                                                      | correct                 |
| 10  | included          | [0001144204-06-001466](https://www.sec.gov/Archives/edgar/data/761034/000114420406001466/0001144204-06-001466-index.htm)  | ENUCLEUS INC                           | Director and 10% owner; P 2,505,000 @ $0.28; warrants (3.5m) bought 4 days later; no footnote on the nature of the purchase; filed 17 business days late | probable false positive |
| 11  | included          | [0001209191-14-043700](https://www.sec.gov/Archives/edgar/data/944809/000120919114043700/0001209191-14-043700-index.htm)  | Opko Health, Inc.                      | CEO & Chairman (+ trust); 30 purchases, 62,103 sh @ $8.54-8.74, indirect via trust                                                                       | correct                 |
| 12  | included          | [0001388296-08-000032](https://www.sec.gov/Archives/edgar/data/1099918/000138829608000032/0001388296-08-000032-index.htm) | Henry Bros. Electronics, Inc.          | Director and 10% owner; 29 lots P on 2 Sep 2008 @ $6.60-7.03, direct                                                                                     | correct                 |
| 13  | included          | [0001140361-17-041816](https://www.sec.gov/Archives/edgar/data/1476034/000114036117041816/0001140361-17-041816-index.htm) | Metropolitan Bank Holding Corp.        | Director; P 5,000 (direct) + 1,000 (spouse) @ exactly $35.00 on 8 Nov 2017                                                                               | false positive          |
| 14  | included          | [0001388038-07-000022](https://www.sec.gov/Archives/edgar/data/1011570/000138803807000022/0001388038-07-000022-index.htm) | KNOLL INC                              | Director; 12 lots P on 28 Feb 2007 @ $22.98-23.19, direct                                                                                                | correct                 |
| 15  | excluded          | [0001199037-07-000018](https://www.sec.gov/Archives/edgar/data/1094348/000119903707000018/0001199037-07-000018-index.htm) | ELOYALTY CORP                          | 10% owner only (Sutter Hill partner)                                                                                                                     | correct                 |
| 16  | excluded          | [0001140361-15-043644](https://www.sec.gov/Archives/edgar/data/1490286/000114036115043644/0001140361-15-043644-index.htm) | TORTOISE MLP FUND, INC.                | Registered closed-end fund (Tortoise MLP Fund); director purchase                                                                                        | correct                 |
| 17  | excluded          | [0001044321-07-000033](https://www.sec.gov/Archives/edgar/data/1069308/000104432107000033/0001044321-07-000033-index.htm) | Opexa Therapeutics, Inc.               | Joint filers, 10% owners only (Special Situations funds)                                                                                                 | correct                 |
| 18  | excluded          | [0001127602-09-016104](https://www.sec.gov/Archives/edgar/data/728535/000112760209016104/0001127602-09-016104-index.htm)  | HUNT J B TRANSPORT SERVICES INC        | EVP and Chief Operations Officer, but the filer ticked 'Other' (not 'Officer'); P 5,109 @ $27.40                                                         | false negative          |
| 19  | excluded          | [0000950142-07-002024](https://www.sec.gov/Archives/edgar/data/1072342/000095014207002024/0000950142-07-002024-index.htm) | DELPHI CORP                            | Merrill Lynch entities, 10% owners; broker error-correction trades                                                                                       | correct                 |
| 20  | excluded          | [0001181431-12-057696](https://www.sec.gov/Archives/edgar/data/1418819/000118143112057696/0001181431-12-057696-index.htm) | Iridium Communications Inc.            | Baralonco Ltd and its owner, 10% owners                                                                                                                  | correct                 |
| 21  | excluded          | [0001209191-07-069995](https://www.sec.gov/Archives/edgar/data/949536/000120919107069995/0001209191-07-069995-index.htm)  | HEARST ARGYLE TELEVISION INC           | Hearst entities, 10% owners                                                                                                                              | correct                 |
| 22  | excluded          | [0001078782-09-000157](https://www.sec.gov/Archives/edgar/data/64472/000107878209000157/0001078782-09-000157-index.htm)   | GENCOR INDUSTRIES INC                  | Houtkins, 10% owners; 2006 trades reported in 2009 after death                                                                                           | correct                 |
| 23  | excluded          | [0001140361-10-023208](https://www.sec.gov/Archives/edgar/data/1278384/000114036110023208/0001140361-10-023208-index.htm) | NTS REALTY HOLDINGS LP                 | Director and 10% owner; 'Limited Partnership Units' bought by family trusts/entity under 10b5-1 plans                                                    | correct                 |
| 24  | excluded          | [0000947871-07-000971](https://www.sec.gov/Archives/edgar/data/1289790/000094787107000971/0000947871-07-000971-index.htm) | Macquarie Infrastructure CO LLC        | Director; 30 purchases of 'Limited Liability Company Interest' @ $40.99-41.09                                                                            | false negative          |
| 25  | excluded          | [0001225208-09-006713](https://www.sec.gov/Archives/edgar/data/51548/000122520809006713/0001225208-09-006713-index.htm)   | INTERNATIONAL SPEEDWAY CORP            | Carl Two LP, 10% owner / France family group member                                                                                                      | correct                 |
| 26  | excluded          | [0001209191-22-010575](https://www.sec.gov/Archives/edgar/data/1504776/000120919122010575/0001209191-22-010575-index.htm) | Warby Parker Inc.                      | Durable Capital Partners, 10% owner                                                                                                                      | correct                 |
| 27  | excluded          | [0000919574-11-003894](https://www.sec.gov/Archives/edgar/data/1170593/000091957411003894/0000919574-11-003894-index.htm) | PRIMUS GUARANTY LTD                    | Second Curve Capital and Thomas Brown, 10% owners                                                                                                        | correct                 |
| 28  | excluded          | [0000892712-07-000779](https://www.sec.gov/Archives/edgar/data/1043961/000089271207000779/0000892712-07-000779-index.htm) | TRANSGENOMIC INC                       | LeRoy Kopp, 10% owner; 2001-2004 trades reported in 2007                                                                                                 | correct                 |
| 29  | excluded          | [0001362118-07-000087](https://www.sec.gov/Archives/edgar/data/1370291/000136211807000087/0001362118-07-000087-index.htm) | First California Financial Group, Inc. | Robert Pohlad, 10% owner; purchases under three share-purchase agreements                                                                                | correct                 |
| 30  | footnote-screened | [0001209191-13-049603](https://www.sec.gov/Archives/edgar/data/1396440/000120919113049603/0001209191-13-049603-index.htm) | Main Street Capital CORP               | Director; 3 fractional DRIP purchases @ $30.25; 'dividend reinvestment plan ... Rule 16a-11'                                                             | correct                 |
| 31  | footnote-screened | [0001209191-15-058126](https://www.sec.gov/Archives/edgar/data/1373670/000120919115058126/0001209191-15-058126-index.htm) | Green Brick Partners, Inc.             | Greenlight/Einhorn entities (director and 10% owner); 3.57m @ $10 'in an underwritten public offering'                                                   | correct                 |
| 32  | footnote-screened | [0001569187-25-000055](https://www.sec.gov/Archives/edgar/data/1569187/000156918725000055/0001569187-25-000055-index.htm) | Armada Hoffler Properties, Inc.        | Director; 954.154 sh @ $7.236; 'broker-sponsored dividend reinvestment program'                                                                          | correct                 |
| 33  | footnote-screened | [0001209191-19-053778](https://www.sec.gov/Archives/edgar/data/80035/000120919119053778/0001209191-19-053778-index.htm)   | PREFORMED LINE PRODUCTS CO             | Director; 17 sh @ $54.40; 'automatic dividend reinvestment'                                                                                              | correct                 |
| 34  | footnote-screened | [0001181431-11-010659](https://www.sec.gov/Archives/edgar/data/1047170/000118143111010659/0001181431-11-010659-index.htm) | EASTERN VIRGINIA BANKSHARES INC        | Director; 64.1026 sh @ $4.68; 'optional cash payments under the Dividend Reinvestment and Stock Purchase Plan'                                           | correct                 |

**Summary.** 29 of 35 classifications are correct. Among the 15 included purchases: 2 confirmed false positives (Calamos: company-directed buying "to manage dilution"; Metropolitan Bank: IPO allocation at the $35.00 IPO price, 8 November 2017 — IPO completed 10 November 2017), 1 probable false positive (eNucleus: likely private placement, below the $1 floor), and 1 missed 10b5-1 flag (Broadway Financial). Among excluded filings: 2 false negatives (an EVP whose filing ticks "Other"; "LLC interests" that are the issuer's listed equity). All 5 footnote-screened filings were correctly screened.

The confirmed-plus-probable false-positive share among included purchases is 20% (exact 95% CI 4–48%; confirmed only: 13%, CI 2–40%). With 15 draws the rate is imprecise, but misclassification is clearly not negligible. The two false-negative patterns are rare in the full data (1,977 and 1,319 Form 4 purchase legs). The pre-specified filter is unchanged; a post-review stricter filter (exclusion or buyback wording anywhere in the filing, IPO-window purchases) removes 19,281 disclosures and gives a test-period estimate of +0.52 pp (95% CI [-0.25, +1.28], p = 0.185, n = 4,791) (`tables/post_review/filter_sensitivity_estimates.csv`).
