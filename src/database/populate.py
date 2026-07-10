import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db_contextmanager
from src.database.models.accounts import UserGroupModel, UserGroupEnum


async def populate_user_groups(db_session: AsyncSession | None = None) -> None:
    """Create default user groups if they do not exist."""
    if db_session is None:
        async with get_db_contextmanager() as session:
            await _populate_user_groups(session)
        return

    await _populate_user_groups(db_session)


async def _populate_user_groups(session: AsyncSession) -> None:
    for group_name in UserGroupEnum:
        exists = await session.scalar(
            select(UserGroupModel).where(UserGroupModel.name == group_name)
        )
        if not exists:
            session.add(UserGroupModel(name=group_name))
    await session.commit()
    print("User groups populated successfully.")


async def main() -> None:
    await populate_user_groups()


if __name__ == "__main__":
    asyncio.run(main())
