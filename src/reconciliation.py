from dataclasses import dataclass
from datetime import date
import pandas as pd
from .config import ReconciliationConfig
from .validation import validate_frame

@dataclass
class ReconciliationOutput:
    results: pd.DataFrame
    exceptions: pd.DataFrame
    rejected: pd.DataFrame
    summary: dict

def reconcile(frame_a: pd.DataFrame, frame_b: pd.DataFrame, config: ReconciliationConfig | None = None) -> ReconciliationOutput:
    config = config or ReconciliationConfig()
    va, vb = validate_frame(frame_a, "SYSTEM_A"), validate_frame(frame_b, "SYSTEM_B")
    a, b = va.accepted.copy(), vb.accepted.copy()
    rejected = pd.concat([va.rejected.assign(source_side="A"), vb.rejected.assign(source_side="B")], ignore_index=True)
    issues: list[dict] = []; rows: list[dict] = []
    def add_issue(key, typ, side, details, aid=None, bid=None, severity="medium"):
        issues.append({"transaction_id":key,"issue_type":typ,"source_side":side,"system_a_row":aid,"system_b_row":bid,"details":details,"severity":severity})
    # Rejected values remain in the exception register and cannot enter joins.
    for _, r in rejected.iterrows():
        for reason in str(r.validation_errors).split(";"):
            if reason: add_issue(r.transaction_id or None, "validation:"+reason, r.source_side, f"Rejected source row {r.source_row}", int(r.source_row) if r.source_side=="A" else None, int(r.source_row) if r.source_side=="B" else None, "high")
    # Duplicate keys in either source are ambiguous and are excluded from all amount comparisons.
    dup_a=set(a.loc[a.transaction_id.duplicated(False),"transaction_id"]); dup_b=set(b.loc[b.transaction_id.duplicated(False),"transaction_id"])
    ambiguous=dup_a|dup_b
    for key in sorted(ambiguous):
        ar=a[a.transaction_id.eq(key)]; br=b[b.transaction_id.eq(key)]
        add_issue(key,"duplicate_key","both" if key in dup_a and key in dup_b else ("A" if key in dup_a else "B"),f"Ambiguous key: {len(ar)} System A rows, {len(br)} System B rows",None,None,"high")
        rows.append({"transaction_id":key,"outcome":"ambiguous_duplicate","system_a_count":len(ar),"system_b_count":len(br),"amount_a":None,"amount_b":None,"amount_difference":None})
    au=a[~a.transaction_id.isin(ambiguous)].set_index("transaction_id",drop=False); bu=b[~b.transaction_id.isin(ambiguous)].set_index("transaction_id",drop=False)
    for key in sorted(set(au.index)|set(bu.index)):
        if key not in au.index:
            r=bu.loc[key]; rows.append({"transaction_id":key,"outcome":"missing_in_a","system_a_count":0,"system_b_count":1,"amount_a":None,"amount_b":float(r.amount),"amount_difference":None}); add_issue(key,"missing_in_a","B","Record exists only in System B",None,int(r.source_row),"high"); continue
        if key not in bu.index:
            r=au.loc[key]; rows.append({"transaction_id":key,"outcome":"missing_in_b","system_a_count":1,"system_b_count":0,"amount_a":float(r.amount),"amount_b":None,"amount_difference":None}); add_issue(key,"missing_in_b","A","Record exists only in System A",int(r.source_row),None,"high"); continue
        x,y=au.loc[key],bu.loc[key]; diffs=[]
        # Amounts are comparable only when their currency codes agree.
        amount_diff=round(float(x.amount)-float(y.amount), 6) if x.currency==y.currency else None
        if amount_diff is not None and abs(amount_diff)>config.amount_tolerance:
            diffs.append("amount_mismatch"); add_issue(key,"amount_mismatch","both",f"A={x.amount}; B={y.amount}; A-B={amount_diff}",int(x.source_row),int(y.source_row))
        for col,typ in (("transaction_date","transaction_date_mismatch"),("settlement_date","settlement_date_mismatch")):
            daydiff=abs((date.fromisoformat(x[col])-date.fromisoformat(y[col])).days)
            if daydiff>config.date_tolerance_days:
                diffs.append(typ); add_issue(key,typ,"both",f"A={x[col]}; B={y[col]}; difference={daydiff} day(s)",int(x.source_row),int(y.source_row))
        for col in ("status","currency","transaction_type"):
            if x[col]!=y[col]:
                typ=col+"_mismatch"; diffs.append(typ); add_issue(key,typ,"both",f"A={x[col]}; B={y[col]}",int(x.source_row),int(y.source_row))
        outcome="matched" if not diffs else "mismatch"
        rows.append({"transaction_id":key,"outcome":outcome,"system_a_count":1,"system_b_count":1,"amount_a":float(x.amount),"amount_b":float(y.amount),"amount_difference":amount_diff})
    results=pd.DataFrame(rows,columns=["transaction_id","outcome","system_a_count","system_b_count","amount_a","amount_b","amount_difference"])
    exceptions=pd.DataFrame(issues,columns=["transaction_id","issue_type","source_side","system_a_row","system_b_row","details","severity"])
    a_total=float(a.amount.sum()); b_total=float(b.amount.sum()); matched=results.outcome.eq("matched").sum()
    currencies=sorted(set(a.currency)|set(b.currency))
    currency_amounts=[{"currency":currency,"system_a_valid_amount":round(float(a.loc[a.currency.eq(currency),"amount"].sum()),2),"system_b_valid_amount":round(float(b.loc[b.currency.eq(currency),"amount"].sum()),2),"system_a_minus_b":round(float(a.loc[a.currency.eq(currency),"amount"].sum()-b.loc[b.currency.eq(currency),"amount"].sum()),2)} for currency in currencies]
    summary={"source_a_rows":len(frame_a),"source_b_rows":len(frame_b),"valid_a_rows":len(a),"valid_b_rows":len(b),"rejected_rows":len(rejected),"result_keys":len(results),"matched_keys":int(matched),"unmatched_or_exception_keys":int(len(results)-matched),"record_match_rate":float(matched/max(len(results),1)),"source_a_valid_amount":a_total,"source_b_valid_amount":b_total,"valid_source_amount_difference":round(a_total-b_total,2) if len(currencies)<=1 else None,"currency_amounts":currency_amounts,"exception_count":len(exceptions),"amount_tolerance":config.amount_tolerance,"date_tolerance_days":config.date_tolerance_days}
    return ReconciliationOutput(results,exceptions,rejected,summary)
