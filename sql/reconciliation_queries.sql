-- Result-level counts and monetary differences by outcome.
SELECT outcome, COUNT(*) AS transaction_keys,
       CASE WHEN a.currency IS NOT NULL AND b.currency IS NOT NULL AND a.currency<>b.currency
            THEN a.currency || ' / ' || b.currency ELSE COALESCE(a.currency,b.currency,'ambiguous') END AS currency,
       SUM(COALESCE(amount_a, 0)) AS amount_a,
       SUM(COALESCE(amount_b, 0)) AS amount_b,
       SUM(COALESCE(amount_difference, 0)) AS net_difference
FROM reconciliation_results r
LEFT JOIN source_transactions a ON a.run_id=r.run_id AND a.side='A' AND a.transaction_id=r.transaction_id AND r.system_a_count=1
LEFT JOIN source_transactions b ON b.run_id=r.run_id AND b.side='B' AND b.transaction_id=r.transaction_id AND r.system_b_count=1
WHERE r.run_id = :run_id
GROUP BY outcome,CASE WHEN a.currency IS NOT NULL AND b.currency IS NOT NULL AND a.currency<>b.currency
                       THEN a.currency || ' / ' || b.currency ELSE COALESCE(a.currency,b.currency,'ambiguous') END;

-- A transaction can have multiple independent issue rows.
SELECT issue_type, severity, COUNT(*) AS issue_count
FROM exceptions WHERE run_id = :run_id GROUP BY issue_type, severity;

-- Latest audit resolution per exception, using a window function.
WITH ranked AS (
  SELECT exception_id,status,justification,changed_at,
         ROW_NUMBER() OVER(PARTITION BY exception_id ORDER BY changed_at DESC,resolution_id DESC) AS rn
  FROM exception_resolutions
)
SELECT e.exception_id,e.transaction_id,e.issue_type,COALESCE(r.status,'open') AS current_status,r.justification
FROM exceptions e LEFT JOIN ranked r ON r.exception_id=e.exception_id AND r.rn=1
WHERE e.run_id=:run_id;
