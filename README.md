# Financial Reconciliation & Controls Engine

A local portfolio application for financial data, data quality, analytics, and operations roles. It compares independent transaction ledgers, keeps run snapshots and investigation history, and produces traceable control reports. **All generated records are synthetic. This application is a portfolio demonstration, not a certified accounting or production payment control.**

## What it does

- Imports two CSV ledgers, validates their schema and values, and retains rejected rows with reasons.
- Reconciles unique transaction IDs and stores all applicable exceptions.
- Compares selected source rows field by field in the reconciliation workspace.
- Suggests possible candidates for one-sided unmatched records. A suggestion never changes a result; a human decision and justification are required and audited.
- Stores immutable run results, append-only resolution status updates, run events, and manual decisions in SQLite.
- Separates source and outcome amount totals by currency, without currency conversion.
- Exports result and exception CSV files and a formatted Excel workbook with source rows and audit history.

## Architecture and data flow

`src/data_generator.py` produces repeatable synthetic ledgers. `src/validation.py` parses CSV and checks required columns and row values. `src/reconciliation.py` applies the business key and comparison tolerances. `src/database.py` stores run metadata, original rows, reconciliation results, exceptions, and append-only events. `src/investigation.py` builds candidate suggestions and source control totals. `src/analytics.py` provides SQL outcome, issue, and dimension summaries. `src/reporting.py` exports database-backed CSV and Excel files. `main.py` and `app.py` use the same processing modules for CLI and Streamlit workflows.

Tables include `reconciliation_runs`, `source_transactions`, `reconciliation_results`, `exceptions`, `exception_resolutions`, `run_summaries`, `run_events`, and `manual_match_decisions`. Existing databases gain the `processing_status` column through a safe `ALTER TABLE` migration. A run starts as processing, then is completed or failed; prior results are never replaced. Streamlit selects and remembers the most recently populated local workspace database, so saved results remain visible after a browser or server restart. The app binds to `127.0.0.1` and is intended for one local user, not a shared server. Use the workspace's **Clear loaded files and synthetic data from this session** control to release dataframe copies held by the current UI session; persisted source rows remain in SQLite for investigation and audit.

Python/pandas handles CSV and row-level validation and matching; SQLite handles durable history, parameterized filters, grouped control totals, resolution ranking, and run comparisons. Example CTE, join, aggregate, and window queries are in `sql/`.

## Business and matching rules

The business key is `transaction_id`. If it occurs exactly once in each source, compare transaction date, settlement date, amount, currency, transaction type, and status. Default tolerances are **0.01** for amount and **0 calendar days** for dates; differences greater than the configured tolerance become exceptions. Amounts are compared only when currency codes agree. A currency mismatch is reported without calculating a meaningless cross-currency difference.

A key only on A is `missing_in_b`; a key only on B is `missing_in_a`. Any duplicate key is ambiguous and excluded from ordinary pair comparisons to prevent many-to-many multiplication. Invalid source rows are retained and appear as validation exceptions. Multiple findings for a key remain separate exception rows. Resolving or accepting an exception does not change a historical result to matched.

### Candidate suggestions

Suggestions are only generated for one-sided, unique unmatched keys. Candidates must have the same currency and transaction type, absolute amount difference no more than `max(1.00, 5% of the unmatched amount)`, and transaction and settlement dates each within three days. Results are sorted by amount difference, combined date distance, candidate ID, then source row. Multiple eligible candidates are marked ambiguous. These are investigation aids, not matches. Confirm/reject requires a justification and writes an append-only manual decision; reconciliation rows remain unchanged.

The matching key can be absent, reused, or incorrect; fuzzy matching is not used. Duplicate keys require investigation. Candidate thresholds are fixed defaults in this demonstration rather than configurable policy.

## Control totals and definitions

- **Source record counts**: ingested rows per side, including invalid and duplicate rows; validated control totals identify rejected rows separately.
- **Source gross amount totals**: valid amounts grouped by side and currency. The overview shows A/B counts, A/B totals, and A-minus-B count and amount differences by currency. No currencies are added together or converted.
- **Matched transaction controls**: result keys labeled matched, grouped by currency, with paired A/B amounts and A-minus-B difference. Values can differ within the configured tolerance.
- **Unresolved amount differences**: absolute differences for amount-mismatch exceptions whose latest resolution is open or under investigation. Resolved and accepted amount exceptions are shown in history, not unresolved totals.
- **Record match rate**: matched result keys divided by all result keys, including unmatched and ambiguous keys. Validation rejects are outside the result-key denominator and remain separately counted.
- **Outcome amount summaries**: valid transaction amounts grouped by result outcome and currency (or an explicit currency pair label for currency mismatches). Ambiguous duplicate groups have no paired amount.

