"""Workspace onboarding, membership, and invites (one owned workspace per user)."""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Notification,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    new_id,
    utcnow,
)
from app.errors import ApiError


def invite_display_name(first_name: str | None, last_name: str | None, email: str) -> str:
    parts = [p for p in ((first_name or "").strip(), (last_name or "").strip()) if p]
    return " ".join(parts) if parts else email.split("@", 1)[0]


def invite_full_name(first_name: str | None, last_name: str | None, email: str) -> str:
    parts = [p for p in ((first_name or "").strip(), (last_name or "").strip()) if p]
    return " ".join(parts) if parts else invite_display_name(None, None, email)


@dataclass
class MembershipView:
    workspace: Workspace
    role: str


async def membership_for_user(db: AsyncSession, user_id: str) -> MembershipView | None:
    """Primary membership (owned workspace first, else earliest join)."""
    memberships = await list_memberships_for_user(db, user_id)
    if not memberships:
        return None
    owned = [m for m in memberships if m.role == "owner"]
    return owned[0] if owned else memberships[0]


async def list_memberships_for_user(db: AsyncSession, user_id: str) -> list[MembershipView]:
    rows = await db.execute(
        select(WorkspaceMember, Workspace)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(WorkspaceMember.created_at.asc())
    )
    return [
        MembershipView(workspace=workspace, role=member.role)
        for member, workspace in rows.all()
    ]


async def membership_in_workspace(
    db: AsyncSession, user_id: str, workspace_id: str,
) -> MembershipView | None:
    row = await db.execute(
        select(WorkspaceMember, Workspace)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .limit(1)
    )
    found = row.first()
    if found is None:
        return None
    member, workspace = found
    return MembershipView(workspace=workspace, role=member.role)


async def needs_onboarding(db: AsyncSession, user: User) -> bool:
    exists = await db.scalar(
        select(WorkspaceMember.id).where(WorkspaceMember.user_id == user.id).limit(1)
    )
    return exists is None


async def owned_workspace(db: AsyncSession, user_id: str) -> Workspace | None:
    return await db.scalar(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.role == "owner",
        )
        .limit(1)
    )


async def ensure_default_workspace(
    db: AsyncSession,
    owner: User,
    *,
    name: str = "Deflake",
    member: User | None = None,
) -> Workspace:
    existing = await owned_workspace(db, owner.id)
    if existing is not None:
        workspace = existing
    else:
        workspace = Workspace(id=new_id(), name=name, created_by=owner.id)
        db.add(workspace)
        await db.flush()
        db.add(WorkspaceMember(
            id=new_id(),
            workspace_id=workspace.id,
            user_id=owner.id,
            role="owner",
        ))
        await db.flush()

    if member is not None:
        already = await db.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == member.id,
            )
        )
        if already is None:
            db.add(WorkspaceMember(
                id=new_id(),
                workspace_id=workspace.id,
                user_id=member.id,
                role="member",
            ))
    return workspace


async def create_workspace_for_owner(
    db: AsyncSession,
    owner: User,
    name: str,
) -> Workspace:
    if await owned_workspace(db, owner.id) is not None:
        raise ApiError(400, "workspace_exists", "You already have a workspace.")
    workspace = Workspace(id=new_id(), name=name.strip(), created_by=owner.id)
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(
        id=new_id(),
        workspace_id=workspace.id,
        user_id=owner.id,
        role="owner",
    ))
    owner.role = "owner"
    await db.flush()
    return workspace


