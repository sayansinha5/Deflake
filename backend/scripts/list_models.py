"""Lists models from the configured OpenAI-compatible endpoint (U1).

    docker compose -f backend/docker-compose.yml exec api python scripts/list_models.py
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> int:
    base = (os.environ.get("AI_BASE_URL") or "").rstrip("/")
    key = os.environ.get("AI_API_KEY") or ""
    if not base or not key:
        print("AI_BASE_URL and AI_API_KEY must be set.")
        return 1
    url = f"{base}/models"
    r = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=30.0)
    print(f"GET {url} -> HTTP {r.status_code}")
    if r.status_code != 200:
        print("body redacted; status only")
        return 1
    data = r.json().get("data") or r.json().get("models") or []
    print(f"{len(data)} models:\n")
    configured = {
        os.environ.get("AI_MODEL_FAST"),
        os.environ.get("AI_MODEL_BALANCED"),
        os.environ.get("AI_MODEL_REASONING"),
    }
    for item in data:
        model_id = item.get("id") or item.get("name") or ""
        owned = item.get("owned_by") or item.get("publisher") or ""
        mark = "  <-- configured" if model_id in configured else ""
        nemo = "  [Nemotron]" if "nemotron" in model_id.lower() else ""
        print(f"  {model_id}  {owned}{nemo}{mark}")
    print("\nSuggested mapping: Nano -> fast, Super -> balanced, Ultra -> reasoning.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
