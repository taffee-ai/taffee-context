"""Focused check: the per-caller rate limit actually triggers. Run against a dedicated low-limit instance
(RATE_LIMIT_PER_MINUTE=3), so it does not disturb the main test run's own call budget."""
import asyncio, os, ssl, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _insecure_client(headers=None, timeout=None, auth=None):
    import httpx
    kw = {"follow_redirects": True, "timeout": timeout or httpx.Timeout(30.0), "verify": False}
    if headers is not None:
        kw["headers"] = headers
    return httpx.AsyncClient(**kw)


async def main():
    async with streamablehttp_client(os.environ["MCP_URL"], headers={"Authorization": "Bearer " + os.environ["MCP_TOKEN"]},
                                     httpx_client_factory=_insecure_client) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            errs = []
            for i in range(5):
                res = await s.call_tool("list_repos", {})
                errs.append(bool(getattr(res, "isError", False)))
            ok = errs[:3] == [False, False, False] and any(errs[3:])
            print(("PASS" if ok else "FAIL") + f" rate limit trips after the configured count: {errs}", flush=True)
            return ok


sys.exit(0 if asyncio.run(main()) else 1)
