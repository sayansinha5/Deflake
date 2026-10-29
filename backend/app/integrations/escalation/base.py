"""Provider interface for one evidence bundle. Spending approval is not part of it."""
from dataclasses import dataclass
from typing import Protocol


class ProviderUnavailable(Exception):
    """The provider is not configured, or it refused the call before accepting work."""


class ProviderError(Exception):
    """The provider answered, but the task id or status could not be used."""


@dataclass
class SubmitResult:
    provider: str
    external_ref: str
    status: str


@dataclass
class StatusResult:
    status: str
    response: str | None = None


class EscalationProvider(Protocol):
    name: str

    async def submit(self, bundle: dict, idempotency_key: str) -> SubmitResult:
        """Open one external task. The caller owns the idempotency key."""

    async def status(self, external_ref: str) -> StatusResult:
        """Read status. This must not approve work or spend money."""
