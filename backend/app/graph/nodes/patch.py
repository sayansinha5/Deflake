"""Ask for a patch, reject it when a guardrail fires, and try again with that feedback."""
import ast
import re
from pathlib import Path, PurePosixPath

from sqlalchemy import func, select

from app.db.models import Diagnosis, Flake, Patch, Repo, Run, utcnow
from app.graph.context import current_context
from app.graph.gates import gate
from app.graph.nodes.common import note_error
from app.graph.state import FlakeState
from app.graph.text import untrusted
from app.llm.prompts import prompt
from app.llm.schemas import PatchOut
from app.llm.usage import BudgetExceeded
from app.security.redact import redact
from app.services.events import append_event
from app.services.guardrails import is_editable, review_patch
from app.services.guardrails import prepare_diff as prepare_lines
from runner.patches import paths_in_patch

FILE_LINE_LIMIT = 250


def fixable(category: str | None, needs_human: bool) -> bool:
    return category != "environment" and not needs_human


def repo_dir(allowlist_path: str, relative: str) -> Path:
    allowlist = Path(allowlist_path)
    if not allowlist.is_absolute():
        allowlist = (Path(__file__).resolve().parents[3] / allowlist).resolve()
    return (allowlist.parent / relative).resolve()


def _clip(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= FILE_LINE_LIMIT:
        return text
    return "\n".join(lines[:FILE_LINE_LIMIT]) + "\n"


def _sources(root: Path, paths: list[str]) -> tuple[dict[str, str], str]:
    originals: dict[str, str] = {}
    blocks: list[str] = []
    for path in paths:
        file_path = (root / path).resolve()
        try:
            file_path.relative_to(root)
        except ValueError:
            continue
        if not file_path.is_file():
            continue
        text = redact(file_path.read_text(encoding="utf-8", errors="replace"))
        originals[path] = text
        blocks.append(f"File {path}:\n{untrusted(_clip(text))}")
    return originals, "\n\n".join(blocks)


def _existing(root: Path, hint: str, editable: list[str]) -> str | None:
    candidate = (root / hint).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        candidate = None
    if candidate is not None and candidate.is_file():
        rel = candidate.relative_to(root).as_posix()
        if is_editable(rel, editable):
            return rel
    name = PurePosixPath(hint).name
    if not root.is_dir() or not name.endswith(".py"):
        return None
    matches = []
    for file in root.rglob(name):
        if not file.is_file() or any(part.startswith(".") for part in file.relative_to(root).parts):
            continue
        rel = file.relative_to(root).as_posix()
        if is_editable(rel, editable):
            matches.append(rel)
    if len(matches) == 1:
        return matches[0]
    return None


def _shop_imports(root: Path, test_file: str) -> list[str]:
    file_path = root / test_file
    if not file_path.is_file():
        return []
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        module = getattr(node, "module", None)
        if isinstance(node, ast.ImportFrom) and module and module.startswith("shop"):
            rel = module.replace(".", "/") + ".py"
            if rel not in found and (root / rel).is_file():
                found.append(rel)
    return found


def _collect_paths(root: Path, test_id: str, culprit: str, editable: list[str]) -> list[str]:
    test_file = test_id.split("::", 1)[0].replace("\\", "/")
    hints = re.findall(r"[A-Za-z0-9_./-]+\.py", culprit.replace("\\", "/"))
    if test_file.endswith(".py"):
        hints.append(test_file)
    resolved: list[str] = []
    for hint in hints:
        rel = _existing(root, hint, editable)
        if rel and rel not in resolved:
            resolved.append(rel)
    if test_file.endswith(".py"):
        for rel in _shop_imports(root, test_file):
            if rel not in resolved and is_editable(rel, editable):
                resolved.append(rel)
    return resolved[:4]


async def patch(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
    async with ctx.sessionmaker() as session:
        reason = await gate(session, ctx.settings, state["run_id"])
        if reason:
            return {"stopped": reason}
        flake = await session.get(Flake, state["flake_id"])
        diagnosis = await session.scalar(
            select(Diagnosis).where(Diagnosis.flake_id == state["flake_id"], Diagnosis.attempt == 1)
        )
        run = await session.get(Run, state["run_id"])
        if flake is None or run is None or diagnosis is None:
            return {"stopped": "error"}
        settled = await session.scalar(
            select(Patch.id).where(
                Patch.flake_id == flake.id,
                Patch.status.in_(("proposed", "verified", "failed_verify", "failed_apply")),
            )
        )
        if settled is not None or flake.routing:
            return {}
        if not fixable(flake.category or diagnosis.category, diagnosis.needs_human):
            await append_event(session, run, "log.line", {
                "level": "info", "flake_id": flake.id,
                "message": "Patch skipped. This flake is escalated in a later step.",
            })
            await append_event(session, run, "step.completed", {
                "step": "patch", "flake_id": flake.id, "skipped": True,
            })
            await session.commit()
            return {}
        prior = list(await session.scalars(
            select(Patch).where(Patch.flake_id == flake.id).order_by(Patch.attempt)
        ))
        if len(prior) >= ctx.settings.max_patch_attempts:
            return {}
        repo = await session.get(Repo, run.repo_id)
        await append_event(session, run, "step.started", {"step": "patch", "flake_id": flake.id})
        await session.commit()
        feedback = [
            f"{item.get('rule')}: {item.get('message')}\n{item.get('lines') or ''}"
            for row in prior for item in (row.violations or [])
        ]
        test_id = flake.test_id
        category = flake.category or diagnosis.category
        cause = diagnosis.root_cause
        strategy = diagnosis.fix_strategy
        culprit = diagnosis.culprit
        editable = list(repo.editable_paths or []) if repo is not None else []
        relative = repo.path if repo is not None else ""
        start_attempt = len(prior) + 1

    root = repo_dir(ctx.settings.allowlist_path, relative)
    paths = _collect_paths(root, test_id, culprit, editable)
    originals, shown = _sources(root, paths)
    version, system = prompt("patch")
    clean_id = None
    for attempt in range(start_attempt, ctx.settings.max_patch_attempts + 1):
        async with ctx.sessionmaker() as session:
            reason = await gate(session, ctx.settings, state["run_id"])
            if reason:
                return {"stopped": reason}
        user = (
            f"You may edit only: {', '.join(paths) or 'no file was loaded'}\n"
            f"Category: {category}\n"
            f"Cause:\n{untrusted(cause)}\n"
            f"Strategy:\n{untrusted(strategy)}\n"
            f"Culprit:\n{untrusted(culprit)}\n"
            f"{shown}"
        )
        if feedback:
            user += "\nPrevious rejections:\n" + untrusted("\n".join(feedback))
        try:
            parsed = await ctx.llm.structured(
                PatchOut,
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                tier="balanced", node="patch", temperature=0.2,
                run_id=state["run_id"], flake_id=state["flake_id"], prompt_version=version,
            )
        except BudgetExceeded:
            return {"stopped": "stopped_budget"}
        except Exception as exc:
            await note_error(ctx, state["run_id"], state["flake_id"], exc)
            return {"stopped": "error"}

        # The files named by the model are not trusted. Read every path the diff names.
        diff = "\n".join(parsed.lines)
        extra = _paths_in(prepare_lines(diff))
        missing = [path for path in extra if path not in originals]
        if missing:
            more, _shown = _sources(root, missing)
            originals.update(more)
        diff, violations = review_patch(diff, originals, editable)
        extra = _paths_in(diff) or extra
        status = "proposed" if not violations else "rejected"
        async with ctx.sessionmaker() as session:
            already = await session.scalar(
                select(Patch.id).where(
                    Patch.flake_id == state["flake_id"], Patch.attempt == attempt,
                )
            )
            if already is None:
                row = Patch(
                    flake_id=state["flake_id"], attempt=attempt, diff=diff,
                    summary=parsed.summary, status=status,
                    violations=[item.as_dict() for item in violations],
                    files_changed=sorted(extra),
                    lines_changed=_changed_lines(diff),
                )
                session.add(row)
                await session.flush()
                if status == "proposed":
                    clean_id = row.id
            flake = await session.get(Flake, state["flake_id"])
            run = await session.get(Run, state["run_id"])
            if status == "proposed" and flake is not None:
                flake.state = "patching"
                flake.error = None
            elif flake is not None:
                rules = ", ".join(item.rule for item in violations) or "rejected"
                flake.error = f"Patch attempt {attempt} rejected ({rules})."
            if flake is not None:
                flake.updated_at = utcnow()
            await append_event(session, run, "flake.updated", {
                "flake_id": state["flake_id"],
                "state": flake.state if flake else None,
                "patch_status": status, "attempt": attempt,
                "rules": [item.rule for item in violations],
            })
            await session.commit()
        if status == "proposed":
            break
        feedback.append(
            "\n".join(f"{item.rule}: {item.message}\n{item.lines}" for item in violations)
        )

    async with ctx.sessionmaker() as session:
        run = await session.get(Run, state["run_id"])
        attempts = int(await session.scalar(
            select(func.count()).select_from(Patch).where(Patch.flake_id == state["flake_id"])
        ) or 0)
        await append_event(session, run, "step.completed", {
            "step": "patch", "flake_id": state["flake_id"],
            "proposed": clean_id is not None, "attempts": attempts,
        })
        await session.commit()
    return {}


def _paths_in(diff: str) -> set[str]:
    try:
        return paths_in_patch(diff)
    except Exception:
        return set()


def _changed_lines(diff: str) -> int:
    return sum(
        1 for line in diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )
