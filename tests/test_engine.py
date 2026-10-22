import pandas as pd
import pytest
from src.validation import validate_frame
from src.reconciliation import reconcile
from src.config import ReconciliationConfig
from src.data_generator import generate_demo_data

def frame(rows):
    return pd.DataFrame(rows,columns=["transaction_id","transaction_date","settlement_date","amount","currency","transaction_type","status","source_system"])

def row(key,amount=10,date="2025-01-01",settle="2025-01-02",status="settled",currency="USD",kind="purchase",system="A"):
    return [key,date,settle,amount,currency,kind,status,system]

def test_perfect_and_missing_and_multiple_issues():
    a=frame([row("same"),row("only-a")]); b=frame([row("same",12,date="2025-01-03",status="pending",system="B"),row("only-b",system="B")])
    out=reconcile(a,b)
    assert out.results.set_index("transaction_id").loc["same","outcome"]=="mismatch"
    assert set(out.exceptions[out.exceptions.transaction_id.eq("same")].issue_type)=={"amount_mismatch","transaction_date_mismatch","status_mismatch"}
    assert set(out.results.outcome)=={"mismatch","missing_in_a","missing_in_b"}
    assert out.summary["matched_keys"]==0

def test_tolerances_and_perfect_match():
    a=frame([row("x")]); b=frame([row("x",10.005,date="2025-01-02",system="B")])
    out=reconcile(a,b,ReconciliationConfig(.01,1))
    assert out.results.iloc[0].outcome=="matched" and out.exceptions.empty
    assert reconcile(a,a.copy()).summary["matched_keys"]==1

def test_duplicates_are_ambiguous_not_multiplied():
    a=frame([row("dup"),row("dup",11)]); b=frame([row("dup",system="B")])
    out=reconcile(a,b)
    assert out.results.iloc[0].outcome=="ambiguous_duplicate"
    assert "duplicate_key" in out.exceptions.issue_type.tolist()

def test_currency_mismatch_does_not_calculate_cross_currency_amount_difference():
    a=frame([row("fx",amount=10,currency="USD")]); b=frame([row("fx",amount=12,currency="EUR",system="B")])
    out=reconcile(a,b)
    result=out.results.iloc[0]
    assert result.outcome=="mismatch" and pd.isna(result.amount_difference)
    assert "currency_mismatch" in out.exceptions.issue_type.tolist()

def test_validation_retains_invalid_rows_and_rejects_schema():
    a=frame([row("bad",amount="oops",date="no-date",currency="XYZ")]); result=validate_frame(a)
    assert len(result.rejected)==1 and len(result.accepted)==0
    assert {"invalid_amount","invalid_transaction_date","unsupported_currency"}.issubset(set(result.rejected.iloc[0].validation_errors.split(";")))
    with pytest.raises(ValueError,match="missing required columns"): validate_frame(pd.DataFrame({"transaction_id":[]}))

def test_empty_upload_and_csv_parse_errors():
    from src.validation import read_csv_upload
    with pytest.raises(ValueError,match="empty"): read_csv_upload(b"","empty.csv")
    with pytest.raises(ValueError,match="no records"): read_csv_upload(b"transaction_id,amount\n","header.csv")
    with pytest.raises(ValueError,match="could not parse CSV"): read_csv_upload(b"a,b\n1,2,3\n4,5\n","malformed.csv")

def test_generator_reproducible():
    a1,b1=generate_demo_data(1000,7); a2,b2=generate_demo_data(1000,7)
    pd.testing.assert_frame_equal(a1,a2); pd.testing.assert_frame_equal(b1,b2)
