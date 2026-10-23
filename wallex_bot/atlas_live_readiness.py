"""Read-only readiness, never ARM or send order/cancel/withdrawal requests.

Existing allowlisted account API retained. Unknown contest authorization cannot
be replaced by ordinary wallet funds. Private evidence stays in ignored store.
"""
import argparse,json,os
from pathlib import Path
from .atlas_deadline import schedule

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

def discovery_readiness(result):
    """Actual read results are observations, never execution authorization.

    Reuses atlas_account_discovery and official spot-intro contracts. Original
    glue; no external source copied. Failed reads never reuse an older success.
    """
    from .atlas_account_discovery import public_summary
    summary=public_summary(result);public=readiness()
    public.update(private_read_performed=result.get('requests',0)>0,
        observed_epoch=result.get('observed_epoch'),
        private_evidence_stored_locally=bool(result.get('private_evidence_directory')),
        connection='SUCCESS_READ_ONLY' if result.get('account_scoped_tmn') else 'READ_NOT_CONFIRMED',
        account_identity_fingerprint=summary.get('account_identity_fingerprint'),
        observed_account_tmn=result.get('account_scoped_tmn'),
        observed_selected_fees=summary.get('account_scoped_fees',{}),
        account_context_comparison=result.get('key_account_context_check'),
        package_read={'requested_id':result.get('requested_package_id'),
                      'returned_id':result.get('package_detail_id'),
                      'account_binding':result.get('package_account_binding'),
                      'selected_markets':summary.get('selected_market_package_checks',{})},
        read_errors=result.get('errors',[]))
    if result.get('account_scoped_fees',{}).get('BTCTMN'):
        public['checks']['verified_fee']='OBSERVED_ACCOUNT_SCOPED_FEE_NOT_PACKAGE_BINDING_PROOF'
    public['checks']['contest_identity']='ACTIVE_PROP_READ_NOT_CONTEST_IDENTITY_PROOF' if summary.get('account_id_observed') else 'BLOCKED_ACCOUNT_READ_UNCONFIRMED'
    public['checks']['package_order_permissions']=result.get('trade_permission','UNVERIFIED')
    public['execution_blockers']={
        'ACCOUNT_PACKAGE_BINDING':'Account-linked package evidence is required; matching balances/title are insufficient.',
        'SPOT_MARKET_RULES':'Authoritative BTC/TMN tick, step, minimum quantity and notional are required; precision alone is insufficient.',
        'FINANCIAL_QUALIFICATION':'Broker requires reviewed independent financial evidence. Never fabricate a real-fill certificate to bootstrap a first order.',
        'SESSION_ARM':'Reviewed authorization must bind account, source/session, deadline and operator capital cap including fees; explicit local ARM follows.',
        'FRESH_CLOCK_QUOTE_AND_RISK':'Each mutation requires fresh verified clock, real quote and unchanged RiskGate approval.'}
    public['automatic_arm_or_order']=False
    return public


def private_check(root,package_id=None):
    from .atlas_account_discovery import discover
    return discovery_readiness(discover(root,package_id=package_id))


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--private-read',action='store_true')
    p.add_argument('--package-id',type=int)
    p.add_argument('--env-file',help='Explicit workspace .env only; never printed or automatically discovered.')
    a=p.parse_args()
    if a.env_file:
        path=Path(a.env_file).resolve()
        if path!=Path(__file__).resolve().parents[1]/'.env':p.error('ONLY_WORKSPACE_LOCAL_ENV_ALLOWED')
        from dotenv import load_dotenv
        load_dotenv(path,override=False)
    print(json.dumps(private_check(a.root,a.package_id) if a.private_read else readiness()))

if __name__=='__main__':main()
