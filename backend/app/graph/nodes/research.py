from urllib.parse import urlparse

from sqlalchemy import select

from app.db.models import Evidence, Flake, Reference, Run, utcnow
from app.graph.context import current_context
from app.graph.gates import gate
from app.graph.state import FlakeState
from app.graph.text import clean_query, error_signature, untrusted
from app.integrations.tavily import cached_search
from app.llm.prompts import prompt
from app.llm.schemas import ReferenceMatchOut, SearchQueryOut
from app.llm.usage import BudgetExceeded
from app.security.redact import redact
from app.services.events import append_event


def _site(url: str) -> str:
    return (urlparse(url).hostname or "")[:255]


async def research(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
    async with ctx.sessionmaker() as session:
        reason = await gate(session, ctx.settings, state["run_id"])
        if reason:
            return {"stopped": reason}
        existing = list(await session.scalars(
            select(Reference).where(Reference.flake_id == state["flake_id"])
        ))
        if existing:
            return {}
        flake = await session.get(Flake, state["flake_id"])
        evidence = await session.get(Evidence, state["flake_id"])
        run = await session.get(Run, state["run_id"])
        if flake is None or run is None:
            return {"stopped": "error"}
        await append_event(session, run, "step.started", {
            "step": "research", "flake_id": flake.id,
        })
        await session.commit()
        signature = error_signature(evidence.failing_samples if evidence else [])
        category = flake.category or "unknown"

    version, system = prompt("search")
    try:
        parsed = await ctx.llm.structured(
            SearchQueryOut,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": (
                    f"Category: {category}\n"
                    f"Error signature:\n{untrusted(signature)}"
                )},
            ],
            tier="fast", node="research", temperature=0.0,
            run_id=state["run_id"], flake_id=state["flake_id"], prompt_version=version,
        )
        query = clean_query(parsed.query, parsed.library)
    except BudgetExceeded:
        return {"stopped": "stopped_budget"}
    except Exception:
        query = signature
    unavailable = None
    try:
        results, _cached = await cached_search(ctx.sessionmaker, ctx.search, query)
    except Exception as exc:
        results = []
        unavailable = redact(str(exc))[:200] or type(exc).__name__

    matched: set[str] = set()
    if results:
        match_version, match_system = prompt("match")
        listing = "\n".join(
            f"{item['url']}\n{item.get('title') or ''}\n{item.get('content') or ''}"
            for item in results
        )
        try:
            judgement = await ctx.llm.structured(
                ReferenceMatchOut,
                [
                    {"role": "system", "content": match_system},
                    {"role": "user", "content": (
                        f"Category: {category}\n"
                        f"Error signature:\n{untrusted(signature)}\n"
                        f"Snippets:\n{untrusted(listing)}"
                    )},
                ],
                tier="fast", node="research", temperature=0.0,
                run_id=state["run_id"], flake_id=state["flake_id"],
                prompt_version=match_version,
            )
            known = {item["url"] for item in results}
            matched = {url for url in judgement.matched_urls if url in known}
        except BudgetExceeded:
            return {"stopped": "stopped_budget"}
        except Exception:
            matched = set()

    async with ctx.sessionmaker() as session:
        run = await session.get(Run, state["run_id"])
        flake = await session.get(Flake, state["flake_id"])
        for item in results:
            session.add(Reference(
                flake_id=state["flake_id"],
                title=(item.get("title") or "")[:300],
                url=item["url"][:2048],
                site=_site(item["url"]),
                snippet=(item.get("content") or "")[:300],
                score=item.get("score") if isinstance(item.get("score"), int | float) else None,
                matched=item["url"] in matched,
            ))
        if flake is not None:
            flake.updated_at = utcnow()
        message = "No upstream references found"
        if unavailable:
            message = "Search unavailable"
        elif results:
            message = f"{len(results)} upstream references"
        await append_event(session, run, "log.line", {
            "level": "info", "flake_id": state["flake_id"], "message": message,
        })
        await append_event(session, run, "step.completed", {
            "step": "research", "flake_id": state["flake_id"], "references": len(results),
        })
        await session.commit()
    return {}
