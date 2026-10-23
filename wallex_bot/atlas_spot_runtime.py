"""Explicitly authorized Spot execution, separate from legacy HARD_DISABLED broker.

Original Atlas adapter over existing OrderIntent, Decimal wire contract,
SpotLedger, RiskGate and deadline gate. Official contracts reviewed:
developers.wallex.ir/docs/spot-intro (sub-account-client-id), spot-create-order,
spot-single-order-detail, spot-active-orders, spot-cancel-order.
No external connector source copied. No automatic arming or probing orders.
"""
from contextlib import contextmanager
from decimal import Decimal
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import requests

from .atlas_broker import BrokerSafetyError, OrderIntent
from .atlas_spot_exchange import SpotLedger, decimal, wire_order, TERMINAL
from .atlas_risk import RiskGate
from .atlas_deadline import permission, ENTRY_STOP, DEADLINE
from .atlas_forward import _sha

_PERMIT_SECRET=object()


class _NetworkPermit:
    """One-shot, exact-request capability minted only after risk/account checks."""
    def __init__(self,owner,action,method,client_id,payload,secret):
        if secret is not _PERMIT_SECRET:raise BrokerSafetyError('INVALID_EXECUTION_CAPABILITY')
        self.owner=owner;self.action=action;self.identity=_sha([method,client_id,payload]);self.used=False
    def validate(self,method,client_id,payload):
        if self.used or self.identity!=_sha([method,client_id,payload]):raise BrokerSafetyError('EXECUTION_CAPABILITY_USED_OR_REQUEST_CHANGED')
        self.owner._permit(self.action);self.used=True


