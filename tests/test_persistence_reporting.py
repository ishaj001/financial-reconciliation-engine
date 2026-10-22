import pandas as pd
from src.reconciliation import reconcile
from src.database import save_run,table,resolve_exception,resolution_history
from src.reporting import excel_bytes,csv_bytes

COLS=["transaction_id","transaction_date","settlement_date","amount","currency","transaction_type","status","source_system"]
def test_run_persistence_resolution_and_exports(tmp_path):
    a=pd.DataFrame([["x","2025-01-01","2025-01-02",10,"USD","purchase","settled","A"]],columns=COLS)
    b=pd.DataFrame([["x","2025-01-01","2025-01-02",12,"USD","purchase","settled","B"]],columns=COLS)
    path=tmp_path/"test.sqlite"; out=reconcile(a,b); run=save_run(out,a,b,path=path)
    assert out.summary["source_a_valid_amount"]==10 and out.summary["source_b_valid_amount"]==12
    assert table(path,"SELECT COUNT(*) n FROM reconciliation_results WHERE run_id=?",(run,)).iloc[0].n==1
    ex=table(path,"SELECT exception_id FROM exceptions WHERE run_id=?",(run,)); eid=int(ex.iloc[0,0])
    resolve_exception(eid,"resolved","Confirmed and booked separately",path)
    resolve_exception(eid,"accepted","Approved by reviewer",path)
    assert table(path,"SELECT COUNT(*) n FROM exception_resolutions WHERE exception_id=?",(eid,)).iloc[0].n==2
    assert resolution_history(eid,path).status.tolist()==["resolved","accepted"]
    assert len(csv_bytes(out.results))>0 and excel_bytes(run,path)[:2]==b"PK"
    second=save_run(out,a,b,path=path)
    assert second!=run and table(path,"SELECT COUNT(*) n FROM reconciliation_runs").iloc[0].n==2
