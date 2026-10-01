# Analysis plan (written before any return was computed)

Written 2026-09-30 after the raw data had been downloaded and checksummed, and
**before any stock return, event return or test statistic was calculated**.
Every threshold below is fixed here. Anything changed later is listed in the
"Deviations" section at the bottom, with the reason and date.

## 1. Question

At the moment a second, distinct officer or director's open-market purchase is
publicly disclosed within *W* = 30 calendar days of a first disclosed purchase,
does the stock's subsequent market-adjusted return differ from that of an
otherwise similar first-buy episode that, **at the same elapsed time**, still has
only one buyer?

H0: the second-buyer indicator adds no information (difference = 0).

## 2. Periods

| Period | Signal (filing) dates | Use |
|---|---|---|
| Development | 2006-01-01 to 2018-12-31 | building filters, checking code, choosing nothing that depends on returns |
| Test (held out) | 2019-01-01 to 2026-06-30 | run once, with the frozen specification |

Winsorisation cut-offs, size/liquidity tercile cut-offs and "high/low" regime
cut-offs are estimated on the development period only and applied unchanged to
the test period.

## 3. Eligible purchase (primary definition)

A non-derivative transaction row is eligible if all of the following hold:

1. Filing `DOCUMENT_TYPE` = `4` (original Form 4). Amendments (4/A) never create
   signals in the primary analysis (see §6).
2. `TRANS_CODE` = `P` and `TRANS_ACQUIRED_DISP_CD` = `A`.
3. At least one reporting owner on the filing has relationship OFFICER or
   DIRECTOR. Filings whose owners are only 10% owners / "other" are excluded.
4. Security title looks like common/ordinary equity: it matches
   `common|ordinary|class [a-c]|shares|stock` and does **not** match
   `preferred|pref\b|warrant|note|debenture|unit|right|option|depositary|\bads\b|bond|convertible|trust preferred|series [a-z] pref`.
5. `TRANS_SHARES` > 0 and `TRANS_PRICEPERSHARE` > 0.
6. `EQUITY_SWAP_INVOLVED` is not true; `NOT_SUBJECT_SEC16` is not true.
7. Transaction date is not after the filing date and not more than 365 days
   before it.
8. **Footnote screen (non-open-market acquisitions).** The row is excluded if any
   footnote referenced on that row, or the filing's REMARKS, matches (case-
   insensitive): `private placement|privately negotiated|subscription agreement|
   directly from the (company|issuer)|from the issuer|purchased from the company|
   registered direct|public offering|underwritten|initial public offering|\bipo\b|
   directed share|rights offering|employee stock purchase|\bespp\b|dividend
   reinvestment|\bdrip\b|401\(k\)|conversion of|converted|in exchange for|
   exchange offer|merger|spin-?off|distribution from|gift`.
   Filings with any such footnote are retained in an audit file so the screen can
   be checked by hand (§10).
9. Issuer SIC (EDGAR) not in {6722, 6726} (registered funds / closed-end funds).

Rule-10b5-1 plan purchases (field `AFF10B5ONE`, only populated from 2023, or a
footnote mentioning 10b5-1) are **kept** in the primary sample and dropped in a
robustness check.

## 4. From rows to disclosures and signals

* **Disclosure** = (issuer CIK, filing date, owner group). An owner group is the
  set of reporting-owner CIKs on an accession (joint filers form one group, since
  the data do not say which joint filer bought). Same-day accessions whose owner
  groups overlap are merged. Duplicate rows (same accession + transaction key, or
  identical owner/trans-date/shares/price across accessions filed the same day)
  are dropped. Purchase value = Σ shares × price.
* **Buyer identity**: two disclosures are from *distinct* buyers only if their
  owner-CIK sets do not intersect.
* **First-buy signal (episode start) at date F**: an eligible disclosure for an
  issuer with **no** eligible disclosure for that issuer in the preceding W
  calendar days (F−W ≤ d < F).
