from io import BytesIO
import json
import pandas as pd
from .database import table

def run_frames(run_id, path):
    results=table(path,"SELECT transaction_id,outcome,system_a_count,system_b_count,amount_a,amount_b,amount_difference FROM reconciliation_results WHERE run_id=? ORDER BY transaction_id",(run_id,))
    exceptions=table(path,"SELECT e.exception_id,e.transaction_id,e.issue_type,e.source_side,e.system_a_row,e.system_b_row,e.details,e.severity,COALESCE((SELECT status FROM exception_resolutions x WHERE x.exception_id=e.exception_id ORDER BY changed_at DESC,resolution_id DESC LIMIT 1),'open') AS resolution_status,(SELECT justification FROM exception_resolutions x WHERE x.exception_id=e.exception_id ORDER BY changed_at DESC,resolution_id DESC LIMIT 1) AS justification FROM exceptions e WHERE e.run_id=? ORDER BY e.exception_id",(run_id,))
    summary=table(path,"SELECT created_at,source_a_name,source_b_name,config_json,summary_json FROM reconciliation_runs WHERE run_id=?",(run_id,))
    return results,exceptions,summary

def csv_bytes(frame): return frame.to_csv(index=False).encode("utf-8-sig")

def excel_bytes(run_id,path):
    results,exceptions,meta=run_frames(run_id,path)
    matched=results[results.outcome.eq("matched")]; unmatched=results[~results.outcome.eq("matched")]
    sources=table(path,"SELECT side,source_row,transaction_id,transaction_date,settlement_date,amount,currency,transaction_type,status,validation_errors FROM source_transactions WHERE run_id=? ORDER BY side,source_row",(run_id,))
    result_totals=table(path,"""SELECT r.outcome,CASE WHEN a.currency IS NOT NULL AND b.currency IS NOT NULL AND a.currency<>b.currency THEN a.currency||' / '||b.currency ELSE COALESCE(a.currency,b.currency,'ambiguous') END currency,COUNT(*) transaction_keys,
        SUM(COALESCE(r.amount_a,0)) amount_a,SUM(COALESCE(r.amount_b,0)) amount_b,SUM(COALESCE(r.amount_difference,0)) net_amount_difference
        FROM reconciliation_results r LEFT JOIN source_transactions a ON a.run_id=r.run_id AND a.side='A' AND a.transaction_id=r.transaction_id AND r.system_a_count=1
        LEFT JOIN source_transactions b ON b.run_id=r.run_id AND b.side='B' AND b.transaction_id=r.transaction_id AND r.system_b_count=1
        WHERE r.run_id=? GROUP BY r.outcome,CASE WHEN a.currency IS NOT NULL AND b.currency IS NOT NULL AND a.currency<>b.currency THEN a.currency||' / '||b.currency ELSE COALESCE(a.currency,b.currency,'ambiguous') END ORDER BY r.outcome,currency""",(run_id,))
    source_totals=table(path,"""SELECT currency,SUM(CASE WHEN side='A' THEN 1 ELSE 0 END) system_a_records,
        ROUND(SUM(CASE WHEN side='A' THEN amount ELSE 0 END),2) system_a_amount,
        SUM(CASE WHEN side='B' THEN 1 ELSE 0 END) system_b_records,
        ROUND(SUM(CASE WHEN side='B' THEN amount ELSE 0 END),2) system_b_amount,
        SUM(CASE WHEN side='A' THEN 1 ELSE 0 END)-SUM(CASE WHEN side='B' THEN 1 ELSE 0 END) record_count_difference,
        ROUND(SUM(CASE WHEN side='A' THEN amount ELSE 0 END)-SUM(CASE WHEN side='B' THEN amount ELSE 0 END),2) gross_amount_difference
        FROM source_transactions WHERE run_id=? AND validation_errors='' GROUP BY currency ORDER BY currency""",(run_id,))
    matched_totals=table(path,"""SELECT a.currency,COUNT(*) matched_keys,ROUND(SUM(r.amount_a),2) matched_amount_a,
        ROUND(SUM(r.amount_b),2) matched_amount_b,ROUND(SUM(r.amount_difference),2) matched_amount_difference
        FROM reconciliation_results r JOIN source_transactions a ON a.run_id=r.run_id AND a.side='A' AND a.transaction_id=r.transaction_id AND a.validation_errors=''
        WHERE r.run_id=? AND r.outcome='matched' AND r.system_a_count=1 AND r.system_b_count=1 GROUP BY a.currency ORDER BY a.currency""",(run_id,))
    unresolved_totals=table(path,"""WITH latest AS (SELECT exception_id,status,ROW_NUMBER() OVER(PARTITION BY exception_id ORDER BY changed_at DESC,resolution_id DESC) rn FROM exception_resolutions)
        SELECT a.currency,COUNT(*) unresolved_amount_exceptions,ROUND(SUM(ABS(r.amount_difference)),2) unresolved_absolute_amount_difference
        FROM exceptions e JOIN reconciliation_results r ON r.run_id=e.run_id AND r.transaction_id=e.transaction_id
        JOIN source_transactions a ON a.run_id=e.run_id AND a.side='A' AND a.transaction_id=e.transaction_id AND r.system_a_count=1
        LEFT JOIN latest l ON l.exception_id=e.exception_id AND l.rn=1
        WHERE e.run_id=? AND e.issue_type='amount_mismatch' AND COALESCE(l.status,'open') NOT IN ('resolved','accepted')
        GROUP BY a.currency ORDER BY a.currency""",(run_id,))
    control_totals=source_totals
    summary_json=json.loads(meta.iloc[0].summary_json) if not meta.empty else {}
    executive=pd.DataFrame([{"run_id":run_id,**summary_json}])
    resolution=table(path,"SELECT e.exception_id,e.transaction_id,x.status,x.justification,x.changed_at FROM exceptions e JOIN exception_resolutions x ON x.exception_id=e.exception_id WHERE e.run_id=? ORDER BY e.exception_id,x.changed_at,x.resolution_id",(run_id,))
    decisions=table(path,"SELECT decision_id,transaction_id,system_a_row,system_b_row,decision,justification,changed_at FROM manual_match_decisions WHERE run_id=? ORDER BY decision_id",(run_id,))
    events=table(path,"SELECT event_type,details,changed_at FROM run_events WHERE run_id=? ORDER BY changed_at,event_id",(run_id,))
    out=BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as writer:
        executive.to_excel(writer,sheet_name="Executive Summary",index=False); control_totals.to_excel(writer,sheet_name="Control Totals",index=False); matched_totals.to_excel(writer,sheet_name="Matched Controls",index=False); unresolved_totals.to_excel(writer,sheet_name="Unresolved Controls",index=False); result_totals.to_excel(writer,sheet_name="Outcome Totals",index=False)
        matched.to_excel(writer,sheet_name="Matched",index=False); unmatched.to_excel(writer,sheet_name="Unmatched",index=False); exceptions.to_excel(writer,sheet_name="Exceptions",index=False)
        resolution.to_excel(writer,sheet_name="Resolution History",index=False); decisions.to_excel(writer,sheet_name="Manual Decisions",index=False); meta.to_excel(writer,sheet_name="Run Metadata",index=False); events.to_excel(writer,sheet_name="Run Events",index=False); sources.to_excel(writer,sheet_name="Source Records",index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
            for col in ws.columns:
                letter=col[0].column_letter; width=min(max(max(len(str(c.value or "")) for c in col)+2,12),48); ws.column_dimensions[letter].width=width
                if col[0].value in {"amount_a","amount_b","amount_difference","net_amount_difference","amount_total","matched_amount_a","matched_amount_b","matched_amount_difference","system_a_valid_amount","system_b_valid_amount","system_a_minus_b","system_a_amount","system_b_amount","gross_amount_difference"}:
                    for cell in col[1:]: cell.number_format='#,##0.00;[Red](#,##0.00);-'
    return out.getvalue()
