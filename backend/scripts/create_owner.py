"""Creates the workspace Owner account from OWNER_* settings if it does not exist yet.

Safe to run on every start: an existing Owner is left unchanged.
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


def _email(value: str | None) -> str:
    return (value or "").split("#", 1)[0].strip().lower()


async def ensure_accounts() -> str:
    settings = get_settings()
    engine = build_engine(settings)
    lines: list[str] = []
    try:
        async with build_sessionmaker(engine)() as db:
            email = _email(settings.owner_email)
            existing = await db.scalar(select(User).where(User.email == email))
            if existing is None:
                db.add(User(
                    email=email,
                    full_name=settings.owner_name,
                    password_hash=hash_password(settings.owner_password.get_secret_value()),
                    role="owner",
                ))
                lines.append(f"Created Owner {email}.")
            elif existing.role != "owner":
                lines.append(
                    f"An account with {email} exists but is not the Owner; left unchanged."
                )
            else:
                lines.append(f"Owner {email} already exists.")

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
                    db.add(User(
                        email=demo_email,
                        full_name="Demo Judge",
                        password_hash=hash_password(demo_password.get_secret_value()),
                        role="member",
                    ))
                    lines.append(f"Created demo account {demo_email}.")
            await db.commit()
            return "\n".join(lines)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(asyncio.run(ensure_accounts()))
