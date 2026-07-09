from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.security.dependencies import get_admin_user
from src.schemas.accounts import MessageResponseSchema
from src.database import get_db, UserModel, UserGroupModel, UserGroupEnum

router = APIRouter()


@router.post("/users/{user_id}/group/", response_model=MessageResponseSchema)
async def change_user_group(
    group_name: str,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_admin_user),
) -> MessageResponseSchema:
    user = await db.scalar(
        select(UserModel)
        .where(UserModel.id == user_id)
        .options(selectinload(UserModel.group))
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    new_group = await db.scalar(
        select(UserGroupModel).where(UserGroupModel.name == group_name)
    )
    if not new_group:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid group name."
        )

    user.group_id = new_group.id
    await db.commit()

    return MessageResponseSchema(message="User group has been updated successfully.")


@router.post("/users/{user_id}/activate/", response_model=MessageResponseSchema)
async def activate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_admin_user),
) -> MessageResponseSchema:
    user = await db.get(UserModel, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already active.",
        )

    user.is_active = True
    await db.commit()

    return MessageResponseSchema(message="User activated successfully.")
