import json
import sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st

from src.config import DEFAULT_DB, ReconciliationConfig
from src.data_generator import generate_demo_data
from src.validation import read_csv_upload
from src.reconciliation import reconcile
from src.database import (initialize, start_run, complete_run, fail_run, list_runs,
                          table, resolve_exception, resolution_history,
                          record_manual_match, run_comparison)
from src.analytics import outcome_summary, exception_summary, source_controls_by_dimension
from src.investigation import candidate_matches, source_totals_by_currency, matched_controls_by_currency, unresolved_controls_by_currency
from src.reporting import csv_bytes, excel_bytes, run_frames

st.set_page_config(page_title="Financial Reconciliation Controls", page_icon="📊", layout="wide")
def persistent_workspace_database():
    data_dir=Path(DEFAULT_DB).parent
    pointer=data_dir/".streamlit_workspace"
    if pointer.exists():
        name=pointer.read_text(encoding="utf-8").strip()
        candidate=data_dir/name
        if candidate.parent.resolve()==data_dir.resolve() and candidate.exists(): return candidate
    candidates=[]
    for candidate in [Path(DEFAULT_DB),*data_dir.glob("session_*.sqlite3")]:
        if not candidate.exists(): continue
        try:
            db=sqlite3.connect(f"file:{candidate.resolve().as_posix()}?mode=ro",uri=True)
            row=db.execute("SELECT MAX(created_at) FROM reconciliation_runs").fetchone()
            db.close()
            if row and row[0]: candidates.append((row[0],candidate))
        except sqlite3.Error:
            continue
    selected=max(candidates,key=lambda item:item[0])[1] if candidates else Path(DEFAULT_DB)
    pointer.write_text(selected.name,encoding="utf-8")
    return selected

DEFAULT_DB=persistent_workspace_database()
st.title("Financial Reconciliation & Controls Engine")
st.caption("Synthetic demonstration data · Local SQLite · Traceable investigation")
initialize(DEFAULT_DB)
overview_tab, workspace_tab, exceptions_tab, history_tab, reports_tab = st.tabs(
    ["Overview", "Reconciliation Workspace", "Exception Investigation", "Run History", "Reports"]
)

def completed_runs():
    runs = list_runs()
    return runs[runs.processing_status.eq("completed")].copy()

all_runs=completed_runs()
active_run_id=st.session_state.get("active_run_id")
if active_run_id not in set(all_runs.run_id):
    active_run_id=None
    st.session_state.pop("active_run_id",None)

def source_pair(run_id, transaction_id):
    if pd.isna(transaction_id):
        return (table(DEFAULT_DB, "SELECT * FROM source_transactions WHERE run_id=? AND side='A' AND transaction_id IS NULL", (run_id,)),
                table(DEFAULT_DB, "SELECT * FROM source_transactions WHERE run_id=? AND side='B' AND transaction_id IS NULL", (run_id,)))
    return (table(DEFAULT_DB, "SELECT * FROM source_transactions WHERE run_id=? AND side='A' AND transaction_id=? ORDER BY source_row", (run_id, transaction_id)),
            table(DEFAULT_DB, "SELECT * FROM source_transactions WHERE run_id=? AND side='B' AND transaction_id=? ORDER BY source_row", (run_id, transaction_id)))

def show_comparison(a_rows, b_rows):
    fields = ["transaction_id", "transaction_date", "settlement_date", "amount", "currency", "transaction_type", "status", "source_system", "validation_errors"]
    if len(a_rows) > 1 or len(b_rows) > 1:
        st.warning(f"Ambiguous source key: {len(a_rows)} System A rows and {len(b_rows)} System B rows. No amounts are paired automatically.")
        left, right = st.columns(2)
        with left: st.markdown("**System A source rows**"); st.dataframe(a_rows[fields], width="stretch", hide_index=True)
        with right: st.markdown("**System B source rows**"); st.dataframe(b_rows[fields], width="stretch", hide_index=True)
        return
    a = a_rows.iloc[0] if len(a_rows) else None
    b = b_rows.iloc[0] if len(b_rows) else None
    comparisons=[]
    for field in fields:
        av = a[field] if a is not None else None
        bv = b[field] if b is not None else None
        av = "— missing —" if pd.isna(av) else str(av)
        bv = "— missing —" if pd.isna(bv) else str(bv)
        comparisons.append({"Field":field,"System A":av,"System B":bv,"Check":"same" if av==bv else "different/missing"})
    st.dataframe(pd.DataFrame(comparisons), width="stretch", hide_index=True)

