import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete

from src.celery_app import celery_app
from src.database.models.accounts import ActivationTokenModel, PasswordResetTokenModel
from src.database.session import AsyncSessionLocal


@celery_app.task
def delete_expired_tokens():
    """
    Celery Beat task: periodically deletes all expired activation
    and password reset tokens from the database.
    """
    asyncio.run(_delete_expired_tokens())


async def _delete_expired_tokens():
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(ActivationTokenModel).where(ActivationTokenModel.expires_at < now)
        )
        await session.execute(
            delete(PasswordResetTokenModel).where(
                PasswordResetTokenModel.expires_at < now
            )
        )
        await session.commit()
