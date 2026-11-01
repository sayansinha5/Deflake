"""Creates the workspace Owner account from OWNER_* settings if it does not exist yet.

Safe to run on every start: an existing Owner is left unchanged.
Also ensures a default workspace and attaches the demo judge as a member.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.engine import build_engine, build_sessionmaker  # noqa: E402
from app.db.models import User  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from app.services.allowlist import ensure_demo_repos_for_user  # noqa: E402
from app.services.workspaces import ensure_default_workspace  # noqa: E402


def _email(value: str | None) -> str:
    return (value or "").split("#", 1)[0].strip().lower()


async def ensure_accounts() -> str:
    settings = get_settings()
    engine = build_engine(settings)
    lines: list[str] = []
    try:
        async with build_sessionmaker(engine)() as db:
            email = _email(settings.owner_email)
            owner = await db.scalar(select(User).where(User.email == email))
            if owner is None:
                owner = User(
                    email=email,
                    full_name=settings.owner_name,
                    password_hash=hash_password(settings.owner_password.get_secret_value()),
                    role="owner",
                )
                db.add(owner)
                await db.flush()
                lines.append(f"Created Owner {email}.")
            elif owner.role != "owner":
                lines.append(
                    f"An account with {email} exists but is not the Owner; left unchanged."
                )
            else:
                lines.append(f"Owner {email} already exists.")

            demo = None
            demo_email = _email(settings.demo_account_email)
            demo_password = settings.demo_account_password
            if not demo_email or demo_password is None:
                lines.append("Demo account is not configured.")
            elif demo_email == email:
                lines.append("Demo account uses the Owner email; left unchanged.")
            else:
                demo = await db.scalar(select(User).where(User.email == demo_email))
                if demo is not None:
                    lines.append(f"Demo account {demo_email} already exists.")
                else:
                    demo = User(
                        email=demo_email,
                        full_name="Demo Judge",
                        password_hash=hash_password(demo_password.get_secret_value()),
                        role="member",
                    )
                    db.add(demo)
                    await db.flush()
                    lines.append(f"Created demo account {demo_email}.")

            if owner is not None and owner.role == "owner":
                workspace = await ensure_default_workspace(
                    db, owner, name="Deflake", member=demo if demo and demo.id != owner.id else None,
                )
                lines.append(f"Workspace ready: {workspace.name}.")
                demos = await ensure_demo_repos_for_user(db, settings, owner.id)
                if demos:
                    lines.append(f"Attached {len(demos)} demo repo(s) to Owner.")

            if demo is not None:
                demos = await ensure_demo_repos_for_user(db, settings, demo.id)
                if demos:
                    lines.append(f"Attached {len(demos)} demo repo(s) to {demo.email}.")

            await db.commit()
            return "\n".join(lines)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(asyncio.run(ensure_accounts()))
