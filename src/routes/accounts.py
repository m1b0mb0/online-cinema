from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import (
    get_jwt_auth_manager,
    get_settings,
    BaseAppSettings,
    get_accounts_email_notificator,
)
from src.database import (
    get_db,
    UserModel,
    UserProfileModel,
    UserGroupModel,
    UserGroupEnum,
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
)
from src.exceptions import BaseSecurityError
from src.security.dependencies import get_current_active_user
from src.security.interfaces import JWTAuthManagerInterface
from src.notifications import EmailSenderInterface
from src.schemas.accounts import (
    UserRegistrationRequestSchema,
    UserRegistrationResponseSchema,
    UserActivationRequestSchema,
    MessageResponseSchema,
    PasswordResetRequestSchema,
    PasswordResetCompleteRequestSchema,
    UserLoginRequestSchema,
    UserLoginResponseSchema,
    UserLogoutRequestSchema,
    TokenRefreshRequestSchema,
    TokenRefreshResponseSchema,
    ChangePasswordRequestSchema,
)

router = APIRouter()


async def get_user_by_email(db: AsyncSession, email: str) -> UserModel | None:
    return await db.scalar(select(UserModel).where(UserModel.email == email))


@router.post(
    "/register/",
    response_model=UserRegistrationResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    user_data: UserRegistrationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> UserRegistrationResponseSchema:
    existing_user = await get_user_by_email(db, user_data.email)

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with this email {user_data.email} already exists.",
        )

    user_group = await db.scalar(
        select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    )
    if not user_group:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default user group not found.",
        )

    try:
        new_user = UserModel.create(
            email=str(user_data.email),
            raw_password=user_data.password,
            group_id=user_group.id,
        )
        db.add(new_user)
        await db.flush()

        user_profile = UserProfileModel(user_id=new_user.id)
        db.add(user_profile)

        activation_token = ActivationTokenModel(user_id=new_user.id)
        db.add(activation_token)

        await db.commit()
        await db.refresh(new_user)
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation.",
        ) from e
    else:
        activation_link = (
            f"http://127.0.0.1/accounts/activate/?token={activation_token.token}"
        )

        background_tasks.add_task(
            email_sender.send_activation_email, str(new_user.email), activation_link
        )

        return UserRegistrationResponseSchema.model_validate(new_user)


@router.post("/activate/", response_model=MessageResponseSchema)
async def activate_user(
    token_record: UserActivationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
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

    expires_at = cast(datetime, activation_token.expires_at).replace(
        tzinfo=timezone.utc
    )

    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    db_user.is_active = True
    await db.delete(activation_token)
    await db.commit()

    login_link = "http://127.0.0.1/accounts/login/"

    background_tasks.add_task(
        email_sender.send_activation_complete_email, str(token_record.email), login_link
    )

    return MessageResponseSchema(message="User account activated successfully.")


@router.post("/resend-activation/", response_model=MessageResponseSchema)
async def resend_activation_token(
    data: PasswordResetRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:

    user = await get_user_by_email(db, data.email)

    if not user or user.is_active:
        return MessageResponseSchema(
            message="If you are registered, you will receive an email with instructions."
        )

    await db.execute(
        delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )

    activation_token = ActivationTokenModel(user_id=user.id)
    db.add(activation_token)
    await db.commit()

    activation_link = (
        f"http://127.0.0.1/accounts/activate/?token={activation_token.token}"
    )
    background_tasks.add_task(
        email_sender.send_activation_email, str(user.email), activation_link
    )

    return MessageResponseSchema(
        message="If you are registered, you will receive an email with instructions."
    )


@router.post("/password-reset/request/", response_model=MessageResponseSchema)
async def reset_password_token(
    request_data: PasswordResetRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    db_user = await get_user_by_email(db, request_data.email)

    if not db_user or not db_user.is_active:
        return MessageResponseSchema(
            message="If you are registered, you will receive an email with instructions."
        )

    await db.execute(
        delete(PasswordResetTokenModel).where(
            PasswordResetTokenModel.user_id == db_user.id
        )
    )

    reset_token = PasswordResetTokenModel(user_id=db_user.id)
    db.add(reset_token)
    await db.commit()

    password_reset_complete_link = (
        f"http://127.0.0.1/accounts/password-reset-complete/?token={reset_token.token}"
    )

    background_tasks.add_task(
        email_sender.send_password_reset_email,
        str(request_data.email),
        password_reset_complete_link,
    )

    return MessageResponseSchema(
        message="If you are registered, you will receive an email with instructions."
    )


@router.post("/reset-password/complete/", response_model=MessageResponseSchema)
async def reset_password(
    data: PasswordResetCompleteRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    db_user = await get_user_by_email(db, data.email)

    if not db_user or not db_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
        )

    password_token = await db.scalar(
        select(PasswordResetTokenModel).where(
            PasswordResetTokenModel.user_id == db_user.id,
        )
    )

    if not password_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
        )

    expires_at = cast(datetime, password_token.expires_at).replace(tzinfo=timezone.utc)

    if password_token.token != data.token or expires_at < datetime.now(timezone.utc):
        await db.delete(password_token)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token."
        )

    try:
        db_user.password = data.password
        await db.delete(password_token)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resetting the password.",
        )

    login_link = "http://127.0.0.1/accounts/login/"

    background_tasks.add_task(
        email_sender.send_password_reset_complete_email, str(data.email), login_link
    )

    return MessageResponseSchema(message="Password reset successfully.")


