from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# Format check only; the demo accounts use the reserved .local domain, which strict
# validators reject.
Email = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SignInIn(StrictModel):
    email: Email
    password: str = Field(min_length=1, max_length=256)


class RegisterIn(StrictModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: Email
    password: str = Field(min_length=1, max_length=256)
    invite_token: str | None = Field(default=None, min_length=8, max_length=64)


class PasswordChangeIn(StrictModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class WorkspaceSummaryOut(BaseModel):
    id: str
    name: str
    role: Literal["owner", "member"]


class MeOut(BaseModel):
    id: str
    full_name: str
    email: str
    role: Literal["owner", "member"]
    is_admin: bool
    expires_at: datetime
    needs_onboarding: bool = False
    workspace: WorkspaceSummaryOut | None = None


class MemberOut(BaseModel):
    id: str
    full_name: str
    email: str
    role: Literal["owner", "member"]
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
