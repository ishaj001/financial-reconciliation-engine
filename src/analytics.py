from .database import table

def outcome_summary(run_id, path):
    return table(path,"""SELECT r.outcome,CASE WHEN a.currency IS NOT NULL AND b.currency IS NOT NULL AND a.currency<>b.currency THEN a.currency||' / '||b.currency ELSE COALESCE(a.currency,b.currency,'ambiguous') END currency,COUNT(*) transaction_keys,
        SUM(COALESCE(r.amount_a,0)) amount_a,SUM(COALESCE(r.amount_b,0)) amount_b,
        SUM(COALESCE(r.amount_difference,0)) net_amount_difference FROM reconciliation_results r
        LEFT JOIN source_transactions a ON a.run_id=r.run_id AND a.side='A' AND a.transaction_id=r.transaction_id AND r.system_a_count=1
        LEFT JOIN source_transactions b ON b.run_id=r.run_id AND b.side='B' AND b.transaction_id=r.transaction_id AND r.system_b_count=1
        WHERE r.run_id=? GROUP BY r.outcome,CASE WHEN a.currency IS NOT NULL AND b.currency IS NOT NULL AND a.currency<>b.currency THEN a.currency||' / '||b.currency ELSE COALESCE(a.currency,b.currency,'ambiguous') END ORDER BY r.outcome,currency""",(run_id,))

def exception_summary(run_id, path):
    return table(path,"SELECT e.issue_type, e.severity, COUNT(*) AS exception_count, SUM(CASE WHEN r.status IN ('resolved','accepted') THEN 1 ELSE 0 END) AS closed_count FROM exceptions e LEFT JOIN (SELECT exception_id,status,ROW_NUMBER() OVER(PARTITION BY exception_id ORDER BY changed_at DESC,resolution_id DESC) rn FROM exception_resolutions) r ON r.exception_id=e.exception_id AND r.rn=1 WHERE e.run_id=? GROUP BY e.issue_type,e.severity ORDER BY exception_count DESC",(run_id,))

def source_controls_by_dimension(run_id, dimension, path):
    columns={"Date":"transaction_date","Transaction type":"transaction_type","Status":"status"}
    if dimension not in columns: raise ValueError("Unsupported control dimension")
    column=columns[dimension]
    return table(path,f"SELECT side,currency,{column} AS control_value,COUNT(*) record_count,ROUND(SUM(amount),2) amount_total FROM source_transactions WHERE run_id=? AND validation_errors='' GROUP BY side,currency,{column} ORDER BY currency,control_value,side",(run_id,))
