# data/

Not shipped. To reproduce, put the export produced by `scripts/download_data.py`
here so that the files sit in `data/raw/insider_data_export/`
(`manifest.json`, `sec_*.parquet`, `edgar_companies.parquet`, `tiingo_*.parquet`):

    unzip insider_data_export.zip -d data/raw/

The SEC-derived files are public data. The `tiingo_*` files contain prices
licensed to the Tiingo subscriber and should not be redistributed.
`scripts/s12_integrity.py` checks every file against the SHA-256 values in
`manifest.json` before trusting any result.