Overview also supports source counts and amounts grouped by transaction date, type, or status (always separated by currency). Issue counts are grouped by exception category and severity. These controls are traceable to run-scoped source/result tables.

## Exception lifecycle and audit

Each exception begins as `open` until an update is recorded. Analysts can append `open`, `under investigation`, `resolved`, or `accepted` status with required notes/justification. Every update has a UTC timestamp; the full history is visible and exported. Original source rows, reconciliation results, and exception reasons are not edited. Run events also capture start, completion, failure, and manual-match decisions.

## Application navigation

1. **Overview**: source and outcome counts, currency-specific gross, matched and unresolved controls, and source breakdowns.
2. **Reconciliation Workspace**: upload two CSVs or generate clearly labeled synthetic ledgers, run with explicit tolerances, select a result, inspect source fields and all applicable findings, and view candidate suggestions.
3. **Exception Investigation**: searchable register filtered by run, issue, transaction identifier, resolution state, transaction date, and minimum absolute amount difference; inspect the full issue set and append a resolution.
4. **Run History**: processing status, identifiers, counts, issue history, and a comparison of outcome counts, issue counts, currency-specific reconciliation differences, and gross source differences across two completed runs.
5. **Reports**: download result CSV, exception CSV, or a formatted Excel workbook with Executive Summary, Control Totals, Matched Controls, Unresolved Controls, Outcome Totals, Matched, Unmatched, Exceptions, Resolution History, Manual Decisions, Run Metadata, Run Events, and Source Records.

The interface prioritizes compact data tables and investigation over decorative charts. Uploaded files are parsed in the local app process and persisted as source rows in the workspace SQLite database to support traceability. The app does not send them to an external service. Do not use real account or customer data.

## Synthetic demo data

The deterministic generator defaults to seed `2026` and at least 20,000 records per source. It introduces roughly 1% missing records on each side, 1% amount mismatches, 1% settlement-date mismatches, 0.5% status mismatches, 0.5% duplicate keys, and samples with unsupported currency, invalid amount/date, and missing transaction ID. Exact counts depend on rounding and source-row-preserving duplicate additions. All records are fictional.

## Install and run

Python 3.10 or newer is recommended. Run these from the project directory.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py init-db
python main.py generate-demo --rows 20000 --seed 2026 --out data/demo
python main.py reconcile --a data/demo/system_a.csv --b data/demo/system_b.csv
python -m streamlit run app.py
python -m pytest -q
```

If `py`/`python` is not on PATH but the Python 3.12 installation exists in the standard per-user location, create the environment with:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
```

Then use `python` after activating `.venv`, or call `\.venv\Scripts\python.exe` explicitly. The app URL printed by Streamlit is commonly `http://localhost:8501`.

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py init-db
python main.py generate-demo --rows 20000 --seed 2026 --out data/demo
python main.py reconcile --a data/demo/system_a.csv --b data/demo/system_b.csv
python -m streamlit run app.py
python -m pytest -q
```

The CLI runs independently of Streamlit. `init-db` prepares the default CLI database. `generate-demo` writes `system_a.csv` and `system_b.csv`; `reconcile` stores a completed run and prints its ID and controls. Use `python main.py reconcile --help` to set amount/date tolerances or a database path.

## Tests

Run `python -m pytest -q`. The tests use small specified ledgers for matches, missing keys, multiple issues, duplicates, currency mismatches, tolerances, bad schemas and malformed CSV, database persistence, separate immutable runs, resolution history, run comparisons, ambiguous candidate decisions, per-currency totals, and Excel sheets.

## Limitations

This is a local, single-user portfolio tool without authentication, fuzzy matching, currency conversion, investigator identity management, large-file streaming, accounting certification, or production-grade tamper-evident audit controls. It binds to localhost and is not designed for a shared multi-user server. Candidate thresholds are fixed and require analyst review. Database migrations are currently limited to additive schema updates.
