"""Tendem over the hosted MCP server.

Documented tools used here: create_task, get_task, get_task_result.
approve_task spends money and is never called.
"""
import json
import re

import httpx

from app.config import Settings
from app.integrations.escalation.base import (
    ProviderError,
    ProviderUnavailable,
    StatusResult,
    SubmitResult,
)
from app.security.redact import redact

DOCUMENTED_URL = "https://mcp.tendem.ai/mcp"
PROTOCOL = "2025-03-26"
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def text_of(result: dict) -> str:
    chunks: list[str] = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("text"):
            chunks.append(str(block["text"]))
        elif isinstance(block, str):
            chunks.append(block)
    return "\n".join(chunks).strip()


def _object(result: dict) -> dict:
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and structured:
        return structured
    text = text_of(result)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _task_id_in(value) -> str | None:
    if not isinstance(value, dict):
        return None
    if value.get("task_id"):
        return str(value["task_id"])
    for key in ("task", "data"):
        found = _task_id_in(value.get(key))
        if found:
            return found
    return None


def extract_task_id(result: dict) -> str | None:
    found = _task_id_in(result.get("structuredContent"))
    if found:
        return found
    text = text_of(result)
    try:
        parsed = json.loads(text) if text else None
    except json.JSONDecodeError:
        parsed = None
    found = _task_id_in(parsed)
    if found:
        return found
    match = _UUID.search(text)
    return match.group(0) if match else None


def map_status(result: dict) -> str:
    """Map a get_task payload onto submitted, in_progress, resolved, or failed."""
    payload = _object(result)
    action = str(payload.get("next_action") or "")
    raw = str(payload.get("status") or "").lower()
    if action == "fetch_result":
        return "resolved"
    if raw in {"submitted", "in_progress", "resolved", "failed"}:
        return raw
    if action.startswith("await"):
        return "in_progress"
    return "submitted"


def _decode(response: httpx.Response) -> dict:
    text = response.text.strip()
    if text.startswith("{"):
        return response.json()
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


class TendemProvider:
    name = "tendem"

    def __init__(self, settings: Settings, tool=None) -> None:
        self.settings = settings
        self._tool_override = tool

    async def submit(self, bundle: dict, idempotency_key: str) -> SubmitResult:
        test_id = str(bundle.get("test_id") or "flaky test")
        short = test_id.split("::")[-1][:80] or "flaky test"
        app = str(bundle.get("app") or "Deflake")
        description = str(bundle.get("text") or "")[:20000] or "Evidence bundle."
        payload = await self._tool("create_task", {
            "name": f"{app}: {short}"[:120],
            "description": description,
            "conversation_id": idempotency_key,
        })
        task_id = extract_task_id(payload)
        if not task_id:
            raise ProviderError("create_task returned no task_id")
        return SubmitResult(provider=self.name, external_ref=task_id, status="submitted")

    async def status(self, external_ref: str) -> StatusResult:
        payload = await self._tool("get_task", {
            "task_id": external_ref,
            "wait_for_change_seconds": 0,
        })
        mapped = map_status(payload)
        if mapped != "resolved":
            return StatusResult(status=mapped, response=None)
        try:
            fetched = await self._tool("get_task_result", {"task_id": external_ref})
        except (ProviderError, ProviderUnavailable):
            return StatusResult(status="in_progress", response=None)
        response = text_of(fetched) or None
        if not response:
            return StatusResult(status="in_progress", response=None)
        return StatusResult(status="resolved", response=redact(response)[:16000])

    async def _tool(self, name: str, arguments: dict) -> dict:
        if self._tool_override is not None:
            return await self._tool_override(name, arguments)
        return await self._mcp(name, arguments)

    async def _mcp(self, name: str, arguments: dict) -> dict:
        secret = self.settings.tendem_api_key
        if secret is None:
            raise ProviderUnavailable("Tendem is not configured.")
        url = (self.settings.tendem_mcp_url or DOCUMENTED_URL).rstrip("/")
        headers = {
            "Authorization": f"ApiKey {secret.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            init = await client.post(url, headers=headers, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "deflake", "version": "0.1.0"},
                },
            })
            if init.status_code >= 400:
                raise ProviderError(f"Tendem initialize HTTP {init.status_code}")
            session = init.headers.get("mcp-session-id")
            call_headers = dict(headers)
            if session:
                call_headers["Mcp-Session-Id"] = session
            noted = await client.post(url, headers=call_headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
            if noted.status_code >= 400:
                raise ProviderError(f"Tendem initialized HTTP {noted.status_code}")
            call = await client.post(url, headers=call_headers, json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            })
        if call.status_code >= 400:
            raise ProviderError(f"Tendem tools/call HTTP {call.status_code}")
        body = _decode(call)
        if body.get("error"):
            error = body["error"]
            message = error.get("message") if isinstance(error, dict) else "mcp error"
            raise ProviderError(redact(str(message))[:300])
        result = body.get("result") or {}
        if not isinstance(result, dict):
            raise ProviderError("Tendem tool result was not an object")
        if result.get("isError"):
            raise ProviderError(redact(text_of(result))[:300] or "tool error")
        return result
