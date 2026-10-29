import json
import time
from typing import Any

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings
from app.llm.fixtures import BY_SCHEMA
from app.llm.routing import Tier, model_id
from app.llm.usage import assert_budget, record_call
from app.security.redact import redact

log = structlog.get_logger()

STRUCTURED_METHODS = ("json_schema", "json_mode", "parse")


class StructuredCallError(RuntimeError):
    pass


def _is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in {429, 500, 502, 503, 504}:
        return True
    blob = f"{type(exc).__name__} {exc}".lower()
    return any(word in blob for word in ("timeout", "rate limit", "overloaded", "temporar"))


def _as_messages(messages: list) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for item in messages:
        if isinstance(item, BaseMessage):
            content = item.content if isinstance(item.content, str) else str(item.content)
            out.append(item.__class__(content=redact(content)))
            continue
        role, content = item.get("role", "user"), redact(item.get("content") or "")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def _usage_from(result: Any) -> tuple[int, int]:
    meta = getattr(result, "usage_metadata", None) or {}
    if meta:
        return int(meta.get("input_tokens") or 0), int(meta.get("output_tokens") or 0)
    response = getattr(result, "response_metadata", None) or {}
    usage = response.get("token_usage") or response.get("usage") or {}
    return (
        int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
    )


def _raw_text(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, list):
        return "".join(
            block.get("text", str(block)) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _parse_schema(schema: type[BaseModel], text: str) -> BaseModel:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return schema.model_validate_json(text)


def build_chat_model(settings: Settings, tier: Tier, temperature: float):
    """The only place a model client is constructed."""
    if settings.ai_provider == "fake":
        return None
    model = model_id(settings, tier)
    timeout = settings.ai_request_timeout_s
    api_key = settings.ai_api_key.get_secret_value() if settings.ai_api_key else None
    if settings.ai_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model, api_key=api_key, base_url=settings.ai_base_url,
            temperature=temperature, timeout=timeout, max_retries=0,
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model, api_key=api_key, base_url=settings.ai_base_url,
        temperature=temperature, timeout=timeout, max_retries=0,
    )


