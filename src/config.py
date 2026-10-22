from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_DB = ROOT / "data" / "reconciliation.sqlite3"
WORKSPACE_POINTER = ROOT / "data" / ".streamlit_workspace"
if WORKSPACE_POINTER.exists():
    _workspace_name = WORKSPACE_POINTER.read_text(encoding="utf-8").strip()
    _workspace_candidate = (BASE_DB.parent / _workspace_name).resolve()
    DEFAULT_DB = _workspace_candidate if _workspace_candidate.parent == BASE_DB.parent.resolve() else BASE_DB
else:
    DEFAULT_DB = BASE_DB
REQUIRED_COLUMNS = ("transaction_id", "transaction_date", "settlement_date", "amount", "currency", "transaction_type", "status", "source_system")

@dataclass(frozen=True)
class ReconciliationConfig:
    amount_tolerance: float = 0.01
    date_tolerance_days: int = 0

    def __post_init__(self):
        if self.amount_tolerance < 0 or self.date_tolerance_days < 0:
            raise ValueError("Comparison tolerances must be non-negative")
