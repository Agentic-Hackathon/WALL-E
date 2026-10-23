"""M8 scoped ShadowBroker adapter for conservative partial exits/sized entries.

Reuses unchanged RiskGate, PaperAccount state/hash chain, actual Atlas quote
receipts and depth sweeps. No live transport, secrets, model promotion or new
risk authorization. ADD cannot bypass the existing gate's HOLD-on-held policy.
Counterfactual depth estimates are NOT exchange fills or realized trading PnL.
"""
import json,math,sqlite3,time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from .atlas_forward import _sha,_canon
from .atlas_shadow import PaperAccount,now
from .atlas_risk import RiskGate
from .atlas_portfolio import AllocationLimits,cost_audit
from .live_scout import _buy_with_notional,_sell_qty,_levels

ACTIONS=('BUY','ADD','HOLD','REDUCE','SELL','REBALANCE','STAY_IN_CASH','REJECT')
VERSION='ATLAS_DYNAMIC_SHADOW_V1'


def account_snapshot(account,quotes,*,stamp=None,fee=.001):
    stamp=time.time() if stamp is None else stamp;positions=account.db.execute('SELECT symbol,quantity,entry_cost FROM positions ORDER BY symbol').fetchall()
    cash=float(account.get('cash_tmn'));nav=cash;values={}
    high_water=float(account.get('high_water_tmn'));stopped=account.get('stopped')
    if not math.isfinite(cash) or cash<0 or not math.isfinite(high_water) or high_water<=0 or stopped not in ('0','1'):raise ValueError('INVALID_PERSISTED_ACCOUNT_STATE')
    for symbol,quantity,cost in positions:
        if not all(math.isfinite(v) and v>0 for v in (quantity,cost)):raise ValueError('INVALID_PERSISTED_POSITION')
        q=quotes.get(symbol)
        if q is None or not 0<=stamp-q['observed_epoch']<=30:raise ValueError('MISSING_FRESH_HELD_ASSET_BID')
        cost_audit(q,max(cost,1),fee);sweep=_sell_qty(_levels(q['raw_book'],'bid'),quantity)
        if sweep is None:raise ValueError('INSUFFICIENT_REAL_HELD_EXIT_DEPTH')
        values[symbol]=sweep[0]*(1-fee);nav+=values[symbol]
    if not math.isfinite(nav) or nav<=0:raise ValueError('NONPOSITIVE_OR_NONFINITE_NAV')
    return {'cash_tmn':cash,'positions':positions,'nav_tmn':nav,'marked_asset_values_tmn':values,
        'high_water_tmn':high_water,'stopped':stopped=='1',
        'all_held_assets_valued':True,'valuation':'actual full displayed bid sweep less assumed exit fee'}


