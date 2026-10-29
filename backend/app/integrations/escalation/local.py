"""In-process escalation. The bundle stays on the Escalation row."""
from app.integrations.escalation.base import StatusResult, SubmitResult


class LocalProvider:
    name = "local"

    async def submit(self, bundle: dict, idempotency_key: str) -> SubmitResult:
        return SubmitResult(
            provider=self.name,
            external_ref=f"local:{idempotency_key}",
            status="submitted",
        )

    async def status(self, external_ref: str) -> StatusResult:
        return StatusResult(status="submitted", response=None)
