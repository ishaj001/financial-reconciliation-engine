from datetime import date
from .database import table

def candidate_matches(run_id: str, transaction_id: str, path, amount_pct: float = 0.05, date_days: int = 3):
    """Return deterministic suggestions for a one-sided key; suggestions never alter results."""
    result=table(path,"SELECT outcome FROM reconciliation_results WHERE run_id=? AND transaction_id=?",(run_id,transaction_id))
    if result.empty or result.iloc[0].outcome not in {"missing_in_a","missing_in_b"}: return []
    missing_side=result.iloc[0].outcome
    source_side="A" if missing_side=="missing_in_b" else "B"
    candidate_side="A" if source_side=="B" else "B"
    target=table(path,"SELECT source_row,transaction_date,settlement_date,amount,currency,transaction_type,status FROM source_transactions WHERE run_id=? AND side=? AND transaction_id=? AND validation_errors=''",(run_id,source_side,transaction_id))
    if len(target)!=1: return []
    t=target.iloc[0]
    eligible_outcome="missing_in_b" if candidate_side=="A" else "missing_in_a"
    choices=table(path,"SELECT s.source_row,s.transaction_id,s.transaction_date,s.settlement_date,s.amount,s.currency,s.transaction_type,s.status FROM source_transactions s JOIN reconciliation_results r ON r.run_id=s.run_id AND r.transaction_id=s.transaction_id WHERE s.run_id=? AND s.side=? AND s.validation_errors='' AND r.outcome=?",(run_id,candidate_side,eligible_outcome))
    candidates=[]
    for _,c in choices.iterrows():
        if t.currency!=c.currency or t.transaction_type!=c.transaction_type: continue
        amount_diff=abs(float(t.amount)-float(c.amount)); amount_limit=max(1.0,abs(float(t.amount))*amount_pct)
        txn_days=abs((date.fromisoformat(t.transaction_date)-date.fromisoformat(c.transaction_date)).days)
        settlement_days=abs((date.fromisoformat(t.settlement_date)-date.fromisoformat(c.settlement_date)).days)
        if amount_diff>amount_limit or max(txn_days,settlement_days)>date_days: continue
        reasons=["same currency","same transaction type",f"amount difference {amount_diff:.2f} within {amount_limit:.2f}",f"dates differ by {txn_days}/{settlement_days} day(s)"]
        if t.status!=c.status: reasons.append(f"status differs: {t.status} vs {c.status}")
        candidates.append({"transaction_id":c.transaction_id,"source_side":candidate_side,"source_row":int(c.source_row),"candidate_status":c.status,"target_status":t.status,"amount_difference":round(amount_diff,2),"transaction_date_difference_days":txn_days,"settlement_date_difference_days":settlement_days,"reasons":"; ".join(reasons),"ambiguous":False,"system_a_row":int(t.source_row) if source_side=="A" else int(c.source_row),"system_b_row":int(t.source_row) if source_side=="B" else int(c.source_row)})
    candidates.sort(key=lambda x:(x["amount_difference"],x["transaction_date_difference_days"]+x["settlement_date_difference_days"],x["transaction_id"],x["source_row"]))
    for item in candidates: item["ambiguous"]=len(candidates)>1
    return candidates

def source_totals_by_currency(run_id,path):
    return table(path,"""SELECT currency,
        SUM(CASE WHEN side='A' THEN 1 ELSE 0 END) system_a_records,
        ROUND(SUM(CASE WHEN side='A' THEN amount ELSE 0 END),2) system_a_amount,
        SUM(CASE WHEN side='B' THEN 1 ELSE 0 END) system_b_records,
        ROUND(SUM(CASE WHEN side='B' THEN amount ELSE 0 END),2) system_b_amount,
        SUM(CASE WHEN side='A' THEN 1 ELSE 0 END)-SUM(CASE WHEN side='B' THEN 1 ELSE 0 END) record_count_difference,
        ROUND(SUM(CASE WHEN side='A' THEN amount ELSE 0 END)-SUM(CASE WHEN side='B' THEN amount ELSE 0 END),2) gross_amount_difference
        FROM source_transactions WHERE run_id=? AND validation_errors='' GROUP BY currency ORDER BY currency""",(run_id,))

def matched_controls_by_currency(run_id,path):
    return table(path,"""SELECT a.currency,COUNT(*) matched_keys,
        ROUND(SUM(r.amount_a),2) matched_amount_a,ROUND(SUM(r.amount_b),2) matched_amount_b,
        ROUND(SUM(r.amount_difference),2) matched_amount_difference
      FROM reconciliation_results r JOIN source_transactions a ON a.run_id=r.run_id AND a.side='A' AND a.transaction_id=r.transaction_id AND a.validation_errors=''
      WHERE r.run_id=? AND r.outcome='matched' AND r.system_a_count=1 AND r.system_b_count=1
      GROUP BY a.currency ORDER BY a.currency""",(run_id,))

def unresolved_controls_by_currency(run_id,path):
    return table(path,"""WITH latest AS (
        SELECT exception_id,status,ROW_NUMBER() OVER(PARTITION BY exception_id ORDER BY changed_at DESC,resolution_id DESC) rn
        FROM exception_resolutions
    ) SELECT a.currency,COUNT(*) unresolved_amount_exceptions,
        ROUND(SUM(ABS(r.amount_difference)),2) unresolved_absolute_amount_difference
      FROM exceptions e JOIN reconciliation_results r ON r.run_id=e.run_id AND r.transaction_id=e.transaction_id
      JOIN source_transactions a ON a.run_id=e.run_id AND a.side='A' AND a.transaction_id=e.transaction_id AND r.system_a_count=1
      LEFT JOIN latest l ON l.exception_id=e.exception_id AND l.rn=1
      WHERE e.run_id=? AND e.issue_type='amount_mismatch' AND COALESCE(l.status,'open') NOT IN ('resolved','accepted')
      GROUP BY a.currency ORDER BY a.currency""",(run_id,))