with overview_tab:
    st.subheader("Control overview")
    if active_run_id is None:
        st.info("No reconciliation is open. Run a reconciliation in the Workspace, or open a saved run from Run History.")
    else:
        run_id=active_run_id
        summary=json.loads(all_runs.loc[all_runs.run_id.eq(run_id),"summary_json"].iloc[0])
        outcomes=outcome_summary(run_id,DEFAULT_DB)
        metrics=st.columns(4)
        metrics[0].metric("System A source rows",f"{summary['source_a_rows']:,}")
        metrics[1].metric("System B source rows",f"{summary['source_b_rows']:,}")
        metrics[2].metric("Matched keys",f"{summary['matched_keys']:,}")
        metrics[3].metric("Record match rate",f"{summary['record_match_rate']:.1%}")
        st.caption(f"Active run: {run_id}")
        st.caption("Match rate is matched unique result keys divided by all result keys. It is a record-count control, separate from monetary controls.")
        st.markdown("**Valid source totals by currency**")
        st.dataframe(source_totals_by_currency(run_id,DEFAULT_DB),width="stretch",hide_index=True)
        st.markdown("**Matched transaction controls by currency**")
        st.dataframe(matched_controls_by_currency(run_id,DEFAULT_DB),width="stretch",hide_index=True)
        st.markdown("**Unresolved amount discrepancies by currency**")
        st.dataframe(unresolved_controls_by_currency(run_id,DEFAULT_DB),width="stretch",hide_index=True)
        dimension=st.selectbox("Break source controls down by",["Date","Transaction type","Status"],key="overview_dimension")
        st.dataframe(source_controls_by_dimension(run_id,dimension,DEFAULT_DB),width="stretch",hide_index=True)
        left,right=st.columns(2)
        with left: st.markdown("**Result keys by outcome**"); st.dataframe(outcomes,width="stretch",hide_index=True)
        with right: st.markdown("**Issue register by category**"); st.dataframe(exception_summary(run_id,DEFAULT_DB),width="stretch",hide_index=True)

