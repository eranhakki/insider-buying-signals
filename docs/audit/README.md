# Hand-coded audit inputs

`filing_audit_35.csv` records the manual review of all 35 randomly sampled filings
(`output/original_v1/tables/audit_sample.csv`, seed 20260930). Each original
submission was read on EDGAR on 30 September 2026 (post-review). Columns: the
dataset's classification, what the filing shows, a verdict (correct /
false_positive / probable_false_positive / false_negative / flag_error), notes,
and links. This file is research input, not pipeline output; the pipeline reads
it (scripts/r03_filter_sensitivity.py) and never overwrites it.