@router.post("/change-password/", response_model=MessageResponseSchema)
async def change_password(
    data: ChangePasswordRequestSchema,
    user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    if not user.verify_password(data.old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    try:
        user.password = data.new_password
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while changing the password.",
        )

    return MessageResponseSchema(message="Password changed successfully.")


@router.post(
    "/login/",
    response_model=UserLoginResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def login(
    login_data: UserLoginRequestSchema,
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
    settings: BaseAppSettings = Depends(get_settings),
) -> UserLoginResponseSchema:
    db_user = await get_user_by_email(db, login_data.email)

    if not db_user or not db_user.verify_password(login_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not db_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not activated.",
        )

    jwt_access_token = jwt_manager.create_access_token({"user_id": db_user.id})
    jwt_refresh_token = jwt_manager.create_refresh_token({"user_id": db_user.id})

    refresh_token = RefreshTokenModel.create(
        user_id=db_user.id, days_valid=settings.LOGIN_TIME_DAYS, token=jwt_refresh_token
    )
    try:
        db.add(refresh_token)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )

    return UserLoginResponseSchema(
        access_token=jwt_access_token,
        refresh_token=jwt_refresh_token,
    )


@router.post("/logout/", response_model=MessageResponseSchema)
async def logout(
    token_data: UserLogoutRequestSchema, db: AsyncSession = Depends(get_db)
) -> MessageResponseSchema:
    refresh_token = await db.scalar(
        select(RefreshTokenModel).where(
            RefreshTokenModel.token == token_data.refresh_token
        )
    )

    if refresh_token:
        await db.delete(refresh_token)
        await db.commit()

    return MessageResponseSchema(message="Successfully logged out.")


@router.post("/refresh/", response_model=TokenRefreshResponseSchema)
async def access_token_refresh(
    token_data: TokenRefreshRequestSchema,
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> TokenRefreshResponseSchema:
    try:
        token_payload = jwt_manager.decode_refresh_token(token_data.refresh_token)
    except BaseSecurityError as error:
        raise HTTPException(status_code=400, detail=str(error))

    refresh_token = await db.scalar(
        select(RefreshTokenModel).where(
            RefreshTokenModel.token == token_data.refresh_token
        )
    )

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found."
        )

    user_id = token_payload["user_id"]

    if refresh_token.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found."
        )

    db_user = await db.get(UserModel, user_id)

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    if not db_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not activated.",
        )

    new_access_token = jwt_manager.create_access_token({"user_id": user_id})

    return TokenRefreshResponseSchema(access_token=new_access_token)