* **Episode**: F to F+W. Buyers disclosed on day F are the "initial buyers". If
  two or more distinct buyers are disclosed on day F itself the episode is a
  *same-day cluster*; it is reported in the event study but excluded from the
  incremental test (the extra buyer is already known at the first signal).
* **Second-buyer signal at date S**: the first date in (F, F+W] on which an
  eligible disclosure appears from a buyer distinct from all initial buyers.
  Signal date = S (the second **disclosure** date). Later buyers in the same
  episode do not create further signals. Repeat purchases by the initial buyer
  are not second buyers.
* Only information with a filing date ≤ the signal date is used to build any
  signal or covariate.

## 5. Timing and returns

* EDGAR assigns Forms 3/4/5 submitted up to 10 p.m. ET the same filing date, so
  a filing dated D may become public after the close on D. **Primary entry:
  closing price on the first trading day after D (t+1 close).** Sensitivities:
  t+1 open, t+2 close, and t+0 close (shown only as an upper bound because it can
  use prices from before publication).
* Returns: Tiingo split- and dividend-adjusted close (open for the t+1 open
  variant). Horizons h = 20 and 60 trading days after entry.
* Market-adjusted buy-and-hold return = stock BHR − SPY BHR over the same days.
  Robustness benchmarks: IWM, and a sector SPDR ETF assigned from SIC.
* **Primary outcome: 60-day SPY-adjusted BHR**, winsorised at the 1st/99th
  percentiles of the development distribution. 20-day is secondary.
* **Delisting / missing data**: if the price series ends before the horizon, the
  return runs to the last available price (primary). Robustness: an additional
  −30% return is applied at the last price (Shumway-style), and events with
  incomplete windows are dropped.
* Price-data floor: last close before the signal ≥ $1 (data-quality floor).

## 6. Amendments and late filings

* Signals use only original Form 4 filing dates (what the public saw first).
* A 4/A with an eligible purchase that has no matching original Form 4 row (same
  issuer, owner, transaction date, shares within 1%) is counted and, in a
  robustness check, added with the 4/A filing date as its disclosure date.
* Filing lag (filing − transaction date) is recorded. Robustness: drop
  disclosures filed more than 4 business days after the trade (late filers).

## 7. Issuer-to-price matching

Candidate tickers in order: the symbol on the Form 4 itself (point-in-time,
OTC suffixes such as `.OB`/`.PK` stripped), then the issuer's current EDGAR
tickers. For each candidate with Tiingo data, the purchase price is compared
with Tiingo's **unadjusted** close on the transaction date (or the previous
trading day). Ratio r = reported price / close.

* Issuer–ticker link accepted if the median r over that issuer's disclosures on
  that ticker lies in [0.8, 1.25]; the first accepted candidate is used.
* **Primary**: event-level r in [0.67, 1.5]. **Strict robustness**: r in
  [0.9, 1.1]. Events whose issuer cannot be matched are counted by year in the
  coverage table (this is the main survivorship measure available).

## 8. Covariates known at the signal (or landmark) date

Prior returns (t−21..t−1 and t−126..t−1 trading days), log median daily dollar
volume over the prior 60 trading days (size/liquidity proxy; no shares
outstanding are available), log price, prior 60-day volatility, log purchase
value of the initial buyer(s), initial-buyer role (officer incl. any officer
title vs director-only), whether the initial buyer is CEO/CFO/President/Chair by
title, number of repeat purchases by the initial buyer before the landmark,
EDGAR SIC division, year.

## 9. Primary incremental test (landmark matching)

For each second-buyer signal i (episode start F_i, lag k_i = S_i − F_i calendar
days) choose up to **5 control episodes** that:

* started within ±60 calendar days of F_i, at a different issuer;
* have exactly the same lag available and had **no** second buyer disclosed by
  F + k_i (they were still single-buyer episodes at that point — information
  available at the time; controls may acquire a second buyer later);
* are not same-day clusters and pass the same price filters at their landmark
  L = F + k_i;
* are nearest in standardised distance on: prior 21-day return, prior 126-day
  return (both measured to the landmark), log dollar volume, log initial purchase
  value.

