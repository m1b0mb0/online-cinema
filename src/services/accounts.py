from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import BaseAppSettings
from src.database import ActivationTokenModel, UserModel
from src.notifications import EmailSenderInterface
from src.schemas.accounts import (
    MessageResponseSchema,
    UserActivationRequestSchema,
)


async def get_user_by_email(db: AsyncSession, email: str) -> UserModel | None:
    return await db.scalar(select(UserModel).where(UserModel.email == email))


def build_account_link(
    settings: BaseAppSettings, path: str, query_params: dict[str, str] | None = None
) -> str:
    if not query_params:
        return f"{settings.APP_BASE_URL}{path}"
    return f"{settings.APP_BASE_URL}{path}?{urlencode(query_params)}"


async def activate_user_account(
    token_record: UserActivationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    settings: BaseAppSettings,
    email_sender: EmailSenderInterface,
) -> MessageResponseSchema:
    db_user = await get_user_by_email(db, token_record.email)

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    if db_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is already active.",
        )

    activation_token = await db.scalar(
        select(ActivationTokenModel).where(
            ActivationTokenModel.token == token_record.token,
            ActivationTokenModel.user_id == db_user.id,
        )
    )

    if not activation_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    expires_at = activation_token.expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    db_user.is_active = True
    await db.delete(activation_token)
    await db.commit()

    login_link = build_account_link(settings, "/accounts/login/")

    background_tasks.add_task(
        email_sender.send_activation_complete_email, str(token_record.email), login_link
    )

    return MessageResponseSchema(message="User account activated successfully.")