class DynamicShadowBroker:
    """Persistent shadow-only adapter; every mutation follows SAME RiskGate.

    A full SELL authorization may be conservatively reduced in quantity.
    A BUY authorization may be conservatively reduced in notional. HOLD never
    becomes ADD. No other strategy or score can manufacture permission.
    """
    def __init__(self,directory,contract):
        self.directory=Path(directory).resolve();self.contract=contract
        if 'milestone8' not in self.directory.parts or contract['settings'].get('research_profile')!='ATLAS_M8_AGENTIC_V1':raise ValueError('SEPARATE_OPT_IN_M8_SHADOW_ACCOUNT_REQUIRED')
        if contract['settings'].get('LIVE')!='HARD_DISABLED':raise ValueError('LIVE_MUST_REMAIN_HARD_DISABLED')
        self.account=PaperAccount(SimpleNamespace(root=self.directory));self.db=self.account.db
        self.db.executescript('''CREATE TABLE IF NOT EXISTS dynamic_intents_v8(
            intent_id TEXT PRIMARY KEY,created REAL NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS dynamic_cycle_budget_v8(cycle_id TEXT PRIMARY KEY,nav REAL NOT NULL,turnover REAL NOT NULL,cost REAL NOT NULL);
        ''');self.db.commit()
    def close(self):self.account.close()
    def _forecast(self,prediction_id,forecast,symbol):
        path=self.directory/'forward_observations.sqlite'
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:row=db.execute('SELECT model,payload,payload_sha FROM m6_predictions WHERE prediction_id=?',(prediction_id,)).fetchone()
        finally:db.close()
        if not row or row[0]!='champion':raise ValueError('ONLY_REGISTERED_CHAMPION_FORECAST_CAN_TRADE')
        p=json.loads(row[1]);q=forecast.get('quantile_log_returns',{})
        if _sha(p)!=row[2] or p['symbol']!=symbol:raise ValueError('FORECAST_RECEIPT_INVALID')
        if p['model_sha256']!=self.contract['models']['champion']['model_sha256']:raise ValueError('PINNED_CHAMPION_REQUIRED')
        if not 0<=time.time()-p['prediction_available_at']<=p['forecast_horizon']:raise ValueError('FORECAST_STALE_OR_FUTURE')
        for key in ('q10','q50','q90'):
            if key=='q10' and q.get(key) is None:continue # restrictive review veto ONLY
            if q.get(key)!=p[key]:raise ValueError('REVIEW_MUST_NOT_MODIFY_NUMERICAL_FORECAST')
        return p
    def submit(self,intent,*,forecast,quotes,review,cycle_id,fee=.001):
        action=intent['action'];symbol=intent['symbol'];key=intent['intent_id']
        if symbol not in self.contract['settings']['symbols']:raise ValueError('MARKET_OUTSIDE_FROZEN_RESEARCH_UNIVERSE')
        if action not in ACTIONS:raise ValueError('UNKNOWN_DYNAMIC_ACTION')
        if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('HASHED_INTENT_ID_REQUIRED')
        if not isinstance(cycle_id,str) or len(cycle_id)>128:raise ValueError('BOUNDED_CYCLE_ID_REQUIRED')
        if not 0<=fee<.05:raise ValueError('INVALID_EXPLICIT_FEE')
        if fee!=self.contract['settings']['fee_per_side_assumed']:raise ValueError('PINNED_ASSUMED_FEE_MUST_NOT_BE_OVERRIDDEN')
        for field in ('quantity','notional_tmn'):
            value=intent.get(field)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<=0):raise ValueError('INVALID_REQUESTED_AMOUNT')
        if _sha({k:v for k,v in review.items() if k!='review_sha256'})!=review['review_sha256']:raise ValueError('REVIEW_HASH_INVALID')
        if review['symbol']!=symbol or _sha(forecast)!=_sha(review['forecast_for_gate']):raise ValueError('REVIEW_FORECAST_MISMATCH')
        fingerprint=_sha({'intent':intent,'forecast':forecast,'quotes':quotes,'review_sha256':review['review_sha256'],'cycle_id':cycle_id,'fee':fee})
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT fingerprint,payload,sha256 FROM dynamic_intents_v8 WHERE intent_id=?',(key,)).fetchone()
            if old:
                if old[0]!=fingerprint:raise ValueError('DYNAMIC_IDEMPOTENCY_CONFLICT')
                payload=json.loads(old[1])
                if _sha(payload)!=old[2]:raise ValueError('DYNAMIC_RECEIPT_HASH_INVALID')
                self.db.commit();return payload
            if not self.account.verify():raise ValueError('PAPER_HASH_CHAIN_INVALID')
            before=account_snapshot(self.account,quotes,fee=fee)
            observation=quotes.get(symbol)
            if observation:cost_audit(observation,500000,fee)
            receipt={'version':VERSION,'intent':intent,'before':before,
                'review_sha256':review['review_sha256'],'contract_sha256':self.contract['contract_sha256'],
                'forecast':forecast,'forecast_receipt':None,'quote_sha256':observation.get('receipt_sha256') if observation else None,'gate':None,'action':action,
                'status':'NO_PAPER_MUTATION','reason':(intent.get('reason_codes') or ['NO_ACTION_REQUESTED'])[0],
                'reason_codes':intent.get('reason_codes',[]),'hypothetical':True,'exchange_fill':None,
                'fee_per_side_assumed':fee,'fee_verified':False,'trade_estimate':None,'actual_created_at':time.time()}
            if action in ('BUY','ADD','REDUCE','SELL','REBALANCE'):
                q=quotes.get(symbol)
                if q is None or q['symbol']!=symbol or not 0<=time.time()-q['observed_epoch']<=30:raise ValueError('FRESH_REAL_QUOTE_REQUIRED')
                from .atlas_study import fast_validate
                fast_validate(self.contract)
                # Additional competition boundary, never weakens existing Gate.
                # Missing external-clock receipt fails closed. Old M8 is not reused.
                from .atlas_deadline import permission
                permission(self.directory,intent['action'])
                audit=cost_audit(q,500000,fee);book=dict(audit);book['best_bid_quantity']=_levels(q['raw_book'],'bid')[0][1]
                receipt['quote_sha256']=q['receipt_sha256']
                terminal=intent.get('purpose')=='FINAL_TMN'
                if terminal:
                    session=json.loads((self.directory/'watch_session.json').read_text())
                    margin=self.contract['settings'].get('intelligence',{}).get('terminal_exit_window_seconds',300)
                    if action!='SELL' or time.time()<session['deadline_epoch']-margin:raise ValueError('NOT_IN_DECLARED_TERMINAL_EXIT_WINDOW')
                elif action in ('BUY','ADD') or intent.get('prediction_id'):
                    receipt['forecast_receipt']=self._forecast(intent['prediction_id'],forecast,symbol)
                elif any(v is not None for v in forecast.get('quantile_log_returns',{}).values()):raise ValueError('EXIT_WITHOUT_MODEL_MUST_NOT_INVENT_QUANTILES')
                assessment=RiskGate().assess_equity(before['nav_tmn'],before['high_water_tmn'],before['stopped'])
                self.account._set('high_water_tmn',assessment.high_water_tmn);self.account._set('stopped','1' if assessment.stopped else '0')
                gate=(RiskGate().final_tmn_liquidation(symbol,book,before['cash_tmn'],before['positions'],fee) if terminal else
                    RiskGate().evaluate(symbol,forecast,book,before['cash_tmn'],before['positions'],assessment.stopped,fee))
                receipt['gate']=gate.audit_payload();receipt['risk_inputs']={'symbol':symbol,'forecast':forecast,'book':book,
                    'cash_tmn':before['cash_tmn'],'positions':before['positions'],'stopped':assessment.stopped,'fee':fee,'limits':asdict(RiskGate().limits),
                    'purpose':'FINAL_TMN' if terminal else 'STRATEGY'}
                receipt['reason']=gate.reason
                budget_id=str(int(time.time()//900)*900);receipt['budget_period_start']=int(budget_id)
                budget=self.db.execute('SELECT nav,turnover,cost FROM dynamic_cycle_budget_v8 WHERE cycle_id=?',(budget_id,)).fetchone()
                nav,used_turnover,used_cost=budget if budget else (before['nav_tmn'],0.,0.)
                trade=None
                if action in ('BUY','ADD') and gate.action=='PAPER_BUY':
                    amount=min(float(intent.get('notional_tmn') or 0),gate.notional_tmn,nav*.1)
                    if amount<RiskGate().limits.min_order_notional_tmn:receipt['reason']='REQUEST_BELOW_UNCHANGED_MINIMUM'
                    elif action=='ADD':receipt['reason']='ADD_NOT_AUTHORIZED_BY_CURRENT_GATE'
                    elif before['cash_tmn']-amount<nav*.8:receipt['reason']='MINIMUM_CASH_RESERVE'
                    else:
                        sweep=_buy_with_notional(_levels(q['raw_book'],'ask'),amount/(1+fee))
                        if sweep is None:receipt['reason']='INSUFFICIENT_ACTUAL_ASK_SWEEP'
                        else:trade={'side':'BUY','quantity':sweep[0],'average_tmn':sweep[1],'cash_delta':-amount,'turnover':amount,
                            'cost_tmn':max(0,amount-sweep[0]*q['mid'])}
                elif action in ('SELL','REDUCE') and gate.action=='PAPER_SELL':
                    held=next(p for p in before['positions'] if p[0]==symbol)
                    quantity=float(intent.get('quantity') or held[1])
                    if terminal and quantity!=held[1]:raise ValueError('FINAL_TMN_REQUIRES_FULL_POSITION')
                    if quantity<=0 or quantity>held[1]:receipt['reason']='REDUCTION_MUST_BE_POSITIVE_SUBSET_OF_HELD_QUANTITY'
                    else:
                        sweep=_sell_qty(_levels(q['raw_book'],'bid'),quantity)
                        if sweep is None:receipt['reason']='INSUFFICIENT_ACTUAL_BID_SWEEP'
                        else:trade={'side':'SELL','quantity':quantity,'average_tmn':sweep[1],'cash_delta':sweep[0]*(1-fee),
                            'turnover':sweep[0],'cost_tmn':max(0,quantity*q['mid']-sweep[0]*(1-fee))}
                elif action=='ADD':receipt['reason']='ADD_BLOCKED_UNCHANGED_GATE_DOES_NOT_AUTHORIZE_HELD_ENTRY'
                elif action=='REBALANCE':receipt['reason']='REBALANCE_REQUIRES_SEPARATE_GATED_EXIT_THEN_FRESH_ENTRY'
                if trade:
                    if used_turnover+trade['turnover']>nav*AllocationLimits().max_turnover_fraction+1e-8:receipt['reason']='ATOMIC_CYCLE_TURNOVER_CAP';trade=None
                    elif used_cost+trade['cost_tmn']>nav*AllocationLimits().max_rebalance_cost_fraction+1e-8:receipt['reason']='ATOMIC_CYCLE_COST_CAP';trade=None
                if trade:
                    self.account._set('cash_tmn',before['cash_tmn']+trade['cash_delta'])
                    if trade['side']=='BUY':
                        self.db.execute('INSERT INTO positions VALUES(?,?,?,?,?)',(symbol,trade['quantity'],-trade['cash_delta'],trade['average_tmn'],now()))
                    else:
                        held=next(p for p in before['positions'] if p[0]==symbol);remaining=held[1]-trade['quantity']
                        if remaining==0:self.db.execute('DELETE FROM positions WHERE symbol=?',(symbol,))
                        else:self.db.execute('UPDATE positions SET quantity=?,entry_cost=? WHERE symbol=?',(remaining,held[2]*remaining/held[1],symbol))
                    self.db.execute('INSERT OR REPLACE INTO dynamic_cycle_budget_v8 VALUES(?,?,?,?)',(budget_id,nav,used_turnover+trade['turnover'],used_cost+trade['cost_tmn']))
                    receipt.update(status='PAPER_ESTIMATE_RECORDED',reason=gate.reason,trade_estimate=trade)
            receipt['after']=account_snapshot(self.account,quotes,fee=fee)
            receipt['source_evidence_hash']=review['source_evidence_hash']
            self.account.log(symbol,'M8_'+receipt['status'],receipt)
            self.db.execute('INSERT INTO dynamic_intents_v8 VALUES(?,?,?,?,?)',(key,time.time(),fingerprint,_canon(receipt),_sha(receipt)))
            self.db.commit();return receipt
        except Exception:self.db.rollback();raise


def replay(receipt):
    """Pure persisted-input gate/accounting check, no broker/network/memory."""
    inputs=receipt.get('risk_inputs');same=None
    if inputs:
        gate=(RiskGate().final_tmn_liquidation(inputs['symbol'],inputs['book'],inputs['cash_tmn'],inputs['positions'],inputs['fee']) if inputs.get('purpose')=='FINAL_TMN' else
            RiskGate().evaluate(inputs['symbol'],inputs['forecast'],inputs['book'],inputs['cash_tmn'],inputs['positions'],inputs['stopped'],inputs['fee']))
        same=gate.audit_payload()==receipt['gate']
    trade=receipt.get('trade_estimate');cash_equal=receipt['before']['cash_tmn']+(trade['cash_delta'] if trade else 0)==receipt['after']['cash_tmn']
    return {'gate_identical':same,'cash_conserved':cash_equal,'exchange_fill_is_none':receipt['exchange_fill'] is None,'authority':'PURE_REPLAY_NO_WRITES'}
