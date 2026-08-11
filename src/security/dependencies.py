from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import get_jwt_auth_manager
from src.database import UserGroupEnum, UserModel, get_db
from src.exceptions import BaseSecurityError
from src.security.interfaces import JWTAuthManagerInterface

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/accounts/login/")
ALLOWED_GROUPS = {
    UserGroupEnum.ADMIN,
    UserGroupEnum.MODERATOR,
}


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> UserModel:
    try:
        token_payload = jwt_manager.decode_access_token(token)
    except BaseSecurityError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token."
        ) from error

    user_id = token_payload["user_id"]
    user = await db.scalar(
        select(UserModel)
        .where(UserModel.id == user_id)
        .options(selectinload(UserModel.group))
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    return user


async def get_current_active_user(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not activated.",
        )
    return current_user


async def get_admin_user(
    current_user: UserModel = Depends(get_current_active_user),
) -> UserModel:
    if current_user.group.name != UserGroupEnum.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user


async def get_moderator_or_admin_user(
    current_user: UserModel = Depends(get_current_active_user),
) -> UserModel:
    if current_user.group.name not in ALLOWED_GROUPS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user
