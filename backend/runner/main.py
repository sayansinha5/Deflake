import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from runner.sandbox import JobError, run_job
from runner.schemas import Job, JobResult

SECRET = os.environ.get("RUNNER_SHARED_SECRET", "")
REPOS_DIR = Path(os.environ.get("RUNNER_REPOS_DIR", "/repos"))
REPOS_DATA_DIR = Path(os.environ.get("RUNNER_REPOS_DATA_DIR", "/repos-data"))
WORK_DIR = Path(os.environ.get("RUNNER_WORKDIR", "/work"))

if len(SECRET) < 16:
    raise RuntimeError("RUNNER_SHARED_SECRET must be set (at least 16 characters).")

app = FastAPI(title="Deflake runner", docs_url=None, redoc_url=None, openapi_url=None)


def _check_secret(given: str | None) -> None:
    if not given or not hmac.compare_digest(given.encode(), SECRET.encode()):
        raise HTTPException(status_code=401, detail="unauthorised")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/jobs", response_model=JobResult)
def jobs(job: Job, x_runner_secret: str | None = Header(default=None)) -> JobResult:
    _check_secret(x_runner_secret)
    try:
        return run_job(job, REPOS_DIR, WORK_DIR, repos_data_dir=REPOS_DATA_DIR)
    except JobError as exc:
        return JSONResponse(status_code=422, content={"error": {"code": exc.code,
                                                                "message": exc.message}})
