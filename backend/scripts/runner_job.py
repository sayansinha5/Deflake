"""Sends one job to the Runner and prints a summary. Run inside the api container:

    docker compose -f backend/docker-compose.yml exec api python scripts/runner_job.py --iterations 5
"""
import argparse
import os
import sys
from collections import Counter

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="flaky-shop")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    url = os.environ.get("RUNNER_URL", "http://runner:8100")
    headers = {"X-Runner-Secret": os.environ["RUNNER_SHARED_SECRET"]}
    job = {"repo_id": args.repo, "iterations": args.iterations, "timeout_s": args.timeout}
    r = httpx.post(f"{url}/jobs", headers=headers, json=job, timeout=900)
    print(f"HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text)
        return 1

    failures: Counter[str] = Counter()
    for it in r.json()["iterations"]:
        counts = Counter(t["outcome"] for t in it["results"])
        print(f"iteration {it['index']}: status={it['status']} seed={it['seed']} "
              f"hash_seed={it['hash_seed']} tests={len(it['results'])} "
              f"duration={it['duration_ms']}ms {dict(counts)}")
        failures.update(t["test_id"] for t in it["results"] if t["outcome"] != "passed")
    print("\nnot passed, per test:")
    for test, n in failures.most_common():
        print(f"  {n}/{args.iterations}  {test}")

    wrong = httpx.post(f"{url}/jobs", headers={"X-Runner-Secret": "wrong"}, json=job, timeout=30)
    print(f"\nrequest with a wrong secret -> HTTP {wrong.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
