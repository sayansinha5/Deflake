"""One read-only Tendem connectivity call. Does not create a task.

Documented server: https://mcp.tendem.ai/mcp with Authorization: ApiKey.
Uses TENDEM_MCP_URL when set, otherwise that documented URL.

    docker compose -f backend/docker-compose.yml exec api python scripts/tendem_ping.py
"""
import json
import os
import sys

import httpx

DOCUMENTED_URL = "https://mcp.tendem.ai/mcp"
PROTOCOL = "2025-03-26"


def _post(client: httpx.Client, url: str, payload: dict, session: str | None) -> httpx.Response:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    # Post the absolute URL. A base URL that already contains /mcp drops that path.
    return client.post(url, json=payload, headers=headers)


def _body(response: httpx.Response) -> dict:
    text = response.text.strip()
    if text.startswith("{"):
        return response.json()
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {"raw": text[:240]}


def main() -> int:
    key = os.environ.get("TENDEM_API_KEY") or ""
    url = (os.environ.get("TENDEM_MCP_URL") or DOCUMENTED_URL).rstrip("/")
    used_default = not os.environ.get("TENDEM_MCP_URL")
    if not key:
        print("TENDEM_API_KEY is not set; skipped")
        return 1
    print(f"url host set, default_url={used_default}")
    with httpx.Client(headers={"Authorization": f"ApiKey {key}"}, timeout=45.0) as client:
        init = _post(client, url, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                       "clientInfo": {"name": "deflake", "version": "0.1.0"}},
        }, None)
        print(f"initialize HTTP {init.status_code}")
        if init.status_code >= 400:
            print("body:", init.text[:240])
            return 1
        session = init.headers.get("mcp-session-id")
        body = _body(init)
        server = (body.get("result") or {}).get("serverInfo") or {}
        print(f"server={server.get('name', '?')} version={server.get('version', '?')}")
        _post(client, url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
        call = _post(client, url, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "get_account", "arguments": {}},
        }, session)
        print(f"get_account HTTP {call.status_code}")
        result = _body(call)
        if "error" in result:
            print("error:", json.dumps(result["error"])[:300])
            return 1
        content = (result.get("result") or {}).get("content") or []
        text = content[0].get("text", "") if content else json.dumps(result.get("result"))[:200]
        # Balance only; do not print account emails or raw payloads.
        print("get_account returned", "non-empty" if text else "empty", f"chars={len(text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
