import pytest

from app.services.detect import classify_test
from app.services.stats import (
    detection_probability,
    plan_verification,
    required_reruns,
    upper_bound_zero_failures,
    wilson_interval,
)


def test_wilson_known_values():
    low, high = wilson_interval(6, 30)
    assert low == pytest.approx(0.0950, abs=0.001)
    assert high == pytest.approx(0.373, abs=0.002)
    assert wilson_interval(0, 30)[0] == 0.0
    assert wilson_interval(30, 30)[1] == 1.0


def test_upper_bound_after_zero_failures():
    assert abs(upper_bound_zero_failures(200) - (1 - 0.05 ** (1 / 200))) < 1e-12
    assert 0.014 < upper_bound_zero_failures(200) < 0.015


def test_power_raises_reruns():
    reruns, ok = plan_verification(p_low=0.05, requested=200, cap=600)
    assert ok and reruns == 200
    reruns, ok = plan_verification(p_low=0.01, requested=200, cap=600)
    assert ok and reruns == required_reruns(0.01)
    assert reruns > 200


def test_underpowered_when_cap_is_too_low():
    reruns, ok = plan_verification(p_low=0.001, requested=200, cap=600)
    assert reruns == 600 and ok is False


def test_detection_probability_at_n30():
    assert 0.95 < detection_probability(0.10, 30) < 0.96


@pytest.mark.parametrize("outcomes,expected", [
    (["passed"] * 30, None),
    (["failed"] * 30, "broken"),
    (["failed"] * 6 + ["passed"] * 24, "flaky"),
    (["timeout"] + ["passed"] * 29, "flaky"),
    (["skipped"] * 30, None),
    (["failed"] + ["skipped"] * 29, "broken"),
])
def test_classify_test(outcomes, expected):
    assert classify_test(outcomes) == expected
