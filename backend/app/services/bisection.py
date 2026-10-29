"""Delta-debug a failing order down to the tests that pollute the victim.

Each probe is one runner call of three iterations. A subset is kept when the
victim fails at least twice. The search stops at one test, a minimal
interacting set, or 40 calls.
"""

FAIL_OUTCOMES = frozenset({"failed", "error", "timeout"})
REPEATS = 3
NEED = 2
MAX_CALLS = 40
# Order dependence also shows up under these labels (demo F1 and F5).
SUSPECTED = frozenset({"order_dependent", "shared_resource", "environment"})

ISOLATED = "isolated"
NOT_ISOLATED = "polluter_not_isolated"
NOT_ORDER = "not_order_dependent"
GATE_STOPS = frozenset({"cancelled", "stopped_time", "stopped_budget", "failed"})


class RunnerFailed(Exception):
    """A probe raised. `steps` are the probes that finished before it."""

    def __init__(self, exc: Exception, steps: list, calls: int) -> None:
        super().__init__(str(exc))
        self.exc = exc
        self.steps = steps
        self.calls = calls


class _Halt:
    def __init__(self, reason: str) -> None:
        self.reason = reason


def failure_count(result: dict, victim: str) -> int:
    """How many iterations the victim failed, including a crashed iteration."""
    total = 0
    for iteration in result.get("iterations") or []:
        if (iteration.get("status") or "ok") != "ok":
            total += 1
            continue
        by_id = {row["test_id"]: row for row in iteration.get("results") or []}
        outcome = (by_id.get(victim) or {}).get("outcome")
        if outcome in FAIL_OUTCOMES or victim not in by_id:
            total += 1
    return total


def skipped_record() -> dict:
    return {"status": "skipped", "polluters": [], "calls": 0, "steps": []}


def _record(
    status: str, polluters: list[str], calls: int, steps: list, detail: str | None = None,
) -> dict:
    out = {
        "status": status,
        "polluters": list(polluters),
        "calls": calls,
        "steps": steps,
    }
    if detail:
        out["detail"] = detail
    return out


def _split(items: list[str], parts: int) -> list[list[str]]:
    parts = max(1, min(parts, len(items)))
    size, extra = divmod(len(items), parts)
    chunks: list[list[str]] = []
    start = 0
    for index in range(parts):
        end = start + size + (1 if index < extra else 0)
        if end > start:
            chunks.append(items[start:end])
        start = end
    return chunks


async def bisect(
    victim: str, prefix: list[str], probe, *, budget: int = MAX_CALLS, allow=None,
) -> dict:
    """`probe(order)` returns how many of the three runs the victim failed.

    `allow` returns a gate reason to stop, or None to continue.
    """
    steps: list[dict] = []
    calls = 0
    if not prefix:
        return _record(NOT_ISOLATED, [], 0, steps, "empty_prefix")

    async def check(group: list[str]):
        nonlocal calls
        if calls >= budget:
            return None
        if allow is not None:
            reason = await allow()
            if reason:
                return _Halt(reason)
        calls += 1
        order = [*group, victim]
        try:
            failures = int(await probe(order))
        except Exception as exc:
            raise RunnerFailed(exc, steps, calls) from exc
        steps.append({
            "step": len(steps) + 1,
            "tests": list(order),
            "failures": failures,
            "repeats": REPEATS,
            "result": "reproduced" if failures >= NEED else "not_reproduced",
        })
        return failures

    alone = await check([])
    if isinstance(alone, _Halt):
        return _record(alone.reason, [], calls, steps)
    if alone is None:
        return _record(NOT_ISOLATED, [], calls, steps, "call_budget")
    if alone >= 1:
        steps[-1]["result"] = "fails_alone"
        return _record(NOT_ORDER, [], calls, steps)

    full = await check(list(prefix))
    if isinstance(full, _Halt):
        return _record(full.reason, [], calls, steps)
    if full is None:
        return _record(NOT_ISOLATED, [], calls, steps, "call_budget")
    if full < NEED:
        return _record(NOT_ISOLATED, [], calls, steps, "unstable")

    found = await _ddmin(list(prefix), check)
    if isinstance(found, _Halt):
        return _record(found.reason, [], calls, steps)
    if found is None:
        return _record(NOT_ISOLATED, [], calls, steps, "call_budget")
    if not found:
        return _record(NOT_ISOLATED, [], calls, steps, "unstable")
    return _record(ISOLATED, found, calls, steps)


async def _ddmin(current: list[str], check):
    """Smallest subset of `current` that still reproduces. None means the call cap."""
    n = 2
    while len(current) >= 2:
        chunks = _split(current, n)
        reduced: list[str] | None = None
        next_n = n
        for chunk in chunks:
            outcome = await check(chunk)
            if isinstance(outcome, _Halt) or outcome is None:
                return outcome
            if outcome >= NEED:
                reduced = chunk
                next_n = 2
                break
        if reduced is None:
            for index in range(len(chunks)):
                complement: list[str] = []
                for chunk_index, chunk in enumerate(chunks):
                    if chunk_index != index:
                        complement.extend(chunk)
                if not complement or len(complement) >= len(current):
                    continue
                outcome = await check(complement)
                if isinstance(outcome, _Halt) or outcome is None:
                    return outcome
                if outcome >= NEED:
                    reduced = complement
                    next_n = max(n - 1, 2)
                    break
        if reduced is None or len(reduced) >= len(current):
            if n >= len(current):
                return current
            n = min(len(current), n * 2)
            continue
        current = reduced
        n = next_n
    return current
