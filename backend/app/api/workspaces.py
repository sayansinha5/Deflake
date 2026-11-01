from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _start_session
from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep, require_owner
from app.config import Settings
from app.db.models import Workspace, WorkspaceMember
from app.errors import ApiError
from app.schemas.auth import UUID_PATTERN, MemberOut
from app.schemas.workspaces import (
    AcceptInviteIn,
    InviteCreateIn,
    InviteCreatedOut,
    InvitePreviewOut,
    OnboardingIn,
    OnboardingOut,
    WorkspaceListItemOut,
    WorkspaceListOut,
    WorkspaceOut,
)
from app.services import workspaces as workspace_service

router = APIRouter(tags=["workspaces"])


def _workspace_out(workspace: Workspace, role: str) -> WorkspaceOut:
    return WorkspaceOut(id=workspace.id, name=workspace.name, role=role)  # type: ignore[arg-type]


def _member_out(user, role: str) -> MemberOut:
    return MemberOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=role,  # type: ignore[arg-type]
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def _member_counts(db: AsyncSession, workspace_ids: list[str]) -> dict[str, int]:
    if not workspace_ids:
        return {}
    rows = await db.execute(
        select(WorkspaceMember.workspace_id, func.count())
        .where(WorkspaceMember.workspace_id.in_(workspace_ids))
        .group_by(WorkspaceMember.workspace_id)
    )
    return {workspace_id: int(count) for workspace_id, count in rows.all()}


@router.get("/workspaces", response_model=WorkspaceListOut)
async def list_workspaces(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceListOut:
    memberships = await workspace_service.list_memberships_for_user(db, session.user.id)
    counts = await _member_counts(db, [m.workspace.id for m in memberships])
    owned = None
    member_of: list[WorkspaceListItemOut] = []
    for item in memberships:
        row = WorkspaceListItemOut(
            id=item.workspace.id,
            name=item.workspace.name,
            role=item.role,  # type: ignore[arg-type]
            member_count=counts.get(item.workspace.id, 0),
        )
        if item.role == "owner" and owned is None:
            owned = row
        elif item.role == "member":
            member_of.append(row)
    return WorkspaceListOut(owned=owned, member_of=member_of)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    membership = await workspace_service.membership_in_workspace(
        db, session.user.id, workspace_id,
    )
    if membership is None:
        raise ApiError(404, "workspace_not_found", "Workspace not found.")
    return _workspace_out(membership.workspace, membership.role)


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut])
async def list_workspace_members(
    workspace_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> list[MemberOut]:
    membership = await workspace_service.membership_in_workspace(
        db, session.user.id, workspace_id,
    )
    if membership is None:
        raise ApiError(404, "workspace_not_found", "Workspace not found.")
    rows = await workspace_service.list_workspace_members_with_roles(db, workspace_id)
    return [_member_out(user, role) for user, role in rows]


@router.post("/workspaces/{workspace_id}/leave", status_code=204)
async def leave_workspace(
    workspace_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await workspace_service.leave_workspace(db, session.user.id, workspace_id)
    await db.commit()
    return Response(status_code=204)


@router.delete("/workspaces/{workspace_id}/members/{member_id}", status_code=204)
async def remove_workspace_member(
    workspace_id: str = Path(pattern=UUID_PATTERN),
    member_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await workspace_service.remove_workspace_member(
        db,
        actor_id=session.user.id,
        workspace_id=workspace_id,
        member_user_id=member_id,
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/workspaces/onboarding", response_model=OnboardingOut)
async def complete_onboarding(
    body: OnboardingIn,
    response: Response,
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> OnboardingOut:
    if not await workspace_service.needs_onboarding(db, session.user):
        raise ApiError(400, "onboarding_done", "Onboarding is already complete.")

    workspace = await workspace_service.create_workspace_for_owner(
        db, session.user, body.name,
    )
    invite_links: list[dict] = []
    created = 0
    for person in body.invites:
        invite = await workspace_service.create_invite(
            db,
            workspace=workspace,
            invited_by=session.user,
            email=person.email,
            first_name=person.first_name,
            last_name=person.last_name,
            public_base_url=settings.public_base_url,
        )
        created += 1
        invite_links.append({
            "email": invite.email,
            "token": invite.token,
            "invite_url": (
                f"{settings.public_base_url.rstrip('/')}/create-account?invite={invite.token}"
            ),
        })
    await db.commit()
    await db.refresh(session.user)
    # Promote cookie so owner APIs work without signing out/in.
    _start_session(response, settings, session.user)
    return OnboardingOut(
        workspace=_workspace_out(workspace, "owner"),
        invites_created=created,
        invite_links=invite_links,
    )


@router.post("/workspaces/invites", response_model=InviteCreatedOut)
async def invite_member(
    body: InviteCreateIn,
    session: CurrentSession = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> InviteCreatedOut:
    workspace = await workspace_service.owned_workspace(db, session.user.id)
    if workspace is None:
        raise ApiError(400, "no_workspace", "Create a workspace before inviting people.")
    invite = await workspace_service.create_invite(
        db,
        workspace=workspace,
        invited_by=session.user,
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        public_base_url=settings.public_base_url,
    )
    await db.commit()
    return InviteCreatedOut(
        id=invite.id,
        email=invite.email,
        token=invite.token,
        status=invite.status,
        invite_url=(
            f"{settings.public_base_url.rstrip('/')}/create-account?invite={invite.token}"
        ),
    )


@router.get("/invites/{token}", response_model=InvitePreviewOut)
async def preview_invite(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InvitePreviewOut:
    invite = await workspace_service.get_pending_invite_by_token(db, token)
    if invite is None:
        # Also allow preview of accepted/revoked for clearer UI.
        from sqlalchemy import select
        from app.db.models import WorkspaceInvite

        invite = await db.scalar(select(WorkspaceInvite).where(WorkspaceInvite.token == token))
        if invite is None:
            raise ApiError(404, "invite_not_found", "Invitation not found.")
    workspace = await db.get(Workspace, invite.workspace_id)
    name = workspace.name if workspace else "Workspace"
    return InvitePreviewOut(
        email=invite.email,
        first_name=invite.first_name,
        last_name=invite.last_name,
        full_name=workspace_service.invite_full_name(
            invite.first_name, invite.last_name, invite.email,
        ),
        workspace_name=name,
        status=invite.status,  # type: ignore[arg-type]
    )


@router.post("/invites/accept", response_model=WorkspaceOut)
async def accept_invite(
    body: AcceptInviteIn,
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    invite = await workspace_service.get_pending_invite_by_token(db, body.token)
    if invite is None:
        raise ApiError(404, "invite_not_found", "Invitation not found or already used.")
    workspace = await workspace_service.accept_invite(db, invite, session.user)
    await db.commit()
    return _workspace_out(workspace, "member")
