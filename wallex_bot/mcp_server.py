"""Locally hosted MCP *adapter* backed by the official Wallex API.

Not advertised as an official Wallex-hosted MCP server.  All tools are read-only.
Tools never expose the API key and no tool can place orders, transfer or withdraw.
Run: python -m wallex_bot.mcp_server
"""
from __future__ import annotations
import time
from .market import markets,depth,candles,complete_only,ALLOWED_RESOLUTIONS
from .wallex_api import WallexReadClient

def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError('Install optional MCP SDK: python -m pip install "mcp==1.30.0"') from exc
    server=FastMCP('wallex-challenge-read-only')

    @server.tool()
    def wallex_spot_markets()->list[dict]:
        """Read exchange public markets; expose only spot metadata and symbols."""
        return [{'symbol':m.get('symbol'),'quote_asset':m.get('quote_asset'),
                 'is_spot':m.get('is_spot'),'is_tmn_based':m.get('is_tmn_based')}
                for m in markets() if m.get('is_spot') is True]

    @server.tool()
    def wallex_ohlcv(symbol:str,resolution:str='15',n_candles:int=100,resample_from:str='')->dict:
        """Read only CLOSED OHLCV with enforced timeframe checks. Max 300 rows."""
        if resolution not in ALLOWED_RESOLUTIONS or not (3<=n_candles<=300):
            raise ValueError('Invalid resolution/n_candles')
        now=int(time.time());secs=ALLOWED_RESOLUTIONS[resolution]
        df=candles(symbol,resolution,now-(n_candles+25)*secs,now,
                   resample_from=resample_from or None)
        frame=complete_only(df,resolution,now).tail(n_candles)
        return {'symbol':symbol,'resolution':resolution,'candles':frame.to_dict('records'),
                'n':len(frame)}

    @server.tool()
    def wallex_order_book(symbol:str)->dict:
        """Read public market depth. Never create an order."""
        return {'symbol':symbol,'book':depth(symbol)}

    @server.tool()
    def wallex_credit_sub_accounts()->list[dict]:
        """Read credit sub-account metadata through the locally configured API key."""
        return WallexReadClient().sub_accounts()

    @server.tool()
    def wallex_account_balances()->dict:
        """Read balances from account associated with locally configured key."""
        return WallexReadClient().balances_detail()

    @server.tool()
    def wallex_package_restrictions(package_id:int)->dict:
        """Read trading-credit package details and its unavailable markets."""
        return WallexReadClient().package_details(package_id)

    return server

def main():
    build_server().run(transport='stdio')

if __name__=='__main__':main()
