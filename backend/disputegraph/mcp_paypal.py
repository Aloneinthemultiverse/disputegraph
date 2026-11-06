"""PayPal MCP server (official @paypal/mcp, Agent Toolkit) as a data source.

The PayPal Analyst fetches disputes through the MCP `get_dispute` tool when
PAYPAL_USE_MCP=1, so the same tools an AI agent would use are the ones that
feed the investigation. Orders/captures still come from REST. The server is
started over stdio with a short-lived sandbox access token (never the secret).

Requires Node.js (npx) and the `mcp` Python package.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil

import requests


def enabled() -> bool:
    return os.environ.get("PAYPAL_USE_MCP") == "1" and os.environ.get("DEMO_MODE") != "1" \
        and bool(shutil.which("npx") or shutil.which("npx.cmd"))


def _token(base: str) -> str:
    r = requests.post(f"{base}/v1/oauth2/token", timeout=30,
                      auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
                      data={"grant_type": "client_credentials"})
    r.raise_for_status()
    return r.json()["access_token"]


async def _call(tool: str, args: dict, base: str) -> tuple[dict, list[str]]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "PAYPAL_ACCESS_TOKEN": _token(base), "PAYPAL_ENVIRONMENT": "SANDBOX"}
    cmd = "npx.cmd" if os.name == "nt" else "npx"
    params = StdioServerParameters(command=cmd, args=["-y", "@paypal/mcp", "--tools=all"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            res = await s.call_tool(tool, args)
            return json.loads(res.content[0].text), names


def call(tool: str, args: dict, base: str) -> tuple[dict, list[str]]:
    """Run one MCP tool call; returns (result, available tool names)."""
    return asyncio.run(_call(tool, args, base))