with workspace_tab:
    st.subheader("Import ledgers and run controls")
    with st.expander("Import data",expanded=True):
        st.caption("Clear loaded files for your next run. Saved reconciliation runs remain available in Run History.")
        if st.button("Clear loaded files for the next run",key="clear_loaded_data"):
            for key in ("uploaded","demo","source_a_upload","source_b_upload"):
                st.session_state.pop(key,None)
            st.rerun()
        if st.button("Generate synthetic demonstration data",key="generate_demo"):
            st.session_state.demo=generate_demo_data()
            st.success("Generated deterministic synthetic System A and System B ledgers (seed 2026).")
        use_demo=False
        if "demo" in st.session_state:
            use_demo=st.checkbox("Use generated synthetic demonstration data",value=True)
        upload_a=st.file_uploader("System A CSV",type="csv",key="source_a_upload")
        upload_b=st.file_uploader("System B CSV",type="csv",key="source_b_upload")
        if use_demo:
            a,b=st.session_state.demo
            st.session_state.uploaded=(a,b,"demo_system_a.csv","demo_system_b.csv",int(a.memory_usage(deep=True).sum()),int(b.memory_usage(deep=True).sum()))
        elif upload_a and upload_b:
            try:
                a=read_csv_upload(upload_a.getvalue(),upload_a.name,"SYSTEM_A")
                b=read_csv_upload(upload_b.getvalue(),upload_b.name,"SYSTEM_B")
                st.session_state.uploaded=(a,b,upload_a.name,upload_b.name,upload_a.size,upload_b.size)
                st.success("Both files parsed and required headers are present.")
            except ValueError as exc: st.error(str(exc))
        if "uploaded" in st.session_state:
            a,b,name_a,name_b,size_a,size_b=st.session_state.uploaded
            st.write(f"A: {name_a} · {size_a:,} bytes · {len(a):,} rows | B: {name_b} · {size_b:,} bytes · {len(b):,} rows")
    st.markdown("**Comparison tolerances**")
    c1,c2=st.columns(2)
    amount_tolerance=c1.number_input("Amount tolerance",min_value=0.0,value=.01,step=.01,format="%.2f")
    date_tolerance=c2.number_input("Date tolerance (days)",min_value=0,value=0,step=1)
    if st.button("Run reconciliation",type="primary"):
        if "uploaded" not in st.session_state: st.error("Import two ledgers or select synthetic demo data first.")
        else:
            a,b,name_a,name_b,_,_=st.session_state.uploaded
            cfg={"amount_tolerance":amount_tolerance,"date_tolerance_days":date_tolerance}
            run_id=start_run((name_a,name_b),cfg,DEFAULT_DB)
            try:
                with st.status(f"Processing run {run_id}…",expanded=True):
                    output=reconcile(a,b,ReconciliationConfig(amount_tolerance,date_tolerance))
                    complete_run(run_id,output,a,b,DEFAULT_DB)
                st.session_state.active_run_id=run_id
                st.session_state.workspace_run=run_id
                st.success(f"Run completed: {run_id}")
                st.rerun()
            except Exception as exc:
                fail_run(run_id,str(exc),DEFAULT_DB)
                st.error(f"Run {run_id} failed: {exc}")
    if active_run_id is None:
        st.info("No run is open. Reconcile these files, or select a saved run in Run History to inspect it here.")
    else:
        run_id=active_run_id
        st.caption(f"Showing active run: {run_id}")
        results=table(DEFAULT_DB,"SELECT transaction_id,outcome,system_a_count,system_b_count,amount_a,amount_b,amount_difference FROM reconciliation_results WHERE run_id=? ORDER BY transaction_id",(run_id,))
        st.dataframe(results,width="stretch",hide_index=True)
        if not results.empty:
            options=results.transaction_id.fillna("(missing transaction ID)").astype(str).tolist()
            selected=st.selectbox("Select result to investigate",options,key="workspace_result")
            tx_id=None if selected=="(missing transaction ID)" else selected
            selected_result=results[results.transaction_id.isna()] if tx_id is None else results[results.transaction_id.astype(str).eq(tx_id)]
            if not selected_result.empty:
                result=selected_result.iloc[0]
                a_rows,b_rows=source_pair(run_id,tx_id)
                st.markdown(f"**Outcome:** `{result.outcome}`")
                show_comparison(a_rows,b_rows)
                rules=table(DEFAULT_DB,"SELECT issue_type,details FROM exceptions WHERE run_id=? AND (transaction_id=? OR (? IS NULL AND transaction_id IS NULL)) ORDER BY exception_id",(run_id,tx_id,tx_id))
                if rules.empty: st.info("This result has no exception reasons. Unique keys matched within configured tolerances.")
                else:
                    st.markdown("**Applicable findings and rule explanations**")
                    st.dataframe(rules,width="stretch",hide_index=True)
                if result.outcome in {"missing_in_a","missing_in_b"}:
                    st.markdown("**Deterministic candidate suggestions**")
                    suggestions=candidate_matches(run_id,str(tx_id),DEFAULT_DB)
                    if not suggestions: st.info("No candidate met the documented currency, transaction type, amount, and date checks.")
                    else:
                        suggestions_df=pd.DataFrame(suggestions).drop(columns=["system_a_row","system_b_row"])
                        st.dataframe(suggestions_df,width="stretch",hide_index=True)
                        chosen=st.selectbox("Candidate source row",range(len(suggestions)),format_func=lambda i:f"{suggestions[i]['transaction_id']} · row {suggestions[i]['source_row']}",key=f"candidate_{run_id}_{tx_id}")
                        candidate=suggestions[chosen]
                        if candidate["ambiguous"]: st.warning("Several candidates meet the suggestion rules. This is ambiguous and requires explicit analyst review.")
                        justification=st.text_input("Manual decision justification",key=f"manual_reason_{run_id}_{tx_id}")
                        if st.button("Confirm this candidate as a manual investigation decision",key=f"confirm_{run_id}_{tx_id}"):
                            try: record_manual_match(run_id,str(tx_id),candidate["system_a_row"],candidate["system_b_row"],"confirmed",justification,DEFAULT_DB); st.success("Manual decision recorded in audit history. Original reconciliation results remain unchanged.")
                            except ValueError as exc: st.error(str(exc))
                        if st.button("Reject this candidate",key=f"reject_{run_id}_{tx_id}"):
                            try: record_manual_match(run_id,str(tx_id),candidate["system_a_row"],candidate["system_b_row"],"rejected",justification,DEFAULT_DB); st.success("Rejection decision recorded in audit history.")
                            except ValueError as exc: st.error(str(exc))

