"""Optional probe of organizer-provided remote MCP endpoint; discovery only."""
from __future__ import annotations
import asyncio,os
from urllib.parse import urlsplit

async def _probe(url:str):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from contextlib import AsyncExitStack
    import httpx
    headers={}
    token=os.environ.get('WALLEX_MCP_TOKEN')
    if token:headers['Authorization']=f'Bearer {token}'
    async with httpx.AsyncClient(headers=headers,timeout=20,follow_redirects=False) as http:
        async with streamable_http_client(url,http_client=http) as (read,write,_):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools=await session.list_tools()
                return {'server':urlsplit(url).netloc,
                        'tools':[{'name':x.name,'description':(x.description or '')[:160]} for x in tools.tools]}

def remote_mcp_tools(url:str)->dict:
    p=urlsplit(url)
    if p.scheme!='https' or not p.netloc or p.username or p.password:
        raise ValueError('Remote MCP must have an explicitly configured HTTPS URL, without credentials in URL')
    return asyncio.run(_probe(url))
