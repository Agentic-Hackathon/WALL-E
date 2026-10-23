"""Read-only account discovery, original glue over existing Atlas contracts.

Official Wallex docs: trade-credit-active-sub-account-list, active-packages,
sub-account-history, package-details, spot-intro. No external connector copied.
Catalog/title/ordinary wallet balance never prove contest identity or Trade scope.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import requests
from .atlas_liquidation import _save_atomic
from .atlas_spot_runtime import ControlledSpotBroker
from .atlas_spot_exchange import decimal


def object_rows(value,identity):
    if isinstance(value,dict) and identity in value:value=[value]
    if not isinstance(value,list) or any(not isinstance(x,dict) for x in value):
        raise ValueError('UNVERIFIED_OBJECT_COLLECTION')
    return value


def compare_balance_contexts(default_context,subaccount_context):
    """A mismatch blocks routing; equality is NOT proof of key ownership.

    Two accounts may have equal balances. Read permission never proves Trade.
    Inputs must be actual independently read/validated balance snapshots.
    """
    if not default_context or not subaccount_context:
        return {'status':'UNKNOWN_MISSING_READ','api_key_matches_sub_account':None,'trade_authorized':False}
    same=all(decimal(default_context[k],zero=True)==decimal(subaccount_context[k],zero=True) for k in ('available','total','frozen'))
    return {'status':'BALANCES_CONSISTENT_NOT_KEY_OWNERSHIP_PROOF' if same else 'BALANCE_CONTEXT_MISMATCH_BLOCK_LIVE',
        'balances_equal':same,'api_key_matches_sub_account':None,'trade_authorized':False,
        'comparison_is_not_atomic':True}


class AccountReader:
    """GET only, fixed paths, bounded attempts, environment key at request time."""
    def __init__(self,folder):self.folder=folder;self.requests=0

    def get(self,path,*,account=None,params=None):
        allowed=('/sub-accounts','/v1/prop/packages','/v1/prop/user/packages/history',
            '/v1/account/balances-detail','/v1/account/fee')
        if path not in allowed and not re.fullmatch(r'/v1/prop/packages/[1-9][0-9]{0,11}',path):
            raise ValueError('READ_PATH_NOT_ALLOWED')
        key=os.environ.get('WALLEX_API_KEY','')
        if not key:raise ValueError('WALLEX_API_KEY_UNSET')
        if account is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',account):raise ValueError('INVALID_ACCOUNT_ID')
        headers={'x-api-key':key,'Accept':'application/json'}
        if account is not None:headers['sub-account-client-id']=account
        self.requests+=1
        try:
            response=requests.get('https://api.wallex.ir'+path,headers=headers,params=params,
                timeout=(5,15),allow_redirects=False)
            if key.encode() in response.content:raise ValueError('CREDENTIAL_ECHO_NOT_STORED')
            if response.status_code!=200:raise ValueError('READ_HTTP_STATUS_'+str(response.status_code))
            payload=response.json(parse_float=str)
            if not isinstance(payload,dict) or payload.get('success') is not True:raise ValueError('READ_SCHEMA_UNVERIFIED')
        except requests.RequestException:raise ValueError('READ_NETWORK_FAILURE_NO_RETRY') from None
        # Exact response bytes and provenance, no request headers or key hash.
        name='response_'+str(self.requests).zfill(3)+'.json'
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/name).write_bytes(response.content)
        _save_atomic(self.folder/(name+'.receipt'),{'path':path,'params':params,'account_client_id':account,
            'observed_epoch':time.time(),'response_sha256':hashlib.sha256(response.content).hexdigest()})
        return payload


def discover(root,*,client_id=None,package_id=None,organizer_allowlist=None):
    root=Path(root).resolve()
    if client_id is None:client_id=os.environ.get('WALLEX_SUB_ACCOUNT_CLIENT_ID') or None
    result={'schema':'ATLAS_READ_ONLY_ACCOUNT_DISCOVERY_V1','observed_epoch':time.time(),
        'status':'BLOCKED_KEY_UNSET','key_environment_present':bool(os.environ.get('WALLEX_API_KEY')),
        'contest_identity':'UNVERIFIED','contest_credit':'UNVERIFIED_NOT_INFERRED_FROM_AMOUNT',
        'trade_permission':'UNVERIFIED_NO_DOCUMENTED_READ_PROOF_NO_PROBING_ORDER',
        'package_account_binding':'UNVERIFIED','organizer_allowlist':'NOT_SUPPLIED',
        'market_limits':'UNVERIFIED_PUBLIC_PRECISION_IS_NOT_TICK_LOT_MINIMUM',
        'LIVE':'HARD_DISABLED','orders_sent':0,'requests':0,'errors':[]}
    if not result['key_environment_present']:return result
    if not root.is_relative_to((Path(__file__).resolve().parents[1]/'atlas_store').resolve()):
        result['status']='BLOCKED_PRIVATE_OUTPUT_MUST_STAY_IN_IGNORED_ATLAS_STORE';return result
    folder=root/'operations/account_discovery'/str(time.time_ns());reader=AccountReader(folder)
    def read(label,path,**kwargs):
        try:return reader.get(path,**kwargs)
        except ValueError as exc:
            # Only fixed local error codes, never remote exception/request text.
            result['errors'].append({'read':label,'reason':str(exc) if str(exc).startswith(('READ_','CREDENTIAL_','WALLEX_','INVALID_')) else 'UNVERIFIED_RESPONSE'})
            return None
    p=read('subaccounts','/sub-accounts');accounts=[]
    if p:
        try:accounts=object_rows(p.get('result'),'clientId')
        except ValueError:result['errors'].append({'read':'subaccounts','reason':'UNVERIFIED_COLLECTION'})
    result['subaccounts']=[{k:a.get(k) for k in ('clientId','type','isActive','isSuspend','packageId','package_id')} for a in accounts]
    active=[a for a in accounts if a.get('type')=='prop' and a.get('isActive') is True and a.get('isSuspend') is False]
    if client_id is None and len(active)==1:
        client_id=active[0].get('clientId');result['selection']='SOLE_ACTIVE_PROP_READ_TARGET_NOT_CONTEST_AUTHORIZATION'
    matches=[a for a in active if a.get('clientId')==client_id]
    if not isinstance(client_id,str) or len(matches)!=1:
        result['status']='BLOCKED_AMBIGUOUS_OR_INACTIVE_SUBACCOUNT'
    else:
        result['status']='ACCOUNT_READ_ATTEMPTED_NOT_LIVE_AUTHORIZATION';result['account_client_id']=client_id
        default_balance=read('key_default_account_balances','/v1/account/balances-detail')
        default_tmn=None
        if default_balance:
            try:
                totals,available=ControlledSpotBroker._balances(default_balance)
                default_tmn={'available':str(available['TMN']),'total':str(totals['TMN']),
                    'frozen':str(totals['TMN']-available['TMN'])}
                result['key_default_context_tmn']=default_tmn
            except (ValueError,RuntimeError):result['errors'].append({'read':'key_default_account_balances','reason':'BALANCE_CONSERVATION_OR_SCHEMA_FAILED'})
        # Never substitute unscoped ordinary wallet balances for credit balances.
        balance=read('account_balances','/v1/account/balances-detail',account=client_id)
        if balance:
            try:
                totals,available=ControlledSpotBroker._balances(balance)
                result['account_scoped_tmn']={'available':str(available['TMN']),'total':str(totals['TMN']),
                    'frozen':str(totals['TMN']-available['TMN']),'contest_classification':'UNVERIFIED'}
            except (ValueError,RuntimeError):result['errors'].append({'read':'account_balances','reason':'BALANCE_CONSERVATION_OR_SCHEMA_FAILED'})
        result['key_account_context_check']=compare_balance_contexts(default_tmn,result.get('account_scoped_tmn'))
        fees=read('account_fees','/v1/account/fee',account=client_id)
        if fees:
            try:
                rates={}
                for symbol,item in fees['result'].items():
                    if isinstance(symbol,str) and symbol.endswith('TMN'):
                        rates[symbol]={k:str(decimal(item[k],zero=True)) for k in ('makerFeeRate','takerFeeRate')}
                        if any(decimal(v,zero=True)>=decimal('0.1') for v in rates[symbol].values()):raise ValueError('INVALID_FEE')
                result['account_scoped_fees']=rates
            except (ValueError,KeyError,TypeError,AttributeError):result['errors'].append({'read':'account_fees','reason':'INVALID_FEE_SCHEMA'})
        declared={str(a[k]) for a in matches for k in ('packageId','package_id') if a.get(k) is not None}
        if len(declared)==1 and next(iter(declared)).isdigit():
            observed=int(next(iter(declared)))
            if package_id is None:package_id=observed
            if package_id==observed:result['package_account_binding']='EXPLICIT_SUBACCOUNT_RESPONSE_FIELD_NOT_ORGANIZER_IDENTITY'
    packages=read('package_catalog','/v1/prop/packages')
    if packages:
        try:result['package_candidates']=[{k:p.get(k) for k in ('id','title','status','currency','destination_currency')} for p in object_rows(packages.get('result'),'id')]
        except ValueError:result['errors'].append({'read':'package_catalog','reason':'UNVERIFIED_COLLECTION'})
    # Bounded history discovery; do not claim complete if pagination remains.
    history=read('package_history','/v1/prop/user/packages/history',params={'page':1,'per_page':100})
    if (history is None and len(matches)==1 and result['errors'][-1:]==[{'read':'package_history','reason':'READ_HTTP_STATUS_401'}]):
        # One explicit read-only alternate context, not a credential retry loop.
        history=read('package_history_subaccount_context','/v1/prop/user/packages/history',
            account=client_id,params={'page':1,'per_page':100})
        result['history_subaccount_context_read_succeeded']=history is not None
    if history:
        try:
            rows=object_rows(history.get('result'),'client_id')
            result['matching_history']=[{k:r.get(k) for k in ('client_id','package_id','package_title','status','loan','start_balance','expire_at','finished_at')} for r in rows if r.get('client_id')==client_id]
            info=history.get('result_info') or {}
            result['history_complete']=type(info.get('total_count')) is int and info['total_count']<=len(rows)
            # A history title is never used as account/package proof.
        except ValueError:result['errors'].append({'read':'package_history','reason':'UNVERIFIED_COLLECTION'})
    if package_id is not None:
        if type(package_id) is not int or not 0<package_id<10**12:raise ValueError('INVALID_EXPLICIT_PACKAGE_ID')
        p=read('package_details','/v1/prop/packages/'+str(package_id));result['requested_package_id']=package_id
        if p:
            detail=p.get('result',{});blocked=detail.get('unavailableMarkets')
            if isinstance(blocked,list) and all(isinstance(s,str) for s in blocked):
                result['package_unavailable_markets']=blocked
                result['package_detail_id']=detail.get('detail',{}).get('id')
                result['package_title']=detail.get('detail',{}).get('title')
                if organizer_allowlist:
                    from .wallex_api import read_organizer_allowlist
                    from .market import markets
                    allowed=read_organizer_allowlist(organizer_allowlist)
                    spot={m['symbol'] for m in markets() if m.get('is_spot') is True and m.get('quote_asset')=='TMN'}
                    result['organizer_allowlist']='EXPLICIT_LOCAL_FILE_NOT_INDEPENDENTLY_AUTHENTICATED'
                    result['candidate_allowed_markets']=sorted(set(allowed)&spot-set(blocked))
                    result['markets_are_live_authorized']=False
            else:result['errors'].append({'read':'package_details','reason':'UNVERIFIED_RESTRICTIONS'})
    result['requests']=reader.requests;result['private_evidence_directory']=str(folder)
    _save_atomic(folder/'result.json',result)
    _save_atomic(root/'operations/account_discovery_latest.json',{'result':str(folder/'result.json'),'observed_epoch':result['observed_epoch']})
    return result


def public_summary(result):
    result={**result};result.pop('subaccounts',None);result.pop('matching_history',None)
    identity=result.pop('account_client_id',None)
    result['account_id_observed']=identity is not None
    result['account_identity_fingerprint']=hashlib.sha256(identity.encode()).hexdigest()[:12] if identity else None
    # Full private records remain local. Avoid dumping hundreds of fee/market
    # entries into chat merely to diagnose the account context.
    fees=result.get('account_scoped_fees',{})
    if fees:
        result['fee_market_count']=len(fees)
        result['account_scoped_fees']={s:fees[s] for s in ('BTCTMN','ETHTMN') if s in fees}
    blocked=result.pop('package_unavailable_markets',None)
    if blocked is not None:
        result['package_unavailable_market_count']=len(blocked)
        result['selected_market_package_checks']={s:{'package_blocked':s in blocked,'organizer_authorization':'UNVERIFIED'} for s in ('BTCTMN','ETHTMN')}
    candidates=result.pop('package_candidates',None)
    if candidates is not None:result['package_candidate_ids']=[p.get('id') for p in candidates]
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default='atlas_store')
    p.add_argument('--client-id');p.add_argument('--package-id',type=int);p.add_argument('--organizer-allowlist')
    a=p.parse_args()
    try:result=discover(a.root,client_id=a.client_id,package_id=a.package_id,organizer_allowlist=a.organizer_allowlist)
    except Exception as exc:result={'status':'READ_DISCOVERY_BLOCKED','error_type':type(exc).__name__,'LIVE':'HARD_DISABLED'}
    print(json.dumps(public_summary(result),ensure_ascii=False))


if __name__=='__main__':main()