class Llm:
    def __init__(self, settings: Settings, session_factory=None) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def _methods(self) -> list[str]:
        preferred = self.settings.ai_structured_output_method
        return [preferred, *[m for m in STRUCTURED_METHODS if m != preferred]]

    def _trace_config(self, node: str, tier: str, prompt_version: str,
                      run_id: str | None, flake_id: str | None, method: str) -> dict:
        return {
            "tags": [f"tier:{tier}", f"node:{node}", f"method:{method}"],
            "metadata": {
                "run_id": run_id, "flake_id": flake_id, "node": node, "tier": tier,
                "prompt_version": prompt_version,
            },
        }

    async def structured(
        self,
        schema: type[BaseModel],
        messages: list,
        *,
        tier: Tier,
        node: str,
        temperature: float | None = None,
        run_id: str | None = None,
        flake_id: str | None = None,
        prompt_version: str = "unversioned",
    ) -> BaseModel:
        temperature = self.settings.ai_temperature_default if temperature is None else temperature
        bound = _as_messages(messages)
        if self.settings.ai_provider == "fake":
            model_name = "fake"
        else:
            model_name = model_id(self.settings, tier)
        started = time.perf_counter()
        error_type = None
        status = "ok"
        parsed: BaseModel | None = None
        in_tok = out_tok = 0

        if run_id and self.session_factory is not None:
            async with self.session_factory() as session:
                await assert_budget(session, run_id, self.settings.ai_run_budget_usd)

        try:
            if self.settings.ai_provider == "fake":
                payload = dict(BY_SCHEMA.get(schema.__name__) or {"ok": True})
                if "tier" in getattr(schema, "model_fields", {}):
                    payload["tier"] = tier
                parsed = schema.model_validate(payload)
            else:
                parsed, in_tok, out_tok = await self._call_with_fallback(
                    schema, bound, tier, temperature, node, prompt_version, run_id, flake_id
                )
            return parsed
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            raise
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            if self.session_factory is not None:
                async with self.session_factory() as session:
                    await record_call(
                        session, run_id=run_id, flake_id=flake_id, node=node, tier=tier,
                        model=model_name, prompt_version=prompt_version,
                        input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
                        status=status, error_type=error_type, settings=self.settings,
                    )
                    await session.commit()
            log.info(
                "llm_call", node=node, tier=tier, model=model_name, status=status,
                input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
            )

    async def complete(
        self,
        messages: list,
        *,
        tier: Tier,
        node: str,
        temperature: float | None = None,
        run_id: str | None = None,
        flake_id: str | None = None,
        prompt_version: str = "unversioned",
    ) -> str:
        """Plain text from one tier. Used for the expert summary, not for JSON."""
        temperature = self.settings.ai_temperature_default if temperature is None else temperature
        bound = _as_messages(messages)
        if self.settings.ai_provider == "fake":
            model_name = "fake"
        else:
            model_name = model_id(self.settings, tier)
        started = time.perf_counter()
        error_type = None
        status = "ok"
        in_tok = out_tok = 0
        text = ""
        if run_id and self.session_factory is not None:
            async with self.session_factory() as session:
                await assert_budget(session, run_id, self.settings.ai_run_budget_usd)
        try:
            if self.settings.ai_provider == "fake":
                text = (
                    "The test fails intermittently and the automatic fix was not proven.\n"
                    "Question: What is the smallest change that removes this flake?"
                )
            else:
                client = build_chat_model(self.settings, tier, temperature)
                config = self._trace_config(
                    node, tier, prompt_version, run_id, flake_id, "text",
                )
                retrying = AsyncRetrying(
                    retry=retry_if_exception(_is_retryable),
                    stop=stop_after_attempt(self.settings.ai_max_retries + 1),
                    wait=wait_exponential(multiplier=1, min=1, max=20),
                    reraise=True,
                )
                async for attempt in retrying:
                    with attempt:
                        if attempt.retry_state.attempt_number > 1:
                            await self._note_capacity(run_id)
                        result = await client.ainvoke(bound, config=config)
                        text = _raw_text(result).strip()
                        in_tok, out_tok = _usage_from(result)
                        if not text:
                            raise StructuredCallError("model returned empty text")
            return text
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            raise
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            if self.session_factory is not None:
                async with self.session_factory() as session:
                    await record_call(
                        session, run_id=run_id, flake_id=flake_id, node=node, tier=tier,
                        model=model_name, prompt_version=prompt_version,
                        input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
                        status=status, error_type=error_type, settings=self.settings,
                    )
                    await session.commit()
            log.info(
                "llm_call", node=node, tier=tier, model=model_name, status=status,
                input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
            )

    async def _call_with_fallback(self, schema, messages, tier, temperature, node,
                                  prompt_version, run_id, flake_id):
        client = build_chat_model(self.settings, tier, temperature)
        last_error: Exception | None = None
        for method in self._methods():
            try:
                return await self._invoke(
                    client, schema, messages, method, node, prompt_version, run_id, flake_id, tier
                )
            except Exception as exc:
                last_error = exc
                log.warning("structured_method_failed", method=method, error=type(exc).__name__)
        raise StructuredCallError(
            f"All structured-output methods failed: {last_error}"
        ) from last_error

    async def _invoke(self, client, schema, messages, method, node, prompt_version,
                      run_id, flake_id, tier) -> tuple[BaseModel, int, int]:
        config = self._trace_config(node, tier, prompt_version, run_id, flake_id, method)
        retrying = AsyncRetrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self.settings.ai_max_retries + 1),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    await self._note_capacity(run_id)
                if method == "parse":
                    return await self._parse_invoke(client, schema, messages, config)
                runnable = client.with_structured_output(schema, method=method, include_raw=True)
                packed = await runnable.ainvoke(messages, config=config)
                if isinstance(packed, dict) and "parsed" in packed:
                    parsed, raw = packed["parsed"], packed.get("raw")
                    if parsed is None:
                        raise StructuredCallError("model returned no structured object")
                    if raw is None:
                        return parsed, 0, 0
                    return parsed, *_usage_from(raw)
                if isinstance(packed, BaseModel):
                    return packed, 0, 0
                raise StructuredCallError("unexpected structured-output payload")
        raise StructuredCallError("retries exhausted")

    async def _note_capacity(self, run_id: str | None) -> None:
        if not run_id or self.session_factory is None:
            return
        from app.db.models import Run
        from app.services.events import append_event

        async with self.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None:
                return
            await append_event(session, run, "log.line", {
                "level": "warning", "message": "Waiting for model capacity",
            })
            await session.commit()

    async def _parse_invoke(self, client, schema, messages, config) -> tuple[BaseModel, int, int]:
        extra = HumanMessage(
            content=redact("Reply with JSON only that matches this schema:\n"
                           + json.dumps(schema.model_json_schema()))
        )
        result = await client.ainvoke([*messages, extra], config=config)
        try:
            parsed = _parse_schema(schema, _raw_text(result))
        except ValidationError:
            repair = HumanMessage(
                content="Last reply was not valid JSON for the schema. Reply with JSON only."
            )
            result = await client.ainvoke([*messages, extra, result, repair], config=config)
            parsed = _parse_schema(schema, _raw_text(result))
        return parsed, *_usage_from(result)
