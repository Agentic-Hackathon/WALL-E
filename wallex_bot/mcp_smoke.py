"""Smoke-test MCP stdio handshake and list_tools; NEVER calls trading tools.

Starts a child MCP server and checks protocol negotiation. This deliberately
returns only the tool names; does not print or store credentials or balances.
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

async def probe(timeout_seconds: float = 25.):
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError('Install MCP: python -m pip install "mcp==1.30.0"') from exc
    root = str(Path(__file__).resolve().parent.parent)
    # Do NOT pass the account API key into a protocol handshake-only child.
    env={k:v for k,v in os.environ.items() if k not in ('WALLEX_API_KEY','WALLEX_MCP_TOKEN')}
    prior=env.get('PYTHONPATH','')
    env['PYTHONPATH']=root+(os.pathsep+prior if prior else '')
    params=StdioServerParameters(command=sys.executable,
                                 args=['-m','wallex_bot.mcp_server'],env=env)
    async with asyncio.timeout(timeout_seconds):
        async with stdio_client(params) as (reader,writer):
            async with ClientSession(reader,writer) as session:
                initialized=await session.initialize()
                response=await session.list_tools()
                names=sorted(t.name for t in response.tools)
                if not names:raise RuntimeError('MCP handshake succeeded but tools/list empty')
                return {'handshake':True,'server_name':str(initialized.serverInfo.name),
                        'tools_count':len(names),'tools':names,
                        'security':'NO TOOLS CALLED; API KEY NOT FORWARDED TO CHILD'}

def run():
    return asyncio.run(probe())
