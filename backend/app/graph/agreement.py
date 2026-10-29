"""Self-consistency: samples agree when category and culprit match."""
from app.llm.schemas import DiagnoseOut


def majority(samples: list[DiagnoseOut]) -> tuple[DiagnoseOut, int]:
    if not samples:
        raise ValueError("majority requires at least one sample")
    groups: dict[tuple[str, str], list[DiagnoseOut]] = {}
    for sample in samples:
        groups.setdefault((sample.category, sample.culprit), []).append(sample)
    best = max(groups.values(), key=lambda group: (len(group), max(s.confidence for s in group)))
    chosen = max(best, key=lambda sample: sample.confidence)
    return chosen, len(best)