Controls are measured from their landmark with exactly the same timing rule as
the treated signal. Estimator: OLS of winsorised 60-day SPY-adjusted return on
a treated indicator plus the §8 covariates and year dummies, weighting each
control by 1/(number of controls for that treated event). Standard errors
two-way clustered by issuer and by signal month. A block bootstrap by calendar
month (1,000 draws) is reported alongside. Two-sided test at 5%.

The same procedure is run on the development period (for code checking and for
fixing cut-offs) and then **once** on the test period. The test-period
coefficient is the headline result.

A secondary predictive check: an OLS model of the 60-day return fitted on the
development period with and without the second-buyer indicator, evaluated
out-of-sample on the test period (difference in rank IC and R²).

## 10. Event study (descriptive)

First-buy signals (single initial buyer), same-day clusters and second-buyer
signals: mean, median, and share-positive of raw and SPY-adjusted 20/60-day
returns, 95% CIs from two-way clustered SEs (issuer, month), by year, and a
calendar-time equal-weighted portfolio (daily; each event held for h days; CAPM
alpha vs SPY with Newey-West SEs), which removes the overlap problem.

## 11. Robustness checks (all pre-listed, all reported whatever they show)

1. Cluster window W = 14 and 60 days (episodes rebuilt).
2. Roles: second buyer officer vs director-only; initial buyer officer vs
   director-only.
3. Purchase size: second buyer's value below/above the development median.
4. Timing: t+1 open, t+2 close, t+0 close.
5. Liquidity: price ≥ $5 and median dollar volume ≥ $1m; strict price match.
6. Market conditions: SPY trailing 252-day return < 0 vs ≥ 0; SPY 60-day
   realised volatility above vs below the development median.
7. Calendar: each year; excluding 2008–09 and 2020.
8. Delisting: −30% delisting return; complete-window events only.
9. Excluding 10b5-1-flagged and late-filed disclosures; adding 4/A-only
   purchases.
10. Concentration: dropping the 1% of issuers with most events; leave-one-year-
    out.
11. Benchmarks: IWM and sector ETF.

Subgroups with fewer than 100 treated events are reported but labelled
"too small for a claim".

## 12. Manual audit

A random sample (seed 20260930) of 15 included and 15 excluded P-code filings,
plus 5 footnote-screened filings, is listed with accession numbers and EDGAR
links; a subset is read on EDGAR and compared with the dataset.

## Deviations



1. **2026-09-30, before any return was computed — fund filter.** EDGAR assigns
   no SIC code to registered investment companies, so the §3.9 rule (SIC
   6722/6726) removed nothing. Replaced by: issuer has a blank EDGAR SIC *and* a
   fund-style name (`fund|trust|portfolio|municipal|income|opportunit|strateg`).
   Business development companies ("... Capital Corp") and operating companies
   with a blank SIC are kept.
2. **2026-09-30, before any return was computed — duplicates.** §4 dropped
   identical legs even within one accession; identical legs in one accession are
   usually separate lots (e.g. direct and IRA holdings) so only identical legs
   in *different* accessions filed the same day are now treated as duplicates.
3. **2026-09-30, before any return was computed — footnote screen.** Reading a
   sample of screened legs showed the §3.8 screen caught footnotes attached to
   *post-transaction holdings* ("includes shares received in the merger",
   "excludes shares gifted in 2007") and currency notes ("converted to US
   dollars"). The screen now reads only footnotes referenced by transaction
   fields (security title, date, shares, price, code, timeliness, swap) plus
   REMARKS; "converted", "gift", "distribution from" and bare "merger" were
   dropped ("pursuant to/in connection with the merger" and "merger
   consideration" kept). The 10b5-1 flag still reads every footnote.

Changes made **after** the test-period results were seen (price-data corrections,
the completed filing audit, a stricter-filter sensitivity and tightened wording)
are not deviations from this pre-registered plan. They are documented as
post-review sensitivity analyses in `POST_REVIEW_CHANGES.md`, and the original
results are preserved in `output/original_v1/`.
