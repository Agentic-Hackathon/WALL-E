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
