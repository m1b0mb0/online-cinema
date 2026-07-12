from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks
from pydantic import EmailStr
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import (
    get_jwt_auth_manager,
    get_settings,
    BaseAppSettings,
    get_accounts_email_notificator,
)
from src.services import (
    get_user_by_email,
    build_account_link,
    activate_user_account,
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

router = APIRouter(tags=["Accounts"])


@router.post(
    "/register/",
    response_model=UserRegistrationResponseSchema,
    summary="User Registration",
    description="Register a new user with an email and password.",
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {
            "description": "Conflict - User with this email already exists.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "A user with this email test@example.com already exists."
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - An error occurred during user creation.",
            "content": {
                "application/json": {
                    "example": {"detail": "An error occurred during user creation."}
                }
            },
        },
    },
)
async def create_user(
    user_data: UserRegistrationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: BaseAppSettings = Depends(get_settings),
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
        activation_link = build_account_link(
            settings,
            "/accounts/activate/",
            {"email": str(new_user.email), "token": activation_token.token},
        )

        background_tasks.add_task(
            email_sender.send_activation_email, str(new_user.email), activation_link
        )

        return UserRegistrationResponseSchema.model_validate(new_user)


@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    summary="Activate User Account",
    description="Activate a user's account using their email and activation token.",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - The activation token is invalid or expired, "
            "or the user account is already active.",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid Token",
                            "value": {"detail": "Invalid or expired activation token."},
                        },
                        "already_active": {
                            "summary": "Account Already Active",
                            "value": {"detail": "User account is already active."},
                        },
                    }
                }
            },
        },
    },
)
async def activate_user(
    token_record: UserActivationRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: BaseAppSettings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    return await activate_user_account(
        token_record, background_tasks, db, settings, email_sender
    )


@router.get(
    "/activate/",
    response_model=MessageResponseSchema,
    summary="Activate User Account From Email Link",
    description=(
        "Activate a user account from the activation link sent by email. "
        "The link must include the user's email and a valid activation token."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": (
                "Bad Request - The activation token is invalid or expired, "
                "or the user account is already active."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid Token",
                            "value": {"detail": "Invalid or expired activation token."},
                        },
                        "already_active": {
                            "summary": "Account Already Active",
                            "value": {"detail": "User account is already active."},
                        },
                    }
                }
            },
        },
    },
)
async def activate_user_from_email_link(
    email: EmailStr,
    token: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: BaseAppSettings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    token_record = UserActivationRequestSchema(email=email, token=token)
    return await activate_user_account(
        token_record, background_tasks, db, settings, email_sender
    )


@router.post(
    "/resend-activation/",
    response_model=MessageResponseSchema,
    summary="Resend Activation Email",
    description=(
        "Send a new activation email for an inactive account. For privacy, the "
        "response is the same when the email is unknown or the account is already active."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Activation email request accepted.",
            "content": {
                "application/json": {
                    "example": {
                        "message": "If you are registered, you will receive an email with instructions."
                    }
                }
            },
        },
    },
)
async def resend_activation_token(
    data: PasswordResetRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: BaseAppSettings = Depends(get_settings),
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

    activation_link = build_account_link(
        settings,
        "/accounts/activate/",
        {"email": str(user.email), "token": activation_token.token},
    )
    background_tasks.add_task(
        email_sender.send_activation_email, str(user.email), activation_link
    )

    return MessageResponseSchema(
        message="If you are registered, you will receive an email with instructions."
    )


@router.post(
    "/password-reset/request/",
    response_model=MessageResponseSchema,
    summary="Request Password Reset Token",
    description=(
        "Allows a user to request a password reset token. If the user exists and is active, "
        "a new token will be generated and any existing tokens will be invalidated."
    ),
    status_code=status.HTTP_200_OK,
)
async def reset_password_token(
    request_data: PasswordResetRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: BaseAppSettings = Depends(get_settings),
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

    password_reset_complete_link = build_account_link(
        settings,
        "/accounts/reset-password/complete/",
        {"email": str(request_data.email), "token": reset_token.token},
    )

    background_tasks.add_task(
        email_sender.send_password_reset_email,
        str(request_data.email),
        password_reset_complete_link,
    )

    return MessageResponseSchema(
        message="If you are registered, you will receive an email with instructions."
    )


@router.post(
    "/reset-password/complete/",
    response_model=MessageResponseSchema,
    summary="Reset User Password",
    description="Reset a user's password if a valid token is provided.",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": (
                "Bad Request - The provided email or token is invalid, "
                "the token has expired, or the user account is not active."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_email_or_token": {
                            "summary": "Invalid Email or Token",
                            "value": {"detail": "Invalid email or token."},
                        },
                        "expired_token": {
                            "summary": "Expired Token",
                            "value": {"detail": "Invalid email or token."},
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - An error occurred while resetting the password.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "An error occurred while resetting the password."
                    }
                }
            },
        },
    },
)
async def reset_password(
    data: PasswordResetCompleteRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: BaseAppSettings = Depends(get_settings),
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

    login_link = build_account_link(settings, "/accounts/login/")

    background_tasks.add_task(
        email_sender.send_password_reset_complete_email, str(data.email), login_link
    )

    return MessageResponseSchema(message="Password reset successfully.")


@router.post(
    "/change-password/",
    response_model=MessageResponseSchema,
    summary="Change Current User Password",
    description=(
        "Change the password for the currently authenticated active user. "
        "The request must include the current password and a new password that "
        "passes password complexity validation."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - The current password is incorrect.",
            "content": {
                "application/json": {
                    "example": {"detail": "Current password is incorrect."}
                }
            },
        },
        401: {
            "description": "Unauthorized - Access token is missing or invalid.",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
        403: {
            "description": "Forbidden - User account is not activated.",
            "content": {
                "application/json": {
                    "example": {"detail": "User account is not activated."}
                }
            },
        },
        500: {
            "description": "Internal Server Error - An error occurred while changing the password.",
            "content": {
                "application/json": {
                    "example": {"detail": "An error occurred while changing the password."}
                }
            },
        },
    },
)
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
    summary="User Login",
    description="Authenticate a user and return access and refresh tokens.",
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {
            "description": "Unauthorized - Invalid email or password.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid email or password."}
                }
            },
        },
        403: {
            "description": "Forbidden - User account is not activated.",
            "content": {
                "application/json": {
                    "example": {"detail": "User account is not activated."}
                }
            },
        },
        500: {
            "description": "Internal Server Error - An error occurred while processing the request.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "An error occurred while processing the request."
                    }
                }
            },
        },
    },
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


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    summary="User Logout",
    description=(
        "Revoke a refresh token by deleting it from storage. After logout, the "
        "same refresh token cannot be used to obtain new access tokens."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Refresh token revoked or already absent.",
            "content": {
                "application/json": {
                    "example": {"message": "Successfully logged out."}
                }
            },
        },
    },
)
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


@router.post(
    "/refresh/",
    response_model=TokenRefreshResponseSchema,
    summary="Refresh Access Token",
    description="Refresh the access token using a valid refresh token.",
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - The provided refresh token is invalid or expired.",
            "content": {
                "application/json": {"example": {"detail": "Token has expired."}}
            },
        },
        401: {
            "description": "Unauthorized - Refresh token not found.",
            "content": {
                "application/json": {"example": {"detail": "Refresh token not found."}}
            },
        },
        404: {
            "description": "Not Found - The user associated with the token does not exist.",
            "content": {"application/json": {"example": {"detail": "User not found."}}},
        },
        403: {
            "description": "Forbidden - User account is not activated.",
            "content": {
                "application/json": {
                    "example": {"detail": "User account is not activated."}
                }
            },
        },
    },
)
async def refresh_access_token(
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
