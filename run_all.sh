#!/usr/bin/env bash
# Regenerate every table, figure and document from data/raw/insider_data_export/.
#  1. the ORIGINAL pipeline (PRICE_QUALITY=v1) -> output/v1_reproduced/, checked against output/original_v1/
#  2. the CORRECTED pipeline (PRICE_QUALITY=v2, post-review) -> output/tables, figures, documents
set -euo pipefail
cd "$(dirname "$0")"
run() { echo "== $*"; python3 -u "$@"; }

export PRICE_QUALITY=v1
run scripts/s01_purchases.py
run scripts/s02_match_prices.py
run scripts/s03_signals.py 30
run scripts/s04_event_study.py --final
run scripts/s05_incremental.py --final

export PRICE_QUALITY=v2
run scripts/s01_purchases.py
run scripts/r01_price_quality.py          # post-review: classify price errors
run scripts/s02_match_prices.py
run scripts/s03_signals.py
run scripts/s04_event_study.py --final
run scripts/s05_incremental.py --final
run scripts/s06_robustness.py
run scripts/s07_audit.py
run scripts/s08_predictive.py
run scripts/r02_quality_impact.py         # post-review: what the price rule removes
run scripts/r03_filter_sensitivity.py     # post-review: stricter-filter sensitivity
run scripts/s09_figures.py
run scripts/s10_numbers.py
run scripts/s11_build_docs.py
run scripts/s13_export.py
run scripts/s12_integrity.py
