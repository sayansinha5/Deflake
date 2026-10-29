import math

Z95 = 1.959963984540054


def wilson_interval(failures: int, runs: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for a failure rate of failures / runs."""
    if runs <= 0:
        raise ValueError("runs must be positive")
    if not 0 <= failures <= runs:
        raise ValueError("failures must be between 0 and runs")
    p = failures / runs
    denom = 1 + z * z / runs
    centre = p + z * z / (2 * runs)
    margin = z * math.sqrt(p * (1 - p) / runs + z * z / (4 * runs * runs))
    low = max(0.0, (centre - margin) / denom)
    high = min(1.0, (centre + margin) / denom)
    if failures == 0:
        low = 0.0
    if failures == runs:
        high = 1.0
    return low, high


def detection_probability(rate: float, runs: int) -> float:
    """Chance of seeing at least one failure in `runs` runs of a test failing at `rate`."""
    return 1 - (1 - rate) ** runs


def rarest_detectable_rate(runs: int, probability: float = 0.95) -> float:
    """Lowest failure rate that `runs` runs catch with the given probability."""
    return 1 - (1 - probability) ** (1 / runs)


def upper_bound_zero_failures(runs: int, alpha: float = 0.05) -> float:
    """95% upper bound on the remaining failure rate after 0 failures in `runs` runs."""
    if runs <= 0:
        raise ValueError("runs must be positive")
    return 1 - alpha ** (1 / runs)


def required_reruns(p_low: float, alpha: float = 0.05) -> int | None:
    """Smallest M where (1 - p_low)^M <= alpha, i.e. M passing runs are unlikely by luck."""
    if p_low <= 0:
        return None
    if p_low >= 1:
        return 1
    return math.ceil(math.log(alpha) / math.log(1 - p_low))


def plan_verification(p_low: float, requested: int, cap: int,
                      alpha: float = 0.05) -> tuple[int, bool]:
    """Returns (reruns to do, enough power). Raises reruns up to cap when underpowered."""
    needed = required_reruns(p_low, alpha)
    if needed is None:
        return min(max(requested, 1), cap), False
    reruns = min(max(requested, needed), cap)
    return reruns, reruns >= needed
