import numpy as np
import pandas as pd
import math

def generate_demo_data(records_per_source: int = 20000, seed: int = 2026) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create reproducible independent ledgers plus controlled exceptions.

    On the shared base: 1% A-only, 1% B-only, 1% amount, 1% date, 0.5% status,
    0.5% duplicate-key, 0.25% bad-value rows per source. Percentages use the
    internal base size; each output contains at least ``records_per_source`` rows.
    """
    if records_per_source < 10: raise ValueError("records_per_source must be at least 10")
    # Leave room for the intentionally removed records while keeping both
    # generated source files at or above the requested number of rows.
    n = math.ceil(records_per_source / 0.99)
    rng = np.random.default_rng(seed)
    ids = np.array([f"TX{seed:04d}{i:08d}" for i in range(n)], dtype=object)
    dates = pd.Timestamp("2025-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D")
    settles = dates + pd.to_timedelta(rng.integers(0, 4, n), unit="D")
    currencies = rng.choice(["USD", "EUR", "GBP", "CAD", "AUD", "INR"], n)
    amounts = np.round(rng.uniform(2, 2500, n), 2)
    base = pd.DataFrame({"transaction_id":ids,"transaction_date":dates.strftime("%Y-%m-%d"),"settlement_date":settles.strftime("%Y-%m-%d"),"amount":amounts,"currency":currencies,"transaction_type":rng.choice(["purchase","refund","fee","payout"], n),"status":rng.choice(["settled","pending","failed","reversed"], n, p=[.82,.09,.06,.03]),"source_system":"SYSTEM_A"})
    a, b = base.copy(), base.copy(); b["source_system"] = "SYSTEM_B"
    k = max(1, n // 100)
    # Missing records on either side, without modifying shared counterparts.
    a = a.drop(index=range(0, k)).reset_index(drop=True)
    b = b.drop(index=range(k, 2*k)).reset_index(drop=True)
    for idx in range(2*k, 3*k): b.loc[b.transaction_id.eq(ids[idx]), "amount"] += 3.17
    for idx in range(3*k, 4*k): b.loc[b.transaction_id.eq(ids[idx]), "settlement_date"] = (pd.Timestamp(settles[idx]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    for idx in range(4*k, 5*k): b.loc[b.transaction_id.eq(ids[idx]), "status"] = "pending" if base.iloc[idx].status != "pending" else "settled"
    dupes = base.iloc[5*k:5*k+max(1,n//200)].copy(); dupes["source_system"]="SYSTEM_A"; a=pd.concat([a,dupes],ignore_index=True)
    # Invalid values are preserved as rejects by validation.
    if n >= 100:
        a.loc[a.transaction_id.eq(ids[6*k]), "currency"] = "XYZ"
        b["amount"] = b["amount"].astype(object)
        b.loc[b.transaction_id.eq(ids[6*k+1]), "amount"] = "not-a-number"
        a.loc[a.transaction_id.eq(ids[6*k+2]), "transaction_date"] = "not-a-date"
        b.loc[b.transaction_id.eq(ids[6*k+3]), "transaction_id"] = None
    return a.reset_index(drop=True), b.reset_index(drop=True)
