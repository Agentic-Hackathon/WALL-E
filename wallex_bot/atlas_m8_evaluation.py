"""M8 chronological saved-evidence backtest/replay and component ablations.

Read-only inputs, no ResearchMemory/Broker calls. Actual persisted paper
transitions are verified, never fabricated from candles. Alternative arms are
snapshot gate diagnostics until a common independent execution path exists.
"""
import argparse,json,time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from .atlas_operational import _read_connection,_table
from .atlas_forward import _sha
from .atlas_agentic_review import board,ABLATIONS
from .atlas_dynamic_shadow import replay
from .atlas_risk import RiskGate
from .atlas_portfolio_report import real_quotes,common_cohorts,depth_replay,write_csv
from .atlas_liquidation import _save_atomic


def epoch(value):
    if value is None:return None
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('BACKTEST_BOUNDARY_MUST_BE_TIMEZONE_AWARE')
    return stamp.timestamp()


def actual_decisions(directory,start=None,end=None,symbols=None):
    begin=epoch(start);finish=time.time() if end is None else epoch(end)
    if finish>time.time()+1 or (begin is not None and begin>=finish):raise ValueError('INVALID_OR_FUTURE_REPLAY_WINDOW')
    db=_read_connection(Path(directory)/'agentic_decisions.sqlite');rows=[]
    try:
        if not db or not _table(db,'agentic_decisions_v8'):return []
        for created,raw,digest in db.execute('SELECT created,payload,sha256 FROM agentic_decisions_v8 ORDER BY created,id'):
            if created>finish or (begin is not None and created<begin):continue
            p=json.loads(raw)
            if symbols is not None and p['evidence']['symbol'] not in symbols:continue
            if _sha(p)!=digest:raise ValueError('M8_DECISION_RECEIPT_HASH_INVALID')
            if p['evidence']['decision_time']>created:raise ValueError('DECISION_CLOCK_REVERSED')
            rows.append(p)
        return rows
    finally:
        if db:db.close()


def evaluate(directory,*,start=None,end=None,symbols=None):
    directory=Path(directory).resolve();rows=actual_decisions(directory,start,end,symbols);replayed=[];nav=[];reasons=Counter()
    for p in rows:
        repeated=board(p['evidence']);receipt=p['receipt'];check=replay(receipt)
        replayed.append({'intent_id':p['intent']['intent_id'],'review_identical':repeated==p['review'],**check})
        nav.append({'decision_timestamp':p['evidence']['decision_time'],'symbol':p['evidence']['symbol'],
            'cash_tmn':receipt['after']['cash_tmn'],'nav_tmn':receipt['after']['nav_tmn'],
            'cash_weight':receipt['after']['cash_tmn']/receipt['after']['nav_tmn'],
            'exposure_tmn':sum(receipt['after']['marked_asset_values_tmn'].values()),
            'status':receipt['status'],'reason':receipt['reason']})
        reasons.update(p['intent'].get('reason_codes',[receipt['reason']]))
    quotes=real_quotes(directory);lower=epoch(start);upper=epoch(end) if end else time.time()
    quotes=[q for q in quotes if (lower is None or q['observed_epoch']>=lower) and q['observed_epoch']<=upper and (symbols is None or q['symbol'] in symbols)]
    universe=sorted({p['evidence']['symbol'] for p in rows})
    cohorts=common_cohorts(quotes,universe) if universe else []
    benchmarks={'cash':depth_replay(cohorts,{})}
    if universe:
        benchmarks['equal_weight_capped']=depth_replay(cohorts,{s:min(.1,.2/len(universe)) for s in universe})
        for s in universe:benchmarks['buy_hold_'+s+'_10pct']=depth_replay(cohorts,{s:.1})
    arms=[]
    for arm in ABLATIONS:
        actions=Counter();veto=Counter();changed=0
        for p in rows:
            e=p['evidence'];r=board(e,arm=arm);state=e['portfolio']
            gate=RiskGate().evaluate(e['symbol'],r['forecast_for_gate'],e['book'],state['cash_tmn'],state['positions'],state['stopped'],.001)
            actions[gate.action]+=1;veto[gate.reason]+=1
            full=board(e);base_gate=RiskGate().evaluate(e['symbol'],full['forecast_for_gate'],e['book'],state['cash_tmn'],state['positions'],state['stopped'],.001)
            changed+=gate.action!=base_gate.action
        arms.append({'arm':arm,'actual_common_snapshots':len(rows),'status':'INSUFFICIENT_INDEPENDENT_ECONOMIC_ABLATION',
            'gate_action_counts':json.dumps(dict(actions),sort_keys=True),'gate_reason_counts':json.dumps(dict(veto),sort_keys=True),
            'changed_action_vs_full':changed,'gross_trading_pnl':None,'net_trading_pnl':None,'drawdown':None,'cost':None,
            'trades':None,'forecast_error':None,'valid_decision_rate':None,'note':'snapshot counterfactual, NOT independently executed policy path'})
    trades=[p['receipt']['trade_estimate'] for p in rows if p['receipt'].get('trade_estimate')]
    costs=sum(t['cost_tmn'] for t in trades);turnover=sum(t['turnover'] for t in trades)
    return {'version':'ATLAS_M8_RECORDED_EVIDENCE_REPLAY_V1','mode':'BACKTEST_READ_ONLY_NO_MEMORY_WRITES',
        'scope':'CHRONOLOGICAL_REPLAY_OF_ACTUAL_OBSERVED_DECISIONS; not a fabricated long historical policy simulation',
        'start':start,'end':end,'symbols':universe,'decision_count':len(rows),'quote_count':len(quotes),'nav_path':nav,
        'recorded_paper_transitions':len(trades),'estimated_transaction_cost_tmn':costs,'estimated_turnover_tmn':turnover,
        'net_paper_cash_change_tmn':rows[-1]['receipt']['after']['cash_tmn']-rows[0]['receipt']['before']['cash_tmn'] if rows and not rows[0]['receipt']['before']['positions'] and not rows[-1]['receipt']['after']['positions'] else None,
        'realized_exchange_pnl':None,'max_drawdown':None,'win_loss':None,'profit_factor':None,'risk_adjusted_return':None,
        'reason_counts':dict(reasons),'replay_checks':replayed,'counterfactual_actual_depth_benchmarks':benchmarks,
        'component_ablation':arms,'economic_edge':'NO_VERIFIED_ECONOMIC_EDGE',
        'status':'INSUFFICIENT_PROSPECTIVE_EVIDENCE','M5_strategy_attribution':'FORECAST OBSERVATION ONLY; no fabricated M5 allocation returns',
        'saved_receipt_replay_supported':True,'independent_long_historical_multi_agent_economic_backtest':'BLOCKED_MISSING_PIT_NEWS_BOOK_AND_APPROVED_ENTRY_EVIDENCE'}


def main():
    from .atlas_intelligence import DEFAULT_SESSION
    p=argparse.ArgumentParser();p.add_argument('--session-dir',default=DEFAULT_SESSION);p.add_argument('--start');p.add_argument('--end');p.add_argument('--symbols');p.add_argument('--output',default='reports/m8_backtest_results.json')
    a=p.parse_args();result=evaluate(a.session_dir,start=a.start,end=a.end,symbols=a.symbols.split(',') if a.symbols else None)
    _save_atomic(Path(a.output),result);write_csv(Path(a.output).parent/'m8_model_agent_ablation.csv',result['component_ablation'])
    print(json.dumps({'decision_count':result['decision_count'],'recorded_paper_transitions':result['recorded_paper_transitions'],'status':result['status']}))

if __name__=='__main__':main()
