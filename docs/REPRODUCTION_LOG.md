# Reproduction log

## Post-review clean-environment rerun (30 September 2026)

* Fresh directory containing only `src/`, `scripts/`, `archive/`, `docs/` (templates, analysis plan, freeze file, hand-coded `docs/audit/filing_audit_35.csv`), `paper/` template, `output/original_v1/` (the preserved original outputs, needed for comparison), `run_all.sh`, `requirements.txt` and the raw export `data/raw/insider_data_export/`. Every generated table, figure, number file and document was removed first.
* Python 3.11 virtual environment with the packages pinned in `requirements.txt`.
* `bash run_all.sh`: the original pipeline (`PRICE_QUALITY=v1`) followed by the corrected pipeline, post-review steps, documents and integrity checks, in 47 minutes on 2 CPU cores / 8 GB RAM.

**Result.**

* `scripts/s12_integrity.py` passed all 36 checks.
* Every regenerated table in `output/tables/` and `output/tables/post_review/`, `output/numbers.json` (606 values), and the filled `paper/paper.md`, `README.md`, `POST_REVIEW_CHANGES.md` and `docs/DATA_AUDIT.md` are identical to the working copy from which the delivered project was built.
* The regenerated original outputs (`output/v1_reproduced/tables/`) are identical to the preserved originals (`output/original_v1/tables/`).

## Earlier clean rerun (original version, 30 September 2026)

The pre-review project was also rerun from a clean environment. That run exposed one table produced by one-off audit code rather than a pipeline step, which was fixed at the time. It then reproduced every table and number of the original version exactly.

## What could not be reproduced or verified here

* **The download itself.** The analysis workspace cannot reach sec.gov or api.tiingo.com, so `scripts/download_data.py` ran on the author's computer. It was tested here only against mocked responses; its outputs are verified by SHA-256 on every run.
* **Tiingo price accuracy.** Prices were checked against Form 4 transaction prices (matching) and, post-review, for internal consistency (stale quotes, spikes, gaps, implausible moves). They were not checked against a second vendor or CRSP. Unrecorded reverse splits smaller than 10× cannot be detected.
* **Point-in-time Tiingo content.** Tiingo's adjusted history and ticker coverage can change; a later download may differ.
* **Timing of the plan and freeze.** This is attested by file hashes recorded in the workspace, not by an external timestamping service. The same analyst built the development results, ran the test and made the post-review corrections.
* **Manual EDGAR review.** All 35 sampled filings were read on EDGAR. The classifications are one reviewer's judgement, recorded with reasons in `docs/audit/filing_audit_35.csv`. The Metropolitan Bank IPO price was confirmed from the company's press release.