with exceptions_tab:
    st.subheader("Exception investigation centre")
    if active_run_id is None: st.info("No run is open. Select a saved run in Run History, or run a reconciliation in the Workspace.")
    else:
        run_id=active_run_id
        st.caption(f"Showing exceptions for active run: {run_id}")
        issue_types=table(DEFAULT_DB,"SELECT DISTINCT issue_type FROM exceptions WHERE run_id=? ORDER BY issue_type",(run_id,)).issue_type.tolist()
        c1,c2,c3=st.columns(3)
        issue=c1.selectbox("Issue type",["All"]+issue_types)
        tx_search=c2.text_input("Transaction ID contains")
        resolution=c3.selectbox("Resolution status",["All","open","under investigation","resolved","accepted"])
        c4,c5=st.columns(2)
        date_filter=c4.text_input("Source transaction date (YYYY-MM-DD)")
        amount_min=c5.number_input("Minimum absolute amount difference",min_value=0.0,value=0.0,step=.01)
        sql="""SELECT e.exception_id,e.transaction_id,e.issue_type,e.source_side,e.details,e.severity,
          COALESCE(latest.status,'open') resolution_status,COALESCE(a.transaction_date,b.transaction_date) source_date,
          r.amount_difference FROM exceptions e
          LEFT JOIN source_transactions a ON a.run_id=e.run_id AND a.side='A' AND a.source_row=e.system_a_row
          LEFT JOIN source_transactions b ON b.run_id=e.run_id AND b.side='B' AND b.source_row=e.system_b_row
          LEFT JOIN reconciliation_results r ON r.run_id=e.run_id AND r.transaction_id=e.transaction_id
          LEFT JOIN (SELECT exception_id,status,ROW_NUMBER() OVER(PARTITION BY exception_id ORDER BY changed_at DESC,resolution_id DESC) rn FROM exception_resolutions) latest ON latest.exception_id=e.exception_id AND latest.rn=1
          WHERE e.run_id=?"""
        params=[run_id]
        if issue!="All": sql+=" AND e.issue_type=?"; params.append(issue)
        if tx_search: sql+=" AND COALESCE(e.transaction_id,'') LIKE ?"; params.append(f"%{tx_search}%")
        if resolution!="All": sql+=" AND COALESCE(latest.status,'open')=?"; params.append(resolution)
        if date_filter: sql+=" AND COALESCE(a.transaction_date,b.transaction_date)=?"; params.append(date_filter)
        if amount_min>0: sql+=" AND ABS(COALESCE(r.amount_difference,0))>=?"; params.append(amount_min)
        exceptions=table(DEFAULT_DB,sql+" ORDER BY e.exception_id",tuple(params))
        st.dataframe(exceptions,width="stretch",hide_index=True)
        if not exceptions.empty:
            exception_id=st.selectbox("Exception to review",exceptions.exception_id.tolist())
            record=table(DEFAULT_DB,"SELECT transaction_id FROM exceptions WHERE exception_id=?",(exception_id,)).iloc[0]
            if pd.notna(record.transaction_id):
                issues=table(DEFAULT_DB,"SELECT issue_type,details,severity FROM exceptions WHERE run_id=? AND transaction_id=? ORDER BY exception_id",(run_id,record.transaction_id))
                st.markdown("**All issue reasons for this transaction**")
                st.dataframe(issues,width="stretch",hide_index=True)
            st.markdown("**Resolution history**")
            st.dataframe(resolution_history(int(exception_id),DEFAULT_DB),width="stretch",hide_index=True)
            with st.form("exception_resolution_form"):
                state=st.selectbox("Set status",["open","under investigation","resolved","accepted"])
                justification=st.text_area("Investigation note / justification (required)")
                submitted=st.form_submit_button("Append resolution update")
                if submitted:
                    try: resolve_exception(int(exception_id),state,justification,DEFAULT_DB); st.success("Resolution event appended. Source and reconciliation records are unchanged.")
                    except ValueError as exc: st.error(str(exc))

