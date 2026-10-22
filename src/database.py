import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from .config import DEFAULT_DB
from .reconciliation import ReconciliationOutput

def connect(path: str | Path = DEFAULT_DB):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db=sqlite3.connect(str(path)); db.row_factory=sqlite3.Row; db.execute("PRAGMA foreign_keys=ON"); return db

def initialize(path: str | Path = DEFAULT_DB):
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS reconciliation_runs(run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, source_a_name TEXT, source_b_name TEXT, config_json TEXT NOT NULL, summary_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_transactions(source_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES reconciliation_runs(run_id), side TEXT NOT NULL, source_row INTEGER, transaction_id TEXT, transaction_date TEXT, settlement_date TEXT, amount REAL, currency TEXT, transaction_type TEXT, status TEXT, source_system TEXT, validation_errors TEXT);
        CREATE TABLE IF NOT EXISTS reconciliation_results(result_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES reconciliation_runs(run_id), transaction_id TEXT, outcome TEXT NOT NULL, system_a_count INTEGER NOT NULL, system_b_count INTEGER NOT NULL, amount_a REAL, amount_b REAL, amount_difference REAL);
        CREATE TABLE IF NOT EXISTS exceptions(exception_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES reconciliation_runs(run_id), transaction_id TEXT, issue_type TEXT NOT NULL, source_side TEXT, system_a_row INTEGER, system_b_row INTEGER, details TEXT NOT NULL, severity TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS exception_resolutions(resolution_id INTEGER PRIMARY KEY, exception_id INTEGER NOT NULL REFERENCES exceptions(exception_id), status TEXT NOT NULL CHECK(status IN ('open','under investigation','resolved','accepted')), justification TEXT NOT NULL, changed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS run_summaries(run_id TEXT PRIMARY KEY REFERENCES reconciliation_runs(run_id), summary_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS run_events(event_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES reconciliation_runs(run_id), event_type TEXT NOT NULL, details TEXT NOT NULL, changed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS manual_match_decisions(decision_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES reconciliation_runs(run_id), transaction_id TEXT, system_a_row INTEGER NOT NULL, system_b_row INTEGER NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('confirmed','rejected')), justification TEXT NOT NULL, changed_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_result_run ON reconciliation_results(run_id); CREATE INDEX IF NOT EXISTS idx_exception_run ON exceptions(run_id);
        CREATE INDEX IF NOT EXISTS idx_exception_tx ON exceptions(transaction_id);
        CREATE INDEX IF NOT EXISTS idx_result_run_tx ON reconciliation_results(run_id,transaction_id);
        CREATE INDEX IF NOT EXISTS idx_source_run_side_tx ON source_transactions(run_id,side,transaction_id);
        CREATE INDEX IF NOT EXISTS idx_source_run_side_row ON source_transactions(run_id,side,source_row);
        ''')
        columns={r[1] for r in db.execute("PRAGMA table_info(reconciliation_runs)")}
        if "processing_status" not in columns:
            db.execute("ALTER TABLE reconciliation_runs ADD COLUMN processing_status TEXT NOT NULL DEFAULT 'completed'")

def start_run(source_names=("system_a.csv","system_b.csv"), config=None, path: str | Path = DEFAULT_DB) -> str:
    initialize(path); run_id=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        db.execute("INSERT INTO reconciliation_runs(run_id,created_at,source_a_name,source_b_name,config_json,summary_json,processing_status) VALUES(?,?,?,?,?,?,?)",(run_id,now,*source_names,json.dumps(config or {}),"{}","processing"))
        db.execute("INSERT INTO run_events(run_id,event_type,details,changed_at) VALUES(?,?,?,?)",(run_id,"started","Reconciliation run started",now))
    return run_id

def fail_run(run_id: str, message: str, path: str | Path = DEFAULT_DB):
    now=datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        db.execute("UPDATE reconciliation_runs SET processing_status='failed' WHERE run_id=?",(run_id,))
        db.execute("INSERT INTO run_events(run_id,event_type,details,changed_at) VALUES(?,?,?,?)",(run_id,"failed",message,now))

def complete_run(run_id: str, output: ReconciliationOutput, frame_a: pd.DataFrame, frame_b: pd.DataFrame, path: str | Path = DEFAULT_DB):
    initialize(path)
    now=datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        run=db.execute("SELECT processing_status FROM reconciliation_runs WHERE run_id=?",(run_id,)).fetchone()
        if not run: raise ValueError(f"Run {run_id} was not found")
        if run[0] != "processing": raise ValueError(f"Run {run_id} is not processing")
        for side,frame in (("A",frame_a),("B",frame_b)):
            from .validation import validate_frame
            val=validate_frame(frame,"SYSTEM_"+side)
            rows=[]
            full=pd.concat([val.accepted.assign(validation_errors=""),val.rejected],ignore_index=True).sort_values("source_row")
            for _,r in full.iterrows(): rows.append((run_id,side,int(r.source_row),r.get("transaction_id"),r.get("transaction_date"),r.get("settlement_date"),None if pd.isna(r.get("amount")) else float(r.get("amount")),r.get("currency"),r.get("transaction_type"),r.get("status"),r.get("source_system"),r.get("validation_errors","")))
            db.executemany("INSERT INTO source_transactions(run_id,side,source_row,transaction_id,transaction_date,settlement_date,amount,currency,transaction_type,status,source_system,validation_errors) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",rows)
        db.executemany("INSERT INTO reconciliation_results(run_id,transaction_id,outcome,system_a_count,system_b_count,amount_a,amount_b,amount_difference) VALUES(?,?,?,?,?,?,?,?)",[(run_id,r.transaction_id,r.outcome,int(r.system_a_count),int(r.system_b_count),r.amount_a,r.amount_b,r.amount_difference) for r in output.results.itertuples(index=False)])
        db.executemany("INSERT INTO exceptions(run_id,transaction_id,issue_type,source_side,system_a_row,system_b_row,details,severity) VALUES(?,?,?,?,?,?,?,?)",[(run_id,r.transaction_id,r.issue_type,r.source_side,r.system_a_row,r.system_b_row,r.details,r.severity) for r in output.exceptions.itertuples(index=False)])
        db.execute("INSERT INTO run_summaries VALUES(?,?)",(run_id,json.dumps(output.summary)))
        db.execute("UPDATE reconciliation_runs SET summary_json=?,processing_status='completed' WHERE run_id=?",(json.dumps(output.summary),run_id))
        db.execute("INSERT INTO run_events(run_id,event_type,details,changed_at) VALUES(?,?,?,?)",(run_id,"completed",f"Stored {len(output.results)} result keys and {len(output.exceptions)} exceptions",now))

def save_run(output: ReconciliationOutput, frame_a: pd.DataFrame, frame_b: pd.DataFrame, config: dict | None=None, source_names=("system_a.csv","system_b.csv"), path: str | Path = DEFAULT_DB) -> str:
    run_id=start_run(source_names,config,path)
    complete_run(run_id,output,frame_a,frame_b,path)
    return run_id

def list_runs(path=DEFAULT_DB):
    initialize(path)
    with connect(path) as db: return pd.read_sql_query("SELECT run_id,created_at,source_a_name,source_b_name,summary_json,processing_status FROM reconciliation_runs ORDER BY created_at DESC",db)

def record_manual_match(run_id: str, transaction_id: str, a_row: int, b_row: int, decision: str, justification: str, path=DEFAULT_DB):
    if decision not in {"confirmed","rejected"}: raise ValueError("Decision must be confirmed or rejected")
    if not justification.strip(): raise ValueError("A justification is required")
    with connect(path) as db:
        if not db.execute("SELECT 1 FROM source_transactions WHERE run_id=? AND side='A' AND source_row=?",(run_id,a_row)).fetchone() or not db.execute("SELECT 1 FROM source_transactions WHERE run_id=? AND side='B' AND source_row=?",(run_id,b_row)).fetchone():
            raise ValueError("Both source rows must belong to this run")
        now=datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO manual_match_decisions(run_id,transaction_id,system_a_row,system_b_row,decision,justification,changed_at) VALUES(?,?,?,?,?,?,?)",(run_id,transaction_id,a_row,b_row,decision,justification.strip(),now))
        db.execute("INSERT INTO run_events(run_id,event_type,details,changed_at) VALUES(?,?,?,?)",(run_id,"manual_match_"+decision,f"{transaction_id}: A row {a_row}, B row {b_row}; {justification.strip()}",now))

def resolution_history(exception_id: int,path=DEFAULT_DB):
    return table(path,"SELECT resolution_id,status,justification,changed_at FROM exception_resolutions WHERE exception_id=? ORDER BY changed_at,resolution_id",(exception_id,))

def run_comparison(run_id: str, other_run_id: str, path=DEFAULT_DB):
    counts=table(path,"SELECT run_id,outcome,COUNT(*) result_count FROM reconciliation_results WHERE run_id IN (?,?) GROUP BY run_id,outcome",(run_id,other_run_id))
    issues=table(path,"SELECT run_id,issue_type,COUNT(*) issue_count FROM exceptions WHERE run_id IN (?,?) GROUP BY run_id,issue_type",(run_id,other_run_id))
    amounts=table(path,"""SELECT r.run_id,r.outcome,CASE WHEN a.currency IS NOT NULL AND b.currency IS NOT NULL AND a.currency<>b.currency THEN a.currency||' / '||b.currency ELSE COALESCE(a.currency,b.currency,'ambiguous') END currency,
        ROUND(SUM(COALESCE(r.amount_difference,0)),2) amount_difference FROM reconciliation_results r
        LEFT JOIN source_transactions a ON a.run_id=r.run_id AND a.side='A' AND a.transaction_id=r.transaction_id AND r.system_a_count=1
        LEFT JOIN source_transactions b ON b.run_id=r.run_id AND b.side='B' AND b.transaction_id=r.transaction_id AND r.system_b_count=1
        WHERE r.run_id IN (?,?) GROUP BY r.run_id,r.outcome,CASE WHEN a.currency IS NOT NULL AND b.currency IS NOT NULL AND a.currency<>b.currency THEN a.currency||' / '||b.currency ELSE COALESCE(a.currency,b.currency,'ambiguous') END""",(run_id,other_run_id))
    gross=table(path,"""SELECT run_id,currency,ROUND(SUM(CASE WHEN side='A' THEN amount ELSE -amount END),2) net_source_difference
        FROM source_transactions WHERE run_id IN (?,?) AND validation_errors='' GROUP BY run_id,currency""",(run_id,other_run_id))
    rows=[]
    for category in sorted(set(counts.outcome)):
        one=counts[(counts.run_id==run_id)&(counts.outcome==category)]; two=counts[(counts.run_id==other_run_id)&(counts.outcome==category)]
        rows.append({"section":"outcome","category":category,"run_one":int(one.result_count.iloc[0]) if len(one) else 0,"run_two":int(two.result_count.iloc[0]) if len(two) else 0,"currency":None,"amount_one":None,"amount_two":None})
    for category in sorted(set(issues.issue_type)):
        one=issues[(issues.run_id==run_id)&(issues.issue_type==category)]; two=issues[(issues.run_id==other_run_id)&(issues.issue_type==category)]
        rows.append({"section":"issue","category":category,"run_one":int(one.issue_count.iloc[0]) if len(one) else 0,"run_two":int(two.issue_count.iloc[0]) if len(two) else 0,"currency":None,"amount_one":None,"amount_two":None})
    for outcome,currency in sorted(set(zip(amounts.outcome,amounts.currency))):
        one=amounts[(amounts.run_id==run_id)&(amounts.outcome==outcome)&(amounts.currency==currency)]; two=amounts[(amounts.run_id==other_run_id)&(amounts.outcome==outcome)&(amounts.currency==currency)]
        rows.append({"section":"amount_difference","category":outcome,"run_one":None,"run_two":None,"currency":currency,"amount_one":float(one.amount_difference.iloc[0]) if len(one) else 0.0,"amount_two":float(two.amount_difference.iloc[0]) if len(two) else 0.0})
    for currency in sorted(set(gross.currency)):
        one=gross[(gross.run_id==run_id)&(gross.currency==currency)]; two=gross[(gross.run_id==other_run_id)&(gross.currency==currency)]
        rows.append({"section":"gross_source_difference","category":"System A minus System B","run_one":None,"run_two":None,"currency":currency,"amount_one":float(one.net_source_difference.iloc[0]) if len(one) else 0.0,"amount_two":float(two.net_source_difference.iloc[0]) if len(two) else 0.0})
    return pd.DataFrame(rows,columns=["section","category","run_one","run_two","currency","amount_one","amount_two"])

def table(path, sql, params=()):
    with connect(path) as db: return pd.read_sql_query(sql,db,params=params)

def resolve_exception(exception_id: int,status: str,justification: str,path=DEFAULT_DB):
    if status not in {"open","under investigation","resolved","accepted"}: raise ValueError("Unsupported resolution status")
    if not justification.strip(): raise ValueError("A justification is required")
    initialize(path)
    with connect(path) as db:
        if not db.execute("SELECT 1 FROM exceptions WHERE exception_id=?",(exception_id,)).fetchone(): raise ValueError(f"Exception {exception_id} was not found")
        db.execute("INSERT INTO exception_resolutions(exception_id,status,justification,changed_at) VALUES(?,?,?,?)",(exception_id,status,justification.strip(),datetime.now(timezone.utc).isoformat()))

