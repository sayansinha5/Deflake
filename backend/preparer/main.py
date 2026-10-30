import hmac
import os
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from preparer.pipeline import prepare
from preparer.schemas import PrepareJob, PrepareResult

SECRET = os.environ.get("PREPARER_SHARED_SECRET", "")
DATA_ROOT = Path(os.environ.get("PREPARER_REPOS_DIR", "/repos-data"))
_REPO_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

if len(SECRET) < 16:
    raise RuntimeError("PREPARER_SHARED_SECRET must be set (at least 16 characters).")

app = FastAPI(title="Deflake preparer", docs_url=None, redoc_url=None, openapi_url=None)


def _check_secret(given: str | None) -> None:
    if not given or not hmac.compare_digest(given.encode(), SECRET.encode()):
        raise HTTPException(status_code=401, detail="unauthorised")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/prepare", response_model=PrepareResult)
def prepare_repo(
    job: PrepareJob,
    x_preparer_secret: str | None = Header(default=None),
) -> PrepareResult | JSONResponse:
    _check_secret(x_preparer_secret)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    result = prepare(job, DATA_ROOT)
    if result.status == "failed":
        return JSONResponse(status_code=422, content=result.model_dump())
    return result


@app.delete("/repos/{repo_id}")
def cleanup_repo(
    repo_id: str,
    x_preparer_secret: str | None = Header(default=None),
) -> dict:
    _check_secret(x_preparer_secret)
    if not _REPO_ID.fullmatch(repo_id):
        raise HTTPException(status_code=422, detail="invalid repo id")
    root = (DATA_ROOT / repo_id).resolve()
    if not root.is_relative_to(DATA_ROOT.resolve()):
        raise HTTPException(status_code=422, detail="invalid repo id")
    if root.exists():
        shutil.rmtree(root)
    return {"ok": True, "repo_id": repo_id}
