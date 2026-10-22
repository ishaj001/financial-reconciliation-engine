-- CTE reconciles source totals while keeping count and monetary measures distinct.
WITH source_totals AS (
  SELECT side,currency,COUNT(*) AS source_rows,ROUND(SUM(amount),2) AS valid_amount
  FROM source_transactions WHERE run_id=:run_id AND validation_errors='' GROUP BY side,currency
), outcome_counts AS (
  SELECT outcome, COUNT(*) AS keys FROM reconciliation_results WHERE run_id=:run_id GROUP BY outcome
)
SELECT * FROM source_totals ORDER BY currency,side;

-- Source gross amount difference is calculated per currency; currencies are never added together.
SELECT currency,
       ROUND(SUM(CASE WHEN side='A' THEN amount ELSE 0 END),2) AS system_a_amount,
       ROUND(SUM(CASE WHEN side='B' THEN amount ELSE 0 END),2) AS system_b_amount,
       ROUND(SUM(CASE WHEN side='A' THEN amount ELSE -amount END),2) AS gross_difference
FROM source_transactions
WHERE run_id=:run_id AND validation_errors=''
GROUP BY currency ORDER BY currency;

-- Open exceptions by severity: the latest resolution event wins.
WITH latest AS (
  SELECT exception_id,status,ROW_NUMBER() OVER(PARTITION BY exception_id ORDER BY changed_at DESC,resolution_id DESC) rn
  FROM exception_resolutions
)
SELECT e.severity,e.issue_type,COUNT(*) AS unresolved_count
FROM exceptions e LEFT JOIN latest l ON l.exception_id=e.exception_id AND l.rn=1
WHERE e.run_id=:run_id AND COALESCE(l.status,'open') NOT IN ('resolved','accepted')
GROUP BY e.severity,e.issue_type ORDER BY e.severity,e.issue_type;
