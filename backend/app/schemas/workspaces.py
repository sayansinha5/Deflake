from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import Email

InviteToken = Annotated[str, Field(min_length=8, max_length=64)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    role: Literal["owner", "member"]


class WorkspaceListItemOut(BaseModel):
    id: str
    name: str
    role: Literal["owner", "member"]
    member_count: int = 0


class WorkspaceListOut(BaseModel):
    owned: WorkspaceListItemOut | None = None
    member_of: list[WorkspaceListItemOut] = []


class InvitePersonIn(StrictModel):
    email: Email
    first_name: str | None = Field(default=None, max_length=60)
    last_name: str | None = Field(default=None, max_length=60)


class OnboardingIn(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    invites: list[InvitePersonIn] = Field(default_factory=list, max_length=20)


class OnboardingOut(BaseModel):
    workspace: WorkspaceOut
    invites_created: int
    invite_links: list[dict]


class InvitePreviewOut(BaseModel):
    email: str
    first_name: str | None
    last_name: str | None
    full_name: str
    workspace_name: str
    status: Literal["pending", "accepted", "revoked"]


class AcceptInviteIn(StrictModel):
    token: InviteToken


class InviteCreateIn(StrictModel):
    email: Email
    first_name: str | None = Field(default=None, max_length=60)
    last_name: str | None = Field(default=None, max_length=60)


class InviteCreatedOut(BaseModel):
    id: str
    email: str
    token: str
    status: str
    invite_url: str


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str
    link: str | None
    data: dict | None
    read_at: datetime | None
    created_at: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int
    limit: int
    offset: int


class UnreadCountOut(BaseModel):
    unread: int
