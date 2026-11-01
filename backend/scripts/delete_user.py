"""One-off: delete a user and owned workspace data so they can sign up again."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.engine import build_engine, build_sessionmaker  # noqa: E402
from app.db.models import GithubAccount, Repo, User, Workspace  # noqa: E402
from app.services.import_repos import _delete_scan_data  # noqa: E402


async def delete_user(email: str) -> None:
    email = email.strip().lower()
    settings = get_settings()
    engine = build_engine(settings)
    async with build_sessionmaker(engine)() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"USER_NOT_FOUND {email}")
            return

        uid = user.id
        owned_ids = list(await db.scalars(select(Workspace.id).where(Workspace.created_by == uid)))
        print(f"USER {uid} owned_workspaces={owned_ids}")

        n = await db.execute(text("DELETE FROM notifications WHERE user_id=:uid"), {"uid": uid})
        print(f"notifications {n.rowcount}")

        if owned_ids:
            placeholders = ", ".join(f":w{i}" for i in range(len(owned_ids)))
            params = {f"w{i}": wid for i, wid in enumerate(owned_ids)}
            params.update({"uid": uid, "email": email})
            inv = await db.execute(
                text(
                    f"DELETE FROM workspace_invites WHERE workspace_id IN ({placeholders}) "
                    "OR invited_by=:uid OR accepted_by=:uid OR email=:email"
                ),
                params,
            )
            wm = await db.execute(
                text(
                    f"DELETE FROM workspace_members WHERE workspace_id IN ({placeholders}) "
                    "OR user_id=:uid"
                ),
                params,
            )
        else:
            inv = await db.execute(
                text(
                    "DELETE FROM workspace_invites WHERE invited_by=:uid "
                    "OR accepted_by=:uid OR email=:email"
                ),
                {"uid": uid, "email": email},
            )
            wm = await db.execute(
                text("DELETE FROM workspace_members WHERE user_id=:uid"),
                {"uid": uid},
            )
        print(f"invites {inv.rowcount}")
        print(f"members {wm.rowcount}")

        gh = await db.scalar(select(GithubAccount).where(GithubAccount.user_id == uid))
        if gh is not None:
            r = await db.execute(
                text("UPDATE repos SET github_account_id=NULL WHERE github_account_id=:gid"),
                {"gid": gh.id},
            )
            print(f"repos_detach_gh {r.rowcount}")
            await db.execute(text("DELETE FROM github_accounts WHERE id=:gid"), {"gid": gh.id})
            print(f"github_deleted {gh.id}")

        owned_repos = list(await db.scalars(select(Repo).where(Repo.created_by == uid)))
        for repo in owned_repos:
            await _delete_scan_data(db, repo.id)
            await db.delete(repo)
        print(f"repos_deleted {len(owned_repos)}")

        await db.execute(text("UPDATE runs SET created_by=NULL WHERE created_by=:uid"), {"uid": uid})
        await db.execute(
            text("UPDATE workspace_defaults SET updated_by=NULL WHERE updated_by=:uid"),
            {"uid": uid},
        )

        if owned_ids:
            placeholders = ", ".join(f":w{i}" for i in range(len(owned_ids)))
            params = {f"w{i}": wid for i, wid in enumerate(owned_ids)}
            wdel = await db.execute(
                text(f"DELETE FROM workspaces WHERE id IN ({placeholders})"),
                params,
            )
            print(f"workspaces {wdel.rowcount}")

        rs = await db.execute(text("DELETE FROM revoked_sessions WHERE user_id=:uid"), {"uid": uid})
        print(f"sessions {rs.rowcount}")

        await db.execute(text("DELETE FROM users WHERE id=:uid"), {"uid": uid})
        print(f"user_deleted {email}")
        await db.commit()
    await engine.dispose()
    print("DONE")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "sayansinha5@gmail.com"
    asyncio.run(delete_user(target))
