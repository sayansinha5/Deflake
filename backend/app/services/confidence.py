"""Raw confidence, calibration lookup, and the auto-PR / escalate decision."""

WEIGHTS = {
    "agreement": 0.30,
    "verification": 0.30,
    "minimality": 0.15,
    "guardrail": 0.10,
    "self_confidence": 0.10,
    "reference": 0.05,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def minimality(lines_changed: int) -> float:
    """1 at 20 changed lines or fewer, falling linearly to 0 at 80."""
    if lines_changed <= 20:
        return 1.0
    if lines_changed >= 80:
        return 0.0
    return (80 - lines_changed) / 60


def verification_strength(outcome: str | None) -> float:
    if outcome == "verified":
        return 1.0
    if outcome == "underpowered":
        return 0.5
    return 0.0


def raw_confidence(
    *,
    agreement_k: int,
    agreement_n: int,
    outcome: str | None,
    lines_changed: int,
    first_attempt_clean: bool,
    self_confidence: float,
    reference_matched: bool,
) -> tuple[float, dict]:
    """Weighted score in 0..1, plus the parts the UI can show."""
    agreement = (agreement_k / agreement_n) if agreement_n else 0.0
    values = {
        "agreement": _clamp(agreement),
        "verification": verification_strength(outcome),
        "minimality": minimality(lines_changed),
        "guardrail": 1.0 if first_attempt_clean else 0.0,
        "self_confidence": _clamp(self_confidence),
        "reference": 1.0 if reference_matched else 0.0,
    }
    parts = {
        name: {"weight": WEIGHTS[name], "value": value}
        for name, value in values.items()
    }
    score = sum(item["weight"] * item["value"] for item in parts.values())
    return round(_clamp(score), 4), parts


def apply_calibration(raw: float, points: list | None) -> float:
    """Map a raw score through isotonic points. No points leaves the score unchanged."""
    pairs: list[tuple[float, float]] = []
    for item in points or []:
        if isinstance(item, dict) and "raw" in item and "calibrated" in item:
            pairs.append((float(item["raw"]), float(item["calibrated"])))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            pairs.append((float(item[0]), float(item[1])))
    if not pairs:
        return _clamp(raw)
    pairs.sort()
    raw = _clamp(raw)
    if raw <= pairs[0][0]:
        return _clamp(pairs[0][1])
    if raw >= pairs[-1][0]:
        return _clamp(pairs[-1][1])
    for (left, low), (right, high) in zip(pairs, pairs[1:], strict=False):
        if left <= raw <= right:
            if right == left:
                return _clamp(high)
            share = (raw - left) / (right - left)
            return _clamp(low + share * (high - low))
    return _clamp(raw)


def decide_route(
    *,
    outcome: str | None,
    category: str | None,
    needs_human: bool,
    score: float,
    threshold: float,
) -> str:
    """Auto-PR only for a powered, verified fix that clears the threshold.

    A failed or underpowered proof, an environment flake, or needs_human
    always escalates.
    """
    if outcome != "verified" or category == "environment" or needs_human:
        return "escalate"
    if score >= threshold:
        return "auto_pr"
    return "escalate"
