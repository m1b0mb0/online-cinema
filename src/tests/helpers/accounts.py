from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import UserGroupEnum, UserGroupModel, UserModel
from src.security.interfaces import JWTAuthManagerInterface


async def create_auth_headers(
    db_session: AsyncSession,
    jwt_manager: JWTAuthManagerInterface,
    group_name: UserGroupEnum,
    email: str,
) -> dict[str, str]:
    group = await db_session.scalar(
        select(UserGroupModel).where(UserGroupModel.name == group_name)
    )
    user = UserModel(
        email=email,
        _hashed_password="not-used-in-permission-tests",
        is_active=True,
        group_id=group.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    access_token = jwt_manager.create_access_token({"user_id": user.id})
    return {"Authorization": f"Bearer {access_token}"}
