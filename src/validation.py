from dataclasses import dataclass
import csv
import io
from typing import Any
import pandas as pd
from .config import REQUIRED_COLUMNS

SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "INR"}
VALID_STATUSES = {"settled", "pending", "failed", "reversed"}
VALID_TYPES = {"purchase", "refund", "fee", "payout"}

@dataclass
class ValidationResult:
    accepted: pd.DataFrame
    rejected: pd.DataFrame
    errors: list[str]

def validate_frame(frame: pd.DataFrame, source_label: str = "source") -> ValidationResult:
    if frame is None or not isinstance(frame, pd.DataFrame):
        raise ValueError(f"{source_label}: input is not a table")
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{source_label}: missing required columns: {', '.join(missing)}")
    if frame.empty:
        return ValidationResult(frame.copy(), frame.copy().assign(validation_errors=pd.Series(dtype=str)), [f"{source_label}: file contains no records"])
    data = frame.loc[:, REQUIRED_COLUMNS].copy().reset_index(drop=True)
    data["source_row"] = range(2, len(data) + 2)
    data["source_system"] = data["source_system"].fillna(source_label).astype(str)
    for col in ("transaction_id", "currency", "transaction_type", "status"):
        data[col] = data[col].where(data[col].notna(), "").astype(str).str.strip()
    data["amount"] = pd.to_numeric(data["amount"], errors="coerce")
    for col in ("transaction_date", "settlement_date"):
        data[col] = pd.to_datetime(data[col], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
        data[col] = data[col].where(data[col].notna(), None)
    issues = [[] for _ in range(len(data))]
    for i, row in data.iterrows():
        if not row.transaction_id: issues[i].append("missing_transaction_id")
        if pd.isna(row.transaction_date): issues[i].append("invalid_transaction_date")
        if pd.isna(row.settlement_date): issues[i].append("invalid_settlement_date")
        if pd.isna(row.amount) or not float("-inf") < float(row.amount) < float("inf"): issues[i].append("invalid_amount")
        if row.currency not in SUPPORTED_CURRENCIES: issues[i].append("unsupported_currency")
        if row.transaction_type not in VALID_TYPES: issues[i].append("unsupported_transaction_type")
        if row.status not in VALID_STATUSES: issues[i].append("unsupported_status")
    data["validation_errors"] = [";".join(x) for x in issues]
    rejected = data[data.validation_errors.ne("")].copy()
    accepted = data[data.validation_errors.eq("")].drop(columns="validation_errors").copy()
    errors = [f"{source_label}: rejected {len(rejected)} of {len(data)} rows"] if len(rejected) else []
    return ValidationResult(accepted, rejected, errors)

def read_csv_upload(payload: bytes, filename: str, source_label: str = "source") -> pd.DataFrame:
    if not payload: raise ValueError(f"{filename}: uploaded file is empty")
    try:
        text = payload.decode("utf-8-sig")
        records = csv.reader(io.StringIO(text, newline=""))
        header = next(records, None)
        if not header:
            raise ValueError("CSV has no header")
        for line_number, record in enumerate(records, start=2):
            if record and len(record) != len(header):
                raise ValueError(f"row {line_number} has {len(record)} fields; expected {len(header)}")
        frame = pd.read_csv(pd.io.common.BytesIO(payload))
    except Exception as exc:
        raise ValueError(f"{filename}: could not parse CSV: {exc}") from exc
    if frame.empty: raise ValueError(f"{filename}: CSV has headers but no records")
    return frame
