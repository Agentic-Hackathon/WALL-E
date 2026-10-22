"""Minimal, allowlisted Wallex API client. Read-only by design. No withdrawal/order methods.

The private key must belong to the intended account. This module never creates
an account, activates a credit package, transfers money, or places an order.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import requests
from .market import HOST

class WallexAPIError(RuntimeError):
    pass

class WallexReadClient:
    """No arbitrary URL/path method: endpoint allowlist is part of security boundary."""
    def __init__(self,api_key: str | None=None,session=None):
        self._api_key=api_key if api_key is not None else os.environ.get('WALLEX_API_KEY','')
        self._session=session if session is not None else requests.Session()

    def _read(self,path:str)->dict:
        if not self._api_key:
            raise WallexAPIError('WALLEX_API_KEY is unset (set locally; never paste or commit it)')
        try:
            r=self._session.get(HOST+path,headers={'x-api-key':self._api_key,
                    'Accept':'application/json'},timeout=(5,15))
            r.raise_for_status()
            data=r.json()
        except (requests.RequestException,ValueError) as exc:
            # Do not print request objects / headers; may contain the API key.
            raise WallexAPIError('Private Wallex read failed; check key/account/network/status') from None
        if not isinstance(data,dict) or data.get('success') is False:
            raise WallexAPIError('Wallex returned unsuccessful response for read-only endpoint')
        return data

    def sub_accounts(self)->list[dict]:
        out=self._read('/sub-accounts').get('result')
        if not isinstance(out,list):
            raise WallexAPIError('Unexpected sub-account response shape')
        return [{'title':x.get('title'), 'clientId':x.get('clientId'),
                 'type':x.get('type'),'isActive':x.get('isActive'),
                 'isSuspend':x.get('isSuspend')} for x in out]

    def balances_detail(self)->dict:
        result=self._read('/v1/account/balances-detail').get('result')
        if not isinstance(result,dict):
            raise WallexAPIError('Unexpected balances-detail response shape')
        return {coin:{'available':item.get('available'), 'total':item.get('total'),
                      'freeze':item.get('freeze')} for coin,item in result.items()
                if isinstance(item,dict)}

    def package_details(self,package_id:int)->dict:
        if not 0<package_id<10**12:raise ValueError('Invalid package id')
        out=self._read(f'/v1/prop/packages/{package_id}').get('result')
        if not isinstance(out,dict) or not isinstance(out.get('unavailableMarkets'),list):
            raise WallexAPIError('Unexpected package-detail response shape')
        return {'id':package_id,'detail':out.get('detail',{}),
                'unavailableMarkets':out['unavailableMarkets']}


def account_connection_status(package_id: int | None=None)->dict:
    """Optional allowlisted private-read diagnostic; never exposes the API key.

    Fee and contest-credit classification are reported as unknown unless an
    explicitly documented read-only response provides them.  In particular this
    function never reads arbitrary local files such as pass.txt.
    """
    if not os.environ.get('WALLEX_API_KEY'):
        return {'status':'WALLEX_API_KEY_UNSET','connection':'NOT_ATTEMPTED','live_execution':'HARD_DISABLED',
                'fee_status':'NOT_AVAILABLE_WITHOUT_READ_RESPONSE','contest_credit_status':'UNKNOWN'}
    client=WallexReadClient();result={'status':'READ_ONLY_CHECK','live_execution':'HARD_DISABLED',
        'fee_status':'NOT_AVAILABLE_NO_ALLOWLISTED_FEE_READ_ENDPOINT','contest_credit_status':'UNKNOWN_NOT_INFERRED_FROM_BALANCE'}
    try:
        accounts=client.sub_accounts()
        result['connection']='SUCCESS_READ_ONLY'
        result['subaccounts']=[{'type':x.get('type'),'active':x.get('isActive'),'suspended':x.get('isSuspend')}
                               for x in accounts]
    except WallexAPIError as exc:
        result['connection']='FAILED_READ_ONLY';result['connection_error']=str(exc);return result
    try:
        balances=client.balances_detail();tmn=balances.get('TMN',{})
        result['tmn_available']=tmn.get('available');result['tmn_total']=tmn.get('total')
    except WallexAPIError as exc:
        result['balances_status']='UNAVAILABLE';result['balances_error']=str(exc)
    if package_id is not None:
        try:
            detail=client.package_details(package_id)
            result['package_read_status']='SUCCESS_READ_ONLY'
            result['package_unavailable_market_count']=len(detail['unavailableMarkets'])
            result['contest_credit_status']='PACKAGE_DETAILS_READ__BALANCE_CLASSIFICATION_STILL_UNKNOWN'
        except (WallexAPIError,ValueError) as exc:
            result['package_read_status']='FAILED_READ_ONLY';result['package_error']=str(exc)
    return result


def read_organizer_allowlist(path: str | Path)->list[str]:
    import json
    if not Path(path).is_file():
        raise ValueError('Organizer allowlist is not published/available; fail closed')
    info=json.loads(Path(path).read_text(encoding='utf-8'))
    allow=info.get('markets')
    if not isinstance(allow,list) or not allow or any(not isinstance(x,str) or not x.isalnum() or x!=x.upper() for x in allow):
        raise ValueError('Organizer allowlist is missing, empty or malformed: fail closed')
    return allow


def market_authorization(symbol:str,allowlist_path:str,package_id:int,api:WallexReadClient|None=None)->dict:
    """Combines organizer approval + public spot metadata + package market restrictions."""
    from .market import markets
    allowed=read_organizer_allowlist(allowlist_path)
    public=next((x for x in markets() if x.get('symbol')==symbol),None)
    details=(api or WallexReadClient()).package_details(package_id)
    unavailable=details['unavailableMarkets']
    if any(not isinstance(x,str) for x in unavailable):
        raise WallexAPIError('Unexpected unavailableMarkets items; cannot certify')
    checks={'organizer_approved':symbol in allowed,
            'spot':bool(public and public.get('is_spot') is True),
            'tmn_quote':bool(public and public.get('quote_asset')=='TMN' and public.get('is_tmn_based') is True),
            'package_market_available':symbol not in unavailable}
    return {'symbol':symbol,'package_id':package_id,'checks':checks,'all_passed':all(checks.values()),
            'note':'Checks are read-only; do not prove that the API key belongs to contest sub-account.'}
