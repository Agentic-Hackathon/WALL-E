"""Read-only readiness, never ARM or send order/cancel/withdrawal requests.

Existing allowlisted account API retained. Unknown contest authorization cannot
be replaced by ordinary wallet funds. Private evidence stays in ignored store.
"""
import argparse,json,os,time
from pathlib import Path
from .atlas_deadline import schedule
from .wallex_api import account_connection_status,WallexReadClient,WallexAPIError

REQUIRED=('contest_identity','contest_credit','organizer_allowlist','verified_fee','spot_tick_step_minimum',
    'package_order_permissions','positive_financial_shadow_e2e','independent_net_oos_evidence','verified_live_transport','session_specific_operator_arm')

def readiness():
    return {'status':'LIVE_NOT_AUTHORIZED_OR_NOT_READY','LIVE':'HARD_DISABLED','operator_arm_available':False,
        'checks':{name:'BLOCKED_MISSING_VERIFIED_EVIDENCE' for name in REQUIRED},'deadline':schedule(),
        'key_environment_present':bool(os.environ.get('WALLEX_API_KEY')),'contest_balance_verified':False,
        'contest_balance_tmn':None,'ordinary_wallet_is_contest_credit':False,'orders_sent':0,'private_read_performed':False,
        'software':{'spot_decimal_preflight':'IMPLEMENTED_RESEARCH_ONLY','persistent_read_only_order_recovery':'IMPLEMENTED_NOT_VERIFIED_WITH_REAL_FILL_RECORDINGS',
                    'financial_post_delete_transport':'IMPLEMENTED_SEPARATE_CONTROLLED_SPOT_ADAPTER_NOT_EXCHANGE_VERIFIED','operator_arm':'IMPLEMENTED_LOCAL_INTERACTIVE_DEFAULT_DISARMED_NO_VERIFIED_AUTHORIZATION',
                    'independent_deadline_supervisor':'IMPLEMENTED_OBSERVER_NOT_INSTALLED_SERVICE',
                    'positive_real_fill_fee_and_conservation_e2e':'UNVERIFIED_NO_AUTHORIZED_RECORDINGS'}}

def private_check(root):
    result=account_connection_status()
    if not os.environ.get('WALLEX_API_KEY'):return readiness()
    try:result['verified_read_fee_rates']=WallexReadClient().fees()
    except WallexAPIError:result['fee_read_status']='UNAVAILABLE_OR_SCHEMA_UNVERIFIED'
    # Existing allowlisted read-only calls; credentials and response stay local.
    result['observed_epoch']=time.time()
    folder=Path(root)/'operations';folder.mkdir(parents=True,exist_ok=True)
    (folder/'private_account_read.json').write_text(json.dumps(result),encoding='utf-8')
    public=readiness();public.update(private_read_performed=True,connection=result.get('connection'),
        private_evidence_stored_locally=True,observed_epoch=time.time())
    return public

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--private-read',action='store_true');a=p.parse_args()
    print(json.dumps(private_check(a.root) if a.private_read else readiness()))

if __name__=='__main__':main()
