"""Isotonic calibration and the reliability chart.

Human labels are 1 when the explanation matches the diff and 0 when it does not.
Control items and items without a consensus are left out of the fit.
"""
from __future__ import annotations


def reviewer_vote(answer: dict) -> int | None:
    """1 only when Q1 is Yes and Q2 is Real fix. Unsure abstains."""
    if "label" in answer and answer["label"] in (0, 1, "0", "1"):
        return int(answer["label"])
    q1 = str(answer.get("q1") or "").strip().lower()
    q2 = str(answer.get("q2") or "").strip().lower()
    if q1 == "yes" and q2 == "real fix":
        return 1
    if q1 == "no" or q2 == "hides it":
        return 0
    return None


def consensus(answers: list[dict]) -> tuple[str | None, float | None]:
    """Majority of the votes. An even split is no consensus."""
    votes = [vote for vote in (reviewer_vote(answer) for answer in answers) if vote is not None]
    if not votes:
        return None, None
    ones = sum(votes)
    zeros = len(votes) - ones
    if ones == zeros:
        return "no_consensus", round(ones / len(votes), 4)
    winner = "1" if ones > zeros else "0"
    return winner, round(max(ones, zeros) / len(votes), 4)


def pav(pairs: list[tuple[float, float]]) -> list[dict]:
    """Pool-adjacent-violators. Each point is a raw score and a 0/1 label."""
    ordered = sorted((float(raw), float(label)) for raw, label in pairs)
    blocks: list[dict] = [
        {"n": 1, "sy": label, "x0": raw, "x1": raw} for raw, label in ordered
    ]
    index = 0
    while index < len(blocks) - 1:
        left, right = blocks[index], blocks[index + 1]
        if left["sy"] / left["n"] <= right["sy"] / right["n"]:
            index += 1
            continue
        blocks[index:index + 2] = [{
            "n": left["n"] + right["n"],
            "sy": left["sy"] + right["sy"],
            "x0": left["x0"],
            "x1": right["x1"],
        }]
        if index:
            index -= 1
    points: list[dict] = []
    for block in blocks:
        value = round(block["sy"] / block["n"], 4)
        points.append({"raw": round(block["x0"], 4), "calibrated": value})
        if block["x1"] != block["x0"]:
            points.append({"raw": round(block["x1"], 4), "calibrated": value})
    return points


def reliability_bins(pairs: list[tuple[float, float]], bins: int = 5) -> list[dict]:
    """Five equal bins of mean predicted score against observed agreement."""
    chart = []
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        chosen = []
        for raw, label in pairs:
            if raw >= high and not (index == bins - 1 and raw == high):
                continue
            if raw < low:
                continue
            if raw == high and index != bins - 1:
                continue
            chosen.append((raw, label))
        count = len(chosen)
        chart.append({
            "low": round(low, 4),
            "high": round(high, 4),
            "mean_predicted": round(sum(raw for raw, _ in chosen) / count, 4) if count else None,
            "observed": round(sum(label for _, label in chosen) / count, 4) if count else None,
            "count": count,
        })
    return chart


def suggest_threshold(
    pairs: list[tuple[float, float]], *, target: float = 0.90, minimum: int = 10,
) -> tuple[float | None, float | None, float | None]:
    """Lowest score whose items at or above it have the target precision and enough items."""
    if len(pairs) < minimum:
        return None, None, None
    for threshold in sorted({round(raw, 4) for raw, _ in pairs}):
        chosen = [label for raw, label in pairs if raw + 1e-9 >= threshold]
        if len(chosen) < minimum:
            continue
        precision = sum(chosen) / len(chosen)
        if precision + 1e-9 >= target:
            coverage = len(chosen) / len(pairs)
            return threshold, round(precision, 4), round(coverage, 4)
    return None, None, None


def operating_point(
    pairs: list[tuple[float, float]], threshold: float,
) -> tuple[float | None, float | None]:
    """Precision and coverage of the items at or above a threshold."""
    if not pairs:
        return None, None
    chosen = [label for raw, label in pairs if raw + 1e-9 >= threshold]
    if not chosen:
        return None, 0.0
    return round(sum(chosen) / len(chosen), 4), round(len(chosen) / len(pairs), 4)


def fit_labels(
    pairs: list[tuple[float, float]], *, min_labels: int, default_threshold: float,
) -> dict:
    suggested, precision, coverage = suggest_threshold(pairs)
    partial = len(pairs) < min_labels or suggested is None
    if len(pairs) < min_labels:
        message = f"Using the default threshold until {min_labels} labels are in."
    elif suggested is None:
        message = (
            "No cutoff reached 0.90 precision on at least 10 items. "
            "Using the default threshold."
        )
    else:
        message = "Threshold is the lowest score with precision at least 0.90."
    return {
        "points": pav(pairs),
        "reliability": reliability_bins(pairs),
        "threshold": default_threshold if partial else suggested,
        "suggested_threshold": suggested,
        "precision_at": None if partial else precision,
        "coverage_at": None if partial else coverage,
        "n_labels": len(pairs),
        "partial": partial,
        "message": message,
        "source": "default" if partial else "calibration",
    }


def control_accuracy(rows: list[tuple[bool, int | None, str | None]]) -> float | None:
    """Share of control items whose consensus matches the known answer."""
    controls = [row for row in rows if row[0]]
    if not controls:
        return None
    matched = 0
    for _is_control, expected, agreed in controls:
        if expected is None or agreed not in {"0", "1"}:
            continue
        if int(agreed) == expected:
            matched += 1
    return round(matched / len(controls), 4)


def label_pairs(items: list) -> list[tuple[float, float]]:
    """Non-control items that have a 0/1 consensus and a raw score."""
    pairs = []
    for item in items:
        if item.is_control or item.consensus not in {"0", "1"} or item.confidence_raw is None:
            continue
        pairs.append((float(item.confidence_raw), float(item.consensus)))
    return pairs
