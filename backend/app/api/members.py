from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, get_db, get_settings_dep, require_owner
from app.config import Settings
from app.db.models import User, WorkspaceMember
from app.errors import ApiError
from app.schemas.auth import UUID_PATTERN, MemberOut
from app.security import audit
from app.services import workspaces as workspace_service

router = APIRouter(prefix="/members", tags=["members"])


def _out(user: User, role: str | None = None) -> MemberOut:
    return MemberOut(
        id=user.id, full_name=user.full_name, email=user.email,
        role=(role or user.role),  # type: ignore[arg-type]
        is_active=user.is_active, created_at=user.created_at, last_login_at=user.last_login_at,
    )


@router.get("", response_model=list[MemberOut])
async def list_members(
    owner: CurrentSession = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> list[MemberOut]:
    workspace = await workspace_service.owned_workspace(db, owner.user.id)
    if workspace is None:
        users = (await db.scalars(select(User).order_by(User.created_at))).all()
        return [_out(u) for u in users]
    rows = await db.execute(
        select(User, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace.id)
        .order_by(User.created_at)
    )
    return [_out(user, role) for user, role in rows.all()]


@router.post("/{member_id}/deactivate", response_model=MemberOut)
async def deactivate_member(
    request: Request,
    member_id: str = Path(pattern=UUID_PATTERN),
    owner: CurrentSession = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> MemberOut:
    if member_id == owner.user.id:
        raise ApiError(400, "cannot_deactivate_self", "You can't deactivate your own account.")
    user = await db.get(User, member_id)
    if user is None:
        raise ApiError(404, "member_not_found", "Member not found.")
    if user.role == "owner":
        raise ApiError(400, "cannot_deactivate_owner", "The workspace owner can't be deactivated.")
    if user.is_active:
        user.is_active = False
        audit.record(
            db, settings, "member_deactivate", "success", owner.user.id,
            request.client.host if request.client else None,
            {"member_hash": audit.salted_hash(settings, user.id)},
        )
        await db.commit()
    return _out(user)