async def create_invite(
    db: AsyncSession,
    *,
    workspace: Workspace,
    invited_by: User,
    email: str,
    first_name: str | None,
    last_name: str | None,
    public_base_url: str,
) -> WorkspaceInvite:
    email_norm = email.strip().lower()
    if email_norm == invited_by.email.lower():
        raise ApiError(400, "invite_self", "You can't invite yourself.")

    existing_member_user = await db.scalar(select(User).where(User.email == email_norm))
    if existing_member_user is not None:
        already = await db.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == existing_member_user.id,
            )
        )
        if already is not None:
            raise ApiError(400, "already_member", f"{email_norm} is already in this workspace.")

    pending = await db.scalar(
        select(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace.id,
            WorkspaceInvite.email == email_norm,
            WorkspaceInvite.status == "pending",
        )
    )
    if pending is not None:
        return pending

    invite = WorkspaceInvite(
        id=new_id(),
        workspace_id=workspace.id,
        email=email_norm,
        first_name=(first_name or "").strip() or None,
        last_name=(last_name or "").strip() or None,
        token=secrets.token_urlsafe(24),
        invited_by=invited_by.id,
        status="pending",
    )
    db.add(invite)
    await db.flush()

    if existing_member_user is not None:
        link = f"/notifications"
        db.add(Notification(
            id=new_id(),
            user_id=existing_member_user.id,
            type="workspace_invite",
            title=f"Invitation to {workspace.name}",
            body=(
                f"{invited_by.full_name} invited you to join the workspace "
                f"“{workspace.name}”."
            ),
            link=link,
            data={
                "invite_id": invite.id,
                "invite_token": invite.token,
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
                "invited_by_name": invited_by.full_name,
            },
        ))
    else:
        # No SMTP in this MVP: leave a copyable link on the inviter's notifications.
        join_url = f"{public_base_url.rstrip('/')}/create-account?invite={invite.token}"
        db.add(Notification(
            id=new_id(),
            user_id=invited_by.id,
            type="invite_link",
            title=f"Invite link for {email_norm}",
            body=(
                f"Share this link so {email_norm} can join “{workspace.name}”: {join_url}"
            ),
            link=join_url,
            data={
                "invite_id": invite.id,
                "invite_token": invite.token,
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
                "email": email_norm,
            },
        ))
    return invite


async def get_pending_invite_by_token(db: AsyncSession, token: str) -> WorkspaceInvite | None:
    return await db.scalar(
        select(WorkspaceInvite).where(
            WorkspaceInvite.token == token,
            WorkspaceInvite.status == "pending",
        )
    )


async def accept_invite(
    db: AsyncSession,
    invite: WorkspaceInvite,
    user: User,
) -> Workspace:
    if invite.status != "pending":
        raise ApiError(400, "invite_used", "This invitation is no longer valid.")
    if user.email.lower() != invite.email.lower():
        raise ApiError(
            403,
            "invite_email_mismatch",
            "Sign in with the email address this invitation was sent to.",
        )

    workspace = await db.get(Workspace, invite.workspace_id)
    if workspace is None:
        raise ApiError(404, "workspace_not_found", "Workspace not found.")

    already = await db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if already is None:
        db.add(WorkspaceMember(
            id=new_id(),
            workspace_id=workspace.id,
            user_id=user.id,
            role="member",
        ))
        if user.role != "owner":
            user.role = "member"

    invite.status = "accepted"
    invite.accepted_at = utcnow()
    invite.accepted_by = user.id

    # Mark matching invite notifications as read.
    notes = (
        await db.scalars(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.type == "workspace_invite",
                Notification.read_at.is_(None),
            )
        )
    ).all()
    now = utcnow()
    for note in notes:
        data = note.data or {}
        if data.get("invite_id") == invite.id:
            note.read_at = now

    await db.flush()
    return workspace


async def list_workspace_member_users(db: AsyncSession, workspace_id: str) -> list[User]:
    rows = await db.scalars(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(User.created_at)
    )
    return list(rows.all())


async def list_workspace_members_with_roles(
    db: AsyncSession, workspace_id: str,
) -> list[tuple[User, str]]:
    rows = await db.execute(
        select(User, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(User.created_at)
    )
    return list(rows.all())


async def leave_workspace(db: AsyncSession, user_id: str, workspace_id: str) -> None:
    membership = await membership_in_workspace(db, user_id, workspace_id)
    if membership is None:
        raise ApiError(404, "workspace_not_found", "Workspace not found.")
    if membership.role == "owner":
        raise ApiError(
            400,
            "cannot_leave_owned",
            "You own this workspace. Transfer ownership before leaving.",
        )
    row = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if row is not None:
        await db.delete(row)
        await db.flush()


async def remove_workspace_member(
    db: AsyncSession,
    *,
    actor_id: str,
    workspace_id: str,
    member_user_id: str,
) -> None:
    actor = await membership_in_workspace(db, actor_id, workspace_id)
    if actor is None or actor.role != "owner":
        raise ApiError(403, "forbidden", "Only the workspace owner can remove members.")
    if member_user_id == actor_id:
        raise ApiError(400, "cannot_remove_self", "You can't remove yourself. Leave the workspace instead.")
    target = await membership_in_workspace(db, member_user_id, workspace_id)
    if target is None:
        raise ApiError(404, "member_not_found", "Member not found in this workspace.")
    if target.role == "owner":
        raise ApiError(400, "cannot_remove_owner", "The workspace owner can't be removed.")
    row = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == member_user_id,
        )
    )
    if row is not None:
        await db.delete(row)
        await db.flush()