with history_tab:
    st.subheader("Reconciliation run history")
    runs=list_runs()
    if runs.empty: st.info("No saved runs yet. Reconcile two ledgers in the Workspace to create the first run.")
    else:
        completed=runs[runs.processing_status.eq("completed")]
        st.caption("Saved results appear in the other tabs only after you open a run here.")
        selected_history_run=st.selectbox("Select a saved run to open across the app",completed.run_id.tolist(),index=None,placeholder="Choose a reconciliation run",key="history_open_run") if not completed.empty else None
        if st.button("Open selected run across all tabs",key="open_history_run",disabled=selected_history_run is None):
            st.session_state.active_run_id=selected_history_run
            st.rerun()
        if active_run_id is not None:
            st.success(f"Active run across all tabs: {active_run_id}")
            if st.button("Close this run and return to a blank view",key="close_active_run"):
                st.session_state.pop("active_run_id",None)
                st.rerun()
        display=runs.copy()
        display["source_a_rows"]=display.summary_json.map(lambda x:json.loads(x).get("source_a_rows"))
        display["source_b_rows"]=display.summary_json.map(lambda x:json.loads(x).get("source_b_rows"))
        display["matched_keys"]=display.summary_json.map(lambda x:json.loads(x).get("matched_keys"))
        display["exception_count"]=display.summary_json.map(lambda x:json.loads(x).get("exception_count"))
        st.dataframe(display.drop(columns="summary_json"),width="stretch",hide_index=True)
        if active_run_id is not None and len(completed)>=2:
            first,second=st.columns(2)
            run_one=first.selectbox("Earlier / baseline run",completed.run_id.tolist(),key="compare_one")
            run_two=second.selectbox("Comparison run",completed.run_id.tolist(),index=1,key="compare_two")
            if run_one!=run_two:
                st.markdown("**Outcome, issue-count, and amount-difference changes (amounts remain separated by currency)**")
                st.dataframe(run_comparison(run_one,run_two,DEFAULT_DB),width="stretch",hide_index=True)
            else: st.info("Choose two different runs to compare their immutable snapshots.")
        if active_run_id is not None:
            events=table(DEFAULT_DB,"SELECT run_id,event_type,details,changed_at FROM run_events WHERE run_id=? ORDER BY changed_at DESC",(active_run_id,))
            with st.expander("Audit events for the active run"): st.dataframe(events,width="stretch",hide_index=True)

with reports_tab:
    st.subheader("Detailed reports and exports")
    if active_run_id is None: st.info("No run is open. Select a saved run in Run History, or run a reconciliation in the Workspace.")
    else:
        run_id=active_run_id
        st.caption(f"Reports for active run: {run_id}")
        results,exceptions,_=run_frames(run_id,DEFAULT_DB)
        st.download_button("Download reconciliation results CSV",csv_bytes(results),"reconciliation_results.csv","text/csv")
        st.download_button("Download exception register CSV",csv_bytes(exceptions),"exception_register.csv","text/csv")
        # Workbook construction reads every source row and formats each Excel
        # column. Keep that work behind an explicit click so initial page load
        # stays responsive (Streamlit executes all tab bodies on every rerun).
        workbook_key=f"report_workbook_{run_id}"
        if st.button("Prepare detailed Excel workbook",key=f"prepare_{run_id}"):
            with st.spinner("Building the detailed workbook from saved run data…"):
                st.session_state[workbook_key]=excel_bytes(run_id,DEFAULT_DB)
        if workbook_key in st.session_state:
            st.download_button("Download detailed Excel workbook",st.session_state[workbook_key],"reconciliation_report.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.caption("The detailed workbook is built when requested so it does not delay app startup.")
        st.caption("Workbook totals are sourced from this run's persisted source and result tables. Resolution and manual-decision history are included separately.")
