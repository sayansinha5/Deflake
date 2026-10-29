"""Runs a demo repo's suite N times in random order with a random PYTHONHASHSEED and prints
per-test failure counts. Exits non-zero when the seeded flakes fall outside the expected bands.

Usage: python scripts/check_demo_flakes.py [--repo PATH] [--runs 30] [--parallel 4]
"""
import argparse
import os
import random
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_REPO = Path(__file__).resolve().parents[2] / "demo-repos" / "flaky-shop"

FLAKY = {
    "F1": "tests/test_pricing.py::test_convert_eur_to_usd",
    "F2": "tests/test_inventory.py::test_concurrent_reservations_keep_stock_consistent",
    "F3": "tests/test_orders.py::test_order_ids_are_unique",
    "F4": "tests/test_coupons.py::test_batch_codes_are_unique",
    "F5": "tests/test_settings.py::test_format_price_defaults_to_usd",
    "F6": "tests/test_reports.py::test_revenue_report_total",
    "E1": "tests/test_reports.py::test_daily_sales_summary_is_fast",
}
BROKEN = {"B1": "tests/test_pricing.py::test_tax_standard_rate"}
FLAKY_BAND = (2, 12)


def test_id(case: ET.Element) -> str:
    module = case.get("classname", "").replace(".", "/") + ".py"
    return f"{module}::{case.get('name')}"


def run_once(repo: Path, seed: int, hash_seed: int) -> dict[str, bool]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONHASHSEED": str(hash_seed),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "-p", "randomly", f"--randomly-seed={seed}", "--timeout=60",
             f"--junitxml={report}"],
            cwd=repo, env=env, capture_output=True, text=True, check=False,
        )
        if not report.exists():
            raise RuntimeError("pytest produced no report; the suite could not start")
        results = {}
        for case in ET.parse(report).getroot().iter("testcase"):  # noqa: S314
            failed = case.find("failure") is not None or case.find("error") is not None
            results[test_id(case)] = failed
        return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args()

    rng = random.SystemRandom()
    jobs = [(rng.randrange(2**32), rng.randrange(2**32)) for _ in range(args.runs)]
    failures: Counter[str] = Counter()
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for results in pool.map(lambda j: run_once(args.repo, *j), jobs):
            seen.update(results)
            failures.update(t for t, failed in results.items() if failed)

    labels = {v: k for k, v in {**FLAKY, **BROKEN}.items()}
    print(f"{len(seen)} tests, {args.runs} runs\n")
    print(f"{'id':<4} {'failures':>8}  test")
    for test in sorted(seen, key=lambda t: (-failures[t], t)):
        if failures[test] or test in labels:
            print(f"{labels.get(test, ''):<4} {failures[test]:>8}  {test}")

    problems = []
    for label, test in FLAKY.items():
        if not FLAKY_BAND[0] <= failures[test] <= FLAKY_BAND[1]:
            problems.append(f"{label} failed {failures[test]}/{args.runs}, expected "
                            f"{FLAKY_BAND[0]} to {FLAKY_BAND[1]}")
    for label, test in BROKEN.items():
        if failures[test] != args.runs:
            problems.append(f"{label} failed {failures[test]}/{args.runs}, expected every run")
    expected = set(FLAKY.values()) | set(BROKEN.values())
    for test in sorted(seen - expected):
        if failures[test]:
            problems.append(f"unexpected failures: {test} ({failures[test]})")

    print("\n" + ("\n".join(problems) if problems else "All seeded flakes are within their bands."))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
