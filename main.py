import argparse
from pathlib import Path
from src.config import DEFAULT_DB, ReconciliationConfig
from src.data_generator import generate_demo_data
from src.validation import read_csv_upload
from src.reconciliation import reconcile
from src.database import initialize, start_run, complete_run, fail_run

def main():
    p=argparse.ArgumentParser(description="Local financial reconciliation controls engine")
    sub=p.add_subparsers(dest="command",required=True)
    init=sub.add_parser("init-db"); init.add_argument("--db",default=str(DEFAULT_DB))
    gen=sub.add_parser("generate-demo"); gen.add_argument("--rows",type=int,default=20000); gen.add_argument("--seed",type=int,default=2026); gen.add_argument("--out",default="data/demo")
    run=sub.add_parser("reconcile"); run.add_argument("--a",required=True); run.add_argument("--b",required=True); run.add_argument("--db",default=str(DEFAULT_DB)); run.add_argument("--amount-tolerance",type=float,default=.01); run.add_argument("--date-tolerance-days",type=int,default=0)
    args=p.parse_args()
    if args.command=="init-db": initialize(args.db); print(f"Database initialized: {args.db}"); return
    if args.command=="generate-demo":
        a,b=generate_demo_data(args.rows,args.seed); out=Path(args.out); out.mkdir(parents=True,exist_ok=True); a.to_csv(out/"system_a.csv",index=False); b.to_csv(out/"system_b.csv",index=False); print(f"Wrote {len(a):,} System A and {len(b):,} System B rows to {out}"); return
    a=read_csv_upload(Path(args.a).read_bytes(),Path(args.a).name,"SYSTEM_A"); b=read_csv_upload(Path(args.b).read_bytes(),Path(args.b).name,"SYSTEM_B")
    cfg=ReconciliationConfig(args.amount_tolerance,args.date_tolerance_days); config={"amount_tolerance":cfg.amount_tolerance,"date_tolerance_days":cfg.date_tolerance_days}
    run_id=start_run((Path(args.a).name,Path(args.b).name),config,args.db)
    try:
        result=reconcile(a,b,cfg)
        complete_run(run_id,result,a,b,args.db)
    except Exception as exc:
        fail_run(run_id,str(exc),args.db)
        raise
    print(f"Run {run_id}: {result.summary['matched_keys']:,}/{result.summary['result_keys']:,} matched keys; {result.summary['exception_count']:,} exceptions; record match rate {result.summary['record_match_rate']:.2%}")

if __name__=="__main__": main()