class AccountSpotTransport:
    """Account-bound HTTPS allowlist, one attempt, no redirects or retries."""
    def __init__(self,client_id):
        if not isinstance(client_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',client_id):
            raise BrokerSafetyError('VERIFIED_SUBACCOUNT_CLIENT_ID_REQUIRED')
        self.client_id=client_id

    def request(self,method,resource,*,client_id=None,payload=None,page=None,permit=None):
        allowed={('GET','balances'):'/v1/account/balances-detail',('GET','fees'):'/v1/account/fee',
            ('GET','subaccounts'):'/sub-accounts',('GET','open_orders'):'/v1/account/openOrders',
            ('GET','order'):'/v1/account/orders/',('POST','order'):'/v1/account/orders',
            ('DELETE','order'):'/v1/account/orders/'}
        if (method,resource) not in allowed:raise BrokerSafetyError('ENDPOINT_NOT_ALLOWED')
        if method!='GET':
            if type(permit) is not _NetworkPermit:raise BrokerSafetyError('NO_PROCESS_LOCAL_EXECUTION_PERMIT')
            permit.validate(method,client_id,payload)
        key=os.environ.get('WALLEX_API_KEY')
        if not key:raise BrokerSafetyError('WALLEX_API_KEY_UNSET')
        path=allowed[method,resource]
        if path.endswith('/'):
            if not isinstance(client_id,str) or not re.fullmatch(r'[A-Za-z0-9_]{8,64}',client_id):raise ValueError('INVALID_CLIENT_ORDER_ID')
            path+=client_id
        params={'page':page,'per_page':100} if resource=='open_orders' else None
        try:
            r=requests.request(method,'https://api.wallex.ir'+path,
                headers={'x-api-key':key,'sub-account-client-id':self.client_id,'Accept':'application/json'},
                json=payload,params=params,timeout=(5,15),allow_redirects=False)
            if key.encode() in r.content:raise BrokerSafetyError('CREDENTIAL_ECHO_RESPONSE_NOT_STORED')
            p=r.json(parse_float=str) # Preserve decimal text, never binary-float wire amounts.
            if r.status_code not in ((201,) if method=='POST' else (200,)) or p.get('success') is not True:
                raise BrokerSafetyError('EXCHANGE_RESPONSE_UNVERIFIED_RECONCILE_NO_RETRY')
            p['_response_sha256']=hashlib.sha256(r.content).hexdigest()
            p['_raw_body_utf8']=r.content.decode('utf-8');p['_observed_epoch']=time.time()
            return p
        except (requests.RequestException,ValueError):
            raise BrokerSafetyError('EXCHANGE_RESULT_UNKNOWN_RECONCILE_NO_RETRY') from None

    def open_orders(self):
        orders=[];seen=set()
        # Require an empty final page. Repeated pages and missing schemas block.
        for page in range(1,12):
            p=self.request('GET','open_orders',page=page).get('result')
            if isinstance(p,dict) and all(isinstance(v,list) for v in p.values()):p=[o for v in p.values() for o in v]
            if not isinstance(p,list):raise BrokerSafetyError('OPEN_ORDER_SCHEMA_UNVERIFIED')
            if not p:return orders
            for item in p:
                key=item.get('clientOrderId')
                if not isinstance(key,str) or key in seen:raise BrokerSafetyError('OPEN_ORDER_PAGINATION_UNVERIFIED')
                seen.add(key);orders.append(item)
        raise BrokerSafetyError('OPEN_ORDER_PAGE_BOUND_REACHED_FAIL_CLOSED')


class ControlledSpotBroker:
    """No startup arm. Exact local operator confirmation plus verified evidence.

    This class is never constructed/armed by the web console or an Agent/LLM.
    Manifest contains operator/organizer authorization references, not keys.
    Missing proof is a blocker, not a default READY boolean.
    """
    def __init__(self,root,authorization_file,forecast_session):
        self.root=Path(root).resolve();self.authorization_file=Path(authorization_file).resolve()
        if not self.authorization_file.is_relative_to(self.root/'operations'):
            raise BrokerSafetyError('AUTHORIZATION_MUST_BE_OPERATOR_LOCAL_OPERATIONS_FILE')
        self.approval=json.loads(self.authorization_file.read_text(encoding='utf-8'))
        self.approval_sha=_sha(self.approval)
        self.forecast_session=Path(forecast_session).resolve()
        if not self.forecast_session.is_relative_to(self.root/'research_challengers'):
            raise BrokerSafetyError('REGISTERED_LOCAL_FORECAST_SESSION_REQUIRED')
        self.api=AccountSpotTransport(self.approval.get('account_client_id'))
        identity=hashlib.sha256(self.api.client_id.encode()).hexdigest()
        self.directory=self.root/'operations/spot_accounts'/identity
        self.ledger=SpotLedger(self.directory);self.gate=RiskGate();self.arm_state=None
        self.lock_db=sqlite3.connect(self.directory/'mutation_lock.sqlite',timeout=30)
        self.lock_db.execute('CREATE TABLE IF NOT EXISTS locks(id INTEGER PRIMARY KEY)');self.lock_db.commit()
        self.ledger.db.execute('CREATE TABLE IF NOT EXISTS spot_baseline(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT,sha TEXT)')
        self.ledger.db.execute('CREATE TABLE IF NOT EXISTS spot_equity_guard(id INTEGER PRIMARY KEY CHECK(id=1),high_water REAL,stopped INTEGER)')
        self.ledger.db.commit()

    @contextmanager
    def exclusive(self):
        self.lock_db.execute('BEGIN IMMEDIATE')
        try:yield
        finally:self.lock_db.rollback()

    def _proofs(self,execution=True):
        a=self.approval
        if a.get('schema')!='ATLAS_OPERATOR_SPOT_AUTHORIZATION_V1':raise BrokerSafetyError('AUTHORIZATION_SCHEMA_REQUIRED')
        if not isinstance(a.get('session_id'),str) or not re.fullmatch(r'[A-Za-z0-9_]{8,64}',a['session_id']):raise BrokerSafetyError('EXPLICIT_SESSION_REQUIRED')
        if not isinstance(a.get('package_id'),int) or a['package_id']<=0:raise BrokerSafetyError('VERIFIED_PACKAGE_ID_REQUIRED')
        if not a.get('organizer_reference') or not a.get('trade_permission_reference'):raise BrokerSafetyError('ORGANIZER_AND_API_PERMISSION_PROOF_REQUIRED')
        markets=a.get('markets')
        if not isinstance(markets,dict) or not markets or any(not re.fullmatch(r'[A-Z0-9]+TMN',s) for s in markets):raise BrokerSafetyError('EXPLICIT_SPOT_TMN_ALLOWLIST_REQUIRED')
        for kind in ('contest_identity','contest_credit','market_limits','financial_validation'):
            proof=a.get('proofs',{}).get(kind,{})
            path=(self.root/proof.get('path','')).resolve()
            if not path.is_relative_to(self.root/'operations') or not path.is_file():raise BrokerSafetyError('MISSING_LOCAL_PROOF:'+kind)
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=proof.get('sha256'):raise BrokerSafetyError('PROOF_HASH_MISMATCH:'+kind)
            evidence=json.loads(raw)
            if evidence.get('account_client_id')!=a['account_client_id'] or evidence.get('package_id')!=a['package_id']:
                raise BrokerSafetyError('PROOF_ACCOUNT_OR_PACKAGE_MISMATCH:'+kind)
            if evidence.get('verified') is not True:raise BrokerSafetyError('UNVERIFIED_PROOF:'+kind)
            if kind=='market_limits' and evidence.get('markets')!=a['markets']:raise BrokerSafetyError('LIMITS_NOT_BOUND_TO_VERIFIED_PROOF')
            if kind=='financial_validation' and evidence.get('source')!='AUTHORIZED_REAL_EXECUTION_AND_INDEPENDENT_VALIDATION':
                raise BrokerSafetyError('FINANCIAL_VALIDATION_NOT_CERTIFIED')
        # No negative/NaN/infinite/expired approval may become permission.
        if execution and not time.time()<float(a.get('expires_epoch',0))<=DEADLINE.timestamp():raise BrokerSafetyError('EXPIRED_AUTHORIZATION_OR_DEADLINE')
        cap=decimal(a.get('max_capital_tmn'))
        if cap>Decimal(str(self.gate.limits.max_open_notional_tmn)):raise BrokerSafetyError('OPERATOR_CAP_EXCEEDS_UNCHANGED_RISK_CAP')
        return cap

    @staticmethod
    def _balances(response):
        p=response.get('result')
        if not isinstance(p,dict):raise BrokerSafetyError('BALANCE_SCHEMA_UNVERIFIED')
        totals={};available={}
        for coin,item in p.items():
            if not isinstance(item,dict):raise BrokerSafetyError('BALANCE_SCHEMA_UNVERIFIED')
            total=decimal(item.get('total'),zero=True);free=decimal(item.get('available'),zero=True)
            frozen=decimal(item.get('freeze'),zero=True)
            if total!=free+frozen:raise BrokerSafetyError('BALANCE_COMPONENTS_DO_NOT_CONSERVE')
            totals[coin]=total;available[coin]=free
        if 'TMN' not in totals:raise BrokerSafetyError('MISSING_TMN_BALANCE')
        return totals,available

    def _account(self):
        self._proofs(execution=False)
        p=self.api.request('GET','subaccounts').get('result')
        if isinstance(p,dict) and 'clientId' in p:p=[p]
        if not isinstance(p,list):raise BrokerSafetyError('SUBACCOUNT_SCHEMA_UNVERIFIED')
        matches=[x for x in p if x.get('clientId')==self.approval['account_client_id']]
        if len(matches)!=1 or matches[0].get('type')!='prop' or matches[0].get('isActive') is not True or matches[0].get('isSuspend') is not False:
            raise BrokerSafetyError('INTENDED_ACTIVE_CONTEST_SUBACCOUNT_NOT_VERIFIED')
        # Package restrictions are an independent current private GET.
        from .wallex_api import WallexReadClient
        restrictions=WallexReadClient().package_details(self.approval['package_id'])
        if any(s in restrictions['unavailableMarkets'] for s in self.approval['markets']):raise BrokerSafetyError('PACKAGE_MARKET_RESTRICTION')
        from .market import markets
        public={m['symbol']:m for m in markets()}
        if any(not (public.get(s,{}).get('is_spot') is True and public[s].get('quote_asset')=='TMN') for s in self.approval['markets']):
            raise BrokerSafetyError('PUBLIC_SPOT_TMN_MARKET_NOT_VERIFIED')
        totals,available=self._balances(self.api.request('GET','balances'))
        fees=self.api.request('GET','fees').get('result')
        if not isinstance(fees,dict):raise BrokerSafetyError('FEE_SCHEMA_UNVERIFIED')
        return totals,available,fees

    def _conservation(self,totals):
        self.ledger._require_integrity()
        row=self.ledger.db.execute('SELECT payload,sha FROM spot_baseline WHERE id=1').fetchone()
        if not row:raise BrokerSafetyError('MISSING_INITIAL_BALANCE_RECONCILIATION')
        baseline=json.loads(row[0])
        if _sha(baseline)!=row[1]:raise BrokerSafetyError('BASELINE_HASH_INVALID')
        expected={k:Decimal(v) for k,v in baseline.items()};positions={};spent=Decimal(0)
        for r in self.ledger.db.execute('SELECT symbol,side,state,exchange_snapshot FROM spot_orders ORDER BY rowid'):
            if r['state'] not in TERMINAL:raise BrokerSafetyError('PENDING_OR_UNKNOWN_ORDER_RECONCILE_FIRST')
            if not r['exchange_snapshot']:
                if r['state']=='REJECTED':continue
                raise BrokerSafetyError('MISSING_EXCHANGE_EXECUTION_SNAPSHOT')
            order=json.loads(r['exchange_snapshot'])['result'];qty=decimal(order['executedQty'],zero=True);amount=decimal(order['executedSum'],zero=True)
            coin=r['symbol'][:-3];sign=1 if r['side']=='BUY' else -1;fee_by_asset={}
            for fill in order['fills']:
                asset=fill['feeAsset'];fee_by_asset[asset]=fee_by_asset.get(asset,Decimal(0))+decimal(fill['fee'],zero=True)
            expected[coin]=expected.get(coin,Decimal(0))+sign*qty
            expected['TMN']=expected.get('TMN',Decimal(0))-sign*amount
            for asset,fee in fee_by_asset.items():expected[asset]=expected.get(asset,Decimal(0))-fee
            if r['side']=='BUY':
                spent+=amount+fee_by_asset.get('TMN',Decimal(0))
                old_qty,old_cost=positions.get(r['symbol'],(Decimal(0),Decimal(0)))
                positions[r['symbol']]=(old_qty+qty-fee_by_asset.get(coin,Decimal(0)),old_cost+amount+fee_by_asset.get('TMN',Decimal(0)))
            elif qty:
                old_qty,old_cost=positions.get(r['symbol'],(Decimal(0),Decimal(0)))
                used=qty+fee_by_asset.get(coin,Decimal(0))
                if used>old_qty:raise BrokerSafetyError('SELL_EXCEEDS_RECONCILED_POSITION')
                positions[r['symbol']]=(old_qty-used,old_cost*(old_qty-used)/old_qty)
        if any(expected.get(c,Decimal(0))!=totals.get(c,Decimal(0)) for c in set(expected)|set(totals)):
            raise BrokerSafetyError('ACCOUNT_BALANCES_DO_NOT_CONSERVE_MANUAL_REVIEW')
        return [(s,float(q),float(cost)) for s,(q,cost) in positions.items() if q],spent

    def arm_interactive(self,*,input_fn=input):
        with self.exclusive():
            cap=self._proofs();permission(self.root,'BUY')
            totals,available,_=self._account()
            if self.api.open_orders():raise BrokerSafetyError('ACCOUNT_OPEN_ORDERS_RECONCILE_BEFORE_ARM')
            row=self.ledger.db.execute('SELECT 1 FROM spot_baseline WHERE id=1').fetchone()
            if not row:
                if self.ledger.db.execute('SELECT 1 FROM spot_orders').fetchone() or any(q for c,q in totals.items() if c!='TMN'):
                    raise BrokerSafetyError('OPENING_POSITION_OR_ORDER_HISTORY_REQUIRES_AUDIT')
                baseline={c:str(v) for c,v in totals.items()}
                with self.ledger.db:self.ledger.db.execute('INSERT INTO spot_baseline VALUES(1,?,?)',(json.dumps(baseline),_sha(baseline)))
            self._conservation(totals)
            if cap>available['TMN']:raise BrokerSafetyError('OPERATOR_CAP_EXCEEDS_AVAILABLE_CASH')
            phrase='ARM '+self.approval['session_id']+' '+str(cap)+' TMN'
            if input_fn('Local operator confirmation ['+phrase+']: ')!=phrase:raise BrokerSafetyError('OPERATOR_DID_NOT_CONFIRM')
            self.arm_state={'pid':os.getpid(),'monotonic_deadline':time.monotonic()+min(300,self.approval['expires_epoch']-time.time()),
                'key_sha':hashlib.sha256(os.environ.get('WALLEX_API_KEY','').encode()).hexdigest()}
        return {'mode':'LIVE_ARMED','expires_in_at_most_seconds':300,'restart_disarms':True,'orders_sent':0}

    def disarm(self):self.arm_state=None

    def _permit(self,action):
        a=self.arm_state
        if not a or a['pid']!=os.getpid() or time.monotonic()>=a['monotonic_deadline']:
            self.disarm();raise BrokerSafetyError('DISARMED_OR_EXPIRED_RESTART_REQUIRES_CONFIRMATION')
        if _sha(json.loads(self.authorization_file.read_text()))!=self.approval_sha:raise BrokerSafetyError('AUTHORIZATION_CHANGED_DISARM_REQUIRED')
        if hashlib.sha256(os.environ.get('WALLEX_API_KEY','').encode()).hexdigest()!=a['key_sha']:raise BrokerSafetyError('ACCOUNT_KEY_CHANGED')
        self._proofs();permission(self.root,action)

    def _forecast_and_quote(self,symbol,prediction_id):
        from .atlas_study import fast_validate
        contract=json.loads((self.forecast_session/'study_contract.json').read_text());fast_validate(contract)
        db=sqlite3.connect((self.forecast_session/'forward_observations.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            row=db.execute('SELECT payload,payload_sha FROM m6_predictions WHERE prediction_id=? AND model=? AND symbol=?',(prediction_id,'champion',symbol)).fetchone()
            qrow=db.execute('SELECT symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256 FROM quotes WHERE symbol=? ORDER BY observed_epoch DESC LIMIT 1',(symbol,)).fetchone()
        finally:db.close()
        if not row or not qrow:raise BrokerSafetyError('REGISTERED_CHAMPION_AND_REAL_QUOTE_REQUIRED')
        forecast=json.loads(row[0]);now=time.time()
        if _sha(forecast)!=row[1] or not 0<=now-forecast['prediction_available_at']<=forecast['forecast_horizon']:
            raise BrokerSafetyError('INVALID_OR_STALE_FORECAST')
        if forecast['model_sha256']!=contract['models']['champion']['model_sha256']:raise BrokerSafetyError('CHAMPION_IDENTITY_MISMATCH')
        q=dict(zip(('symbol','observed_epoch','best_bid','best_ask','mid','raw_book','receipt_sha256'),qrow));q['raw_book']=json.loads(q['raw_book'])
        if _sha({k:v for k,v in q.items() if k!='receipt_sha256'})!=q['receipt_sha256'] or not 0<=now-q['observed_epoch']<=30:
            raise BrokerSafetyError('INVALID_OR_STALE_QUOTE')
        return {'quantile_log_returns':{k:forecast[k] for k in ('q10','q50','q90')}},q

    def _equity_assessment(self,totals,positions,fees):
        from .live_scout import _levels,_sell_qty
        nav=float(totals['TMN'])
        db=sqlite3.connect((self.forecast_session/'forward_observations.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            for symbol,qty,_ in positions:
                row=db.execute('SELECT symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256 FROM quotes WHERE symbol=? ORDER BY observed_epoch DESC LIMIT 1',(symbol,)).fetchone()
                if not row:raise BrokerSafetyError('MISSING_ACTUAL_HELD_ASSET_BOOK')
                q=dict(zip(('symbol','observed_epoch','best_bid','best_ask','mid','raw_book','receipt_sha256'),row));q['raw_book']=json.loads(q['raw_book'])
                if _sha({k:v for k,v in q.items() if k!='receipt_sha256'})!=q['receipt_sha256'] or not 0<=time.time()-q['observed_epoch']<=30:
                    raise BrokerSafetyError('HELD_ASSET_BOOK_STALE_OR_INVALID')
                sweep=_sell_qty(_levels(q['raw_book'],'bid'),qty)
                if sweep is None:raise BrokerSafetyError('HELD_ASSET_LIQUIDATION_DEPTH_INSUFFICIENT')
                rate=decimal(fees[symbol]['takerFeeRate'],zero=True)
                if rate>=Decimal('.05'):raise BrokerSafetyError('INVALID_HELD_ASSET_FEE')
                nav+=sweep[0]*(1-float(rate))
        finally:db.close()
        row=self.ledger.db.execute('SELECT high_water,stopped FROM spot_equity_guard WHERE id=1').fetchone()
        initial=json.loads(self.ledger.db.execute('SELECT payload FROM spot_baseline WHERE id=1').fetchone()[0])
        high,stopped=row if row else (float(initial['TMN']),False)
        assessment=self.gate.assess_equity(nav,high,bool(stopped))
        with self.ledger.db:self.ledger.db.execute('INSERT OR REPLACE INTO spot_equity_guard VALUES(1,?,?)',(assessment.high_water_tmn,int(assessment.stopped)))
        return assessment,nav

    def submit(self,intent,*,price,quantity,prediction_id):
        from .atlas_portfolio import cost_audit
        with self.exclusive():
            self._permit(intent.side)
            old=self.ledger.status(intent.client_order_id)
            limits=self.approval['markets'].get(intent.symbol)
            if not limits:raise BrokerSafetyError('MARKET_NOT_AUTHORIZED')
            payload=wire_order(intent,price=price,quantity=quantity,**limits)
            if old:
                self.ledger.register(payload) # Exact duplicate returns status, never POST again.
                return self.ledger.status(intent.client_order_id)
            totals,available,fees=self._account();positions,spent=self._conservation(totals)
            if self.api.open_orders():raise BrokerSafetyError('OPEN_OR_OPPOSING_ACCOUNT_ORDER_SELF_TRADE_GUARD')
            forecast,quote=self._forecast_and_quote(intent.symbol,prediction_id)
            fee=float(decimal(fees[intent.symbol]['takerFeeRate'],zero=True))
            if not fee<.05:raise BrokerSafetyError('INVALID_CURRENT_FEE')
            book=cost_audit(quote,500000,fee)
            assessment,nav=self._equity_assessment(totals,positions,fees)
            if intent.purpose=='FINAL_TMN':
                phase=permission(self.root,'SELL')['phase']
                if phase!='EXIT_ONLY':raise BrokerSafetyError('FINAL_TMN_ONLY_IN_EXIT_WINDOW')
                from .live_scout import _levels
                book['best_bid_quantity']=_levels(quote['raw_book'],'bid')[0][1]
                gate=self.gate.final_tmn_liquidation(intent.symbol,book,float(available['TMN']),positions,fee)
            else:gate=self.gate.evaluate(intent.symbol,forecast,book,float(available['TMN']),positions,assessment.stopped,fee)
            if gate.action!=('PAPER_BUY' if intent.side=='BUY' else 'PAPER_SELL'):raise BrokerSafetyError('RISK_VETO:'+gate.reason)
            p=decimal(price);qty=decimal(quantity);gross=p*qty
            if p!=Decimal(str(quote['best_ask' if intent.side=='BUY' else 'best_bid'])):raise BrokerSafetyError('ONLY_OBSERVED_BEST_QUOTE_LIMIT_SUPPORTED')
            if intent.side=='BUY':
                cost=gross*(1+Decimal(str(fee)))
                if cost>Decimal(str(gate.notional_tmn)) or cost>available['TMN'] or spent+cost>self._proofs():raise BrokerSafetyError('RISK_OR_SESSION_CAP_EXCEEDED')
                from .atlas_portfolio import AllocationLimits
                policy=AllocationLimits()
                if positions:raise BrokerSafetyError('CROSS_ASSET_CORRELATION_NOT_CERTIFIED_NO_ADDITIONAL_POSITION')
                if (float(available['TMN']-cost)<policy.min_cash_weight*nav or
                    float(cost)>policy.max_asset_weight*nav or float(cost)>policy.max_turnover_fraction*nav or
                    float(gross)*fee>policy.max_rebalance_cost_fraction*nav):
                    raise BrokerSafetyError('PORTFOLIO_RESERVE_WEIGHT_TURNOVER_OR_COST_VETO')
            elif qty>next((Decimal(str(q)) for s,q,_ in positions if s==intent.symbol),Decimal(0)):
                raise BrokerSafetyError('SELL_EXCEEDS_ACTUAL_RECONCILED_HOLDING')
            self.ledger.register(payload)
            with self.ledger.db:self.ledger._state(intent.client_order_id,'SUBMITTED',json.dumps({'payload':payload,'gate':gate.audit_payload()}))
            try:
                capability=_NetworkPermit(self,intent.side,'POST',None,payload,_PERMIT_SECRET)
                response=self.api.request('POST','order',payload=payload,permit=capability)
                return self.ledger.observe(intent.client_order_id,response)
            except Exception:
                with self.ledger.db:self.ledger._state(intent.client_order_id,'UNKNOWN','SUBMISSION_RESULT_UNKNOWN_NO_RETRY')
                raise BrokerSafetyError('ORDER_UNKNOWN_READ_STATUS_BEFORE_ANY_OTHER_ACTION') from None

    def cancel(self,client_order_id):
        with self.exclusive():
            self._permit('CANCEL');self._account()
            old=self.ledger.status(client_order_id)
            if not old:raise BrokerSafetyError('UNTRACKED_ORDER_CANCEL_NOT_AUTHORIZED')
            if old['state'] in TERMINAL:return old
            # Read first; never cancel an unknown identity or assume cancellation.
            self.ledger.observe(client_order_id,self.api.request('GET','order',client_id=client_order_id))
            if self.ledger.status(client_order_id)['state'] in TERMINAL:return self.ledger.status(client_order_id)
            with self.ledger.db:self.ledger._state(client_order_id,'CANCEL_PENDING','OPERATOR_AUTHORIZED_CANCEL')
            try:
                capability=_NetworkPermit(self,'CANCEL','DELETE',client_order_id,None,_PERMIT_SECRET)
                return self.ledger.observe(client_order_id,self.api.request('DELETE','order',client_id=client_order_id,permit=capability))
            except Exception:
                with self.ledger.db:self.ledger._state(client_order_id,'UNKNOWN','CANCEL_RESULT_UNKNOWN_NO_RETRY')
                raise BrokerSafetyError('CANCEL_UNKNOWN_RECONCILE_READ_ONLY') from None

    def reconcile(self):
        with self.exclusive():
            for row in self.ledger.db.execute('SELECT client_id,state FROM spot_orders').fetchall():
                if row['state']=='CREATED':continue
                self.ledger.observe(row['client_id'],self.api.request('GET','order',client_id=row['client_id']))
            totals,available,fees=self._account();positions,spent=self._conservation(totals)
            return {'positions':positions,'balances':{k:str(v) for k,v in totals.items()},
                'spent_session_tmn':str(spent),'open_orders':self.api.open_orders(),'settlement_guaranteed':False}

    def close(self):self.disarm();self.ledger.close();self.lock_db.close()


def main():
    p=argparse.ArgumentParser(description='Local operator only. No automatic order or ARM.')
    p.add_argument('command',choices=('reconcile','interactive'))
    p.add_argument('--root',default='atlas_store');p.add_argument('--authorization',required=True)
    p.add_argument('--forecast-session',required=True)
    a=p.parse_args();broker=ControlledSpotBroker(a.root,a.authorization,a.forecast_session)
    try:
        if a.command=='reconcile':print(json.dumps(broker.reconcile(),default=str));return
        print(json.dumps(broker.arm_interactive()))
        while True:
            raw=input('Spot command JSON (or STOP): ')
            if raw=='STOP':break
            try:
                cmd=json.loads(raw)
                if cmd.get('operation')=='status':result=broker.reconcile()
                elif cmd.get('operation')=='cancel':result=broker.cancel(cmd['client_order_id'])
                elif cmd.get('operation')=='submit':
                    intent=OrderIntent(cmd['client_order_id'],cmd['symbol'],cmd['side'],purpose=cmd.get('purpose','STRATEGY'))
                    result=broker.submit(intent,price=cmd['price'],quantity=cmd['quantity'],prediction_id=cmd['prediction_id'])
                else:raise BrokerSafetyError('OPERATION_NOT_ALLOWED')
                print(json.dumps(result,default=str))
            except (BrokerSafetyError,ValueError,KeyError):
                # No request headers, keys or untrusted remote exception text.
                print(json.dumps({'status':'BLOCKED_OR_UNKNOWN_RECONCILE','no_automatic_retry':True}))
    finally:broker.close()


if __name__=='__main__':main()
