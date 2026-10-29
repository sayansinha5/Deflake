from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TestId = Annotated[
    str,
    Field(
        min_length=4,
        max_length=300,
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.py(::[A-Za-z0-9_.\-\[\]]+)*$",
    ),
]
Seed = Annotated[int, Field(ge=0, lt=2**32)]


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    patch: str | None = Field(default=None, max_length=200_000)
    mode: Literal["suite", "tests"] = "suite"
    tests: list[TestId] | None = Field(default=None, max_length=2000)
    iterations: int = Field(default=1, ge=1, le=600)
    seeds: list[Seed] | None = None
    hash_seeds: list[Seed] | None = None
    random_order: bool = True
    order: list[TestId] | None = Field(default=None, max_length=2000)
    timeout_s: int = Field(default=60, ge=1, le=300)
    iteration_timeout_s: int = Field(default=300, ge=5, le=900)

    @model_validator(mode="after")
    def _check(self) -> "Job":
        if self.mode == "tests" and not self.tests and not self.order:
            raise ValueError("mode 'tests' needs tests or order")
        for name in ("seeds", "hash_seeds"):
            values = getattr(self, name)
            if values is not None and len(values) != self.iterations:
                raise ValueError(f"{name} must have one value per iteration")
        if self.order is not None:
            if len(set(self.order)) != len(self.order):
                raise ValueError("order must not repeat a test")
            if self.random_order:
                raise ValueError("an explicit order needs random_order=false")
        for test in (self.tests or []) + (self.order or []):
            if ".." in test.split("::")[0].split("/"):
                raise ValueError("test paths must stay inside the repository")
        return self


class TestOutcome(BaseModel):
    test_id: str
    outcome: Literal["passed", "failed", "error", "skipped", "timeout"]
    duration_ms: int
    traceback: str | None = None


class Iteration(BaseModel):
    index: int
    seed: int
    hash_seed: int
    status: Literal["ok", "collection_error", "timeout", "crashed"]
    exit_code: int | None
    duration_ms: int
    order: list[str]
    results: list[TestOutcome]
    error: str | None = None


class JobResult(BaseModel):
    repo_id: str
    patch_applied: bool
    iterations: list[Iteration]
