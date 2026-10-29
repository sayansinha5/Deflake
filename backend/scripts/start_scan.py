"""Starts a scan as the demo owner and prints flakes when it finishes.

    docker compose -f backend/docker-compose.yml exec api python scripts/start_scan.py --detect 30
"""
import argparse
import os
import sys

import httpx

API = "http://localhost:8000"
HEADERS = {"X-Requested-With": "deflake", "Content-Type": "application/json"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="flaky-shop")
    parser.add_argument("--detect", type=int, default=30)
    parser.add_argument("--resume", default=None, help="Resume this run id.")
    parser.add_argument("--email", default=os.environ.get("OWNER_EMAIL", "owner@deflake.local"))
    parser.add_argument("--password", default=os.environ.get("OWNER_PASSWORD", "Owner2026"))
    args = parser.parse_args()

    with httpx.Client(base_url=API, headers=HEADERS, timeout=30.0) as c:
        sign = c.post("/api/auth/session", json={"email": args.email, "password": args.password})
        if sign.status_code != 204:
            print("sign-in failed", sign.status_code, sign.text)
            return 1
        if args.resume:
            started = c.post(f"/api/runs/{args.resume}/resume")
            print("resume", started.status_code, started.text)
        else:
            started = c.post(
                f"/api/repos/{args.repo}/runs", json={"detect_reruns": args.detect},
            )
            print("start", started.status_code, started.text)
        if started.status_code != 202:
            return 1
        run_id = started.json()["run_id"]
        print(f"run_id={run_id}")

    # SSE from a client that follows the cookie jar
    with httpx.Client(base_url=API, headers=HEADERS, timeout=1200.0) as c:
        c.post("/api/auth/session", json={"email": args.email, "password": args.password})
        with c.stream("GET", f"/api/runs/{run_id}/events",
                      headers={"Accept": "text/event-stream"}) as stream:
            event_name = ""
            for line in stream.iter_lines():
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event_name:
                    data = line.split(":", 1)[1].strip()
                    if event_name in {"run.status", "step.started", "step.completed",
                                      "flake.detected", "run.finished"}:
                        print(event_name, data[:300])
                    if event_name == "run.finished":
                        break
                if not line:
                    event_name = ""
        flakes = c.get(f"/api/runs/{run_id}/flakes").json()
        print("\nclassification:")
        for f in sorted(flakes, key=lambda x: x["test_id"]):
            print(f"  {f['state']:<12} {f.get('category') or '-':<16} "
                  f"{f['fail_count']:>2}/{f['run_count']}  "
                  f"rate={f['rate']:.2f} [{f['ci_low']:.2f}, {f['ci_high']:.2f}]  {f['test_id']}")
        run = c.get(f"/api/runs/{run_id}").json()
        print(f"\nstatus={run['status']} flakes={run['flake_count']} broken={run['broken_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
