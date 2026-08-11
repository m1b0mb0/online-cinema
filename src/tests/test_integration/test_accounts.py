from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from src.database import (
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)
from src.tasks.accounts import _delete_expired_tokens

PASSWORD = "StrongPassword123!"
NEW_PASSWORD = "NewStrongPassword123!"


async def get_user(db_session, email: str) -> UserModel | None:
    return await db_session.scalar(select(UserModel).where(UserModel.email == email))


async def get_user_group(db_session, group: UserGroupEnum) -> UserGroupModel:
    user_group = await db_session.scalar(
        select(UserGroupModel).where(UserGroupModel.name == group)
    )
    assert user_group is not None
    return user_group


async def create_user(
    db_session,
    email: str = "user@example.com",
    password: str = PASSWORD,
    group: UserGroupEnum = UserGroupEnum.USER,
    is_active: bool = True,
) -> UserModel:
    user_group = await get_user_group(db_session, group)
    user = UserModel.create(
        email=email,
        raw_password=password,
        group_id=user_group.id,
    )
    user.is_active = is_active
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_user_success(client, db_session, seed_user_groups):
    payload = {"email": "testuser@example.com", "password": PASSWORD}

    response = await client.post("/accounts/register/", json=payload)

    assert response.status_code == 201
    assert response.json()["email"] == payload["email"]

    user = await get_user(db_session, payload["email"])
    assert user is not None
    assert user.is_active is False

    activation_token = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert activation_token is not None
    assert activation_token.token
    assert activation_token.expires_at.replace(tzinfo=timezone.utc) > datetime.now(
        timezone.utc
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_password, expected_error",
    [
        ("short", "Password must contain at least 8 characters."),
        ("NoDigitHere!", "Password must contain at least one digit."),
        ("nouppercase1!", "Password must contain at least one uppercase letter."),
        ("NOLOWERCASE1!", "Password must contain at least one lower letter."),
        (
            "NoSpecial123",
            "Password must contain at least one special character",
        ),
    ],
)
async def test_register_user_password_validation(
    client,
    seed_user_groups,
    invalid_password,
    expected_error,
):
    payload = {"email": "testuser@example.com", "password": invalid_password}

    response = await client.post("/accounts/register/", json=payload)

    assert response.status_code == 422
    assert expected_error in str(response.json())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_user_conflict(client, seed_user_groups):
    payload = {"email": "duplicate@example.com", "password": PASSWORD}

    first_response = await client.post("/accounts/register/", json=payload)
    second_response = await client.post("/accounts/register/", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == (
        "A user with this email duplicate@example.com already exists."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_activate_account_success(client, db_session, seed_user_groups):
    payload = {"email": "activation@example.com", "password": PASSWORD}
    registration_response = await client.post("/accounts/register/", json=payload)
    assert registration_response.status_code == 201

    user = await get_user(db_session, payload["email"])
    assert user is not None
    token = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert token is not None

    response = await client.post(
        "/accounts/activate/",
        json={"email": payload["email"], "token": token.token},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "User account activated successfully."

    await db_session.refresh(user)
    assert user.is_active is True
    deleted_token = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert deleted_token is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_activation_email_link_can_activate_account(
    client,
    db_session,
    seed_user_groups,
    email_sender_stub,
):
    payload = {"email": "activation-link@example.com", "password": PASSWORD}
    response = await client.post("/accounts/register/", json=payload)
    assert response.status_code == 201
    assert email_sender_stub.activation_emails

    activation_link = email_sender_stub.activation_emails[-1]["activation_link"]
    parsed_link = urlparse(activation_link)
    query_params = parse_qs(parsed_link.query)

    assert parsed_link.path == "/accounts/activate/"
    assert query_params["email"] == [payload["email"]]
    assert query_params["token"][0]

    activation_response = await client.get(f"{parsed_link.path}?{parsed_link.query}")

    assert activation_response.status_code == 200
    assert email_sender_stub.activation_complete_emails[-1]["login_link"] == (
        "http://127.0.0.1:8000/accounts/login/"
    )
    user = await get_user(db_session, payload["email"])
    assert user is not None
    await db_session.refresh(user)
    assert user.is_active is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_activate_account_with_expired_token(
    client,
    db_session,
    seed_user_groups,
):
    payload = {"email": "expired@example.com", "password": PASSWORD}
    await client.post("/accounts/register/", json=payload)

    user = await get_user(db_session, payload["email"])
    assert user is not None
    token = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert token is not None
    token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()

    response = await client.post(
        "/accounts/activate/",
        json={"email": payload["email"], "token": token.token},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired activation token."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resend_activation_replaces_previous_token(
    client,
    db_session,
    seed_user_groups,
):
    payload = {"email": "resend@example.com", "password": PASSWORD}
    await client.post("/accounts/register/", json=payload)

    user = await get_user(db_session, payload["email"])
    assert user is not None
    old_token = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id)
    )
    assert old_token is not None
    user_id = user.id
    old_token_value = old_token.token

    response = await client.post(
        "/accounts/resend-activation/",
        json={"email": payload["email"]},
    )

    assert response.status_code == 200
    db_session.expire_all()
    new_token = await db_session.scalar(
        select(ActivationTokenModel).where(ActivationTokenModel.user_id == user_id)
    )
    assert new_token is not None
    assert new_token.token != old_token_value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_user_success(client, db_session, jwt_manager, seed_user_groups):
    user = await create_user(db_session, email="login@example.com")

    response = await client.post(
        "/accounts/login/",
        json={"email": user.email, "password": PASSWORD},
    )

    assert response.status_code == 201
    response_data = response.json()
    assert response_data["token_type"] == "bearer"
    assert response_data["access_token"]
    assert response_data["refresh_token"]

    access_payload = jwt_manager.decode_access_token(response_data["access_token"])
    refresh_payload = jwt_manager.decode_refresh_token(response_data["refresh_token"])
    assert access_payload["user_id"] == user.id
    assert refresh_payload["user_id"] == user.id

    stored_refresh_token = await db_session.scalar(
        select(RefreshTokenModel).where(RefreshTokenModel.user_id == user.id)
    )
    assert stored_refresh_token is not None
    assert stored_refresh_token.token == response_data["refresh_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_user_invalid_password(client, db_session, seed_user_groups):
    await create_user(db_session, email="wrong-password@example.com")

    response = await client.post(
        "/accounts/login/",
        json={"email": "wrong-password@example.com", "password": "Wrong123!"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_inactive_user(client, db_session, seed_user_groups):
    await create_user(
        db_session,
        email="inactive@example.com",
        is_active=False,
    )

    response = await client.post(
        "/accounts/login/",
        json={"email": "inactive@example.com", "password": PASSWORD},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User account is not activated."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_access_token_success(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user = await create_user(db_session, email="refresh@example.com")
    login_response = await client.post(
        "/accounts/login/",
        json={"email": user.email, "password": PASSWORD},
    )
    refresh_token = login_response.json()["refresh_token"]

    response = await client.post(
        "/accounts/refresh/",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    token_payload = jwt_manager.decode_access_token(response.json()["access_token"])
    assert token_payload["user_id"] == user.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_access_token_for_inactive_user(
    client,
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, email="refresh-inactive@example.com")
    login_response = await client.post(
        "/accounts/login/",
        json={"email": user.email, "password": PASSWORD},
    )
    refresh_token = login_response.json()["refresh_token"]

    user.is_active = False
    await db_session.commit()

    response = await client.post(
        "/accounts/refresh/",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User account is not activated."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_access_token_not_found(client, jwt_manager):
    refresh_token = jwt_manager.create_refresh_token({"user_id": 1})

    response = await client.post(
        "/accounts/refresh/",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Refresh token not found."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logout_deletes_refresh_token(client, db_session, seed_user_groups):
    user = await create_user(db_session, email="logout@example.com")
    login_response = await client.post(
        "/accounts/login/",
        json={"email": user.email, "password": PASSWORD},
    )
    refresh_token = login_response.json()["refresh_token"]

    response = await client.post(
        "/accounts/logout/",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    stored_refresh_token = await db_session.scalar(
        select(RefreshTokenModel).where(RefreshTokenModel.token == refresh_token)
    )
    assert stored_refresh_token is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logout_revokes_refresh_token_for_future_refresh(
    client,
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, email="logout-refresh@example.com")
    login_response = await client.post(
        "/accounts/login/",
        json={"email": user.email, "password": PASSWORD},
    )
    refresh_token = login_response.json()["refresh_token"]

    logout_response = await client.post(
        "/accounts/logout/",
        json={"refresh_token": refresh_token},
    )
    assert logout_response.status_code == 200

    refresh_response = await client.post(
        "/accounts/refresh/",
        json={"refresh_token": refresh_token},
    )

    assert refresh_response.status_code == 401
    assert refresh_response.json()["detail"] == "Refresh token not found."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_password_reset_flow_success(
    client,
    db_session,
    seed_user_groups,
    email_sender_stub,
):
    user = await create_user(db_session, email="reset@example.com")

    request_response = await client.post(
        "/accounts/password-reset/request/",
        json={"email": user.email},
    )
    assert request_response.status_code == 200

    reset_token = await db_session.scalar(
        select(PasswordResetTokenModel).where(
            PasswordResetTokenModel.user_id == user.id
        )
    )
    assert reset_token is not None

    complete_response = await client.post(
        "/accounts/reset-password/complete/",
        json={
            "email": user.email,
            "token": reset_token.token,
            "password": NEW_PASSWORD,
        },
    )

    assert complete_response.status_code == 200
    assert email_sender_stub.password_reset_complete_emails[-1]["login_link"] == (
        "http://127.0.0.1:8000/accounts/login/"
    )
    await db_session.refresh(user)
    assert user.verify_password(NEW_PASSWORD)

    deleted_token = await db_session.scalar(
        select(PasswordResetTokenModel).where(
            PasswordResetTokenModel.user_id == user.id
        )
    )
    assert deleted_token is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_password_reset_email_link_contains_email_and_token(
    client,
    db_session,
    seed_user_groups,
    email_sender_stub,
):
    user = await create_user(db_session, email="reset-link@example.com")

    response = await client.post(
        "/accounts/password-reset/request/",
        json={"email": user.email},
    )

    assert response.status_code == 200
    assert email_sender_stub.password_reset_emails

    reset_link = email_sender_stub.password_reset_emails[-1]["reset_link"]
    parsed_link = urlparse(reset_link)
    query_params = parse_qs(parsed_link.query)

    assert parsed_link.path == "/accounts/reset-password/complete/"
    assert query_params["email"] == [user.email]
    assert query_params["token"][0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_password_reset_expired_token_is_rejected_and_deleted(
    client,
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, email="expired-reset@example.com")
    await client.post(
        "/accounts/password-reset/request/",
        json={"email": user.email},
    )

    reset_token = await db_session.scalar(
        select(PasswordResetTokenModel).where(
            PasswordResetTokenModel.user_id == user.id
        )
    )
    assert reset_token is not None
    reset_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()

    response = await client.post(
        "/accounts/reset-password/complete/",
        json={
            "email": user.email,
            "token": reset_token.token,
            "password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid email or token."

    deleted_token = await db_session.scalar(
        select(PasswordResetTokenModel).where(
            PasswordResetTokenModel.user_id == user.id
        )
    )
    assert deleted_token is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_change_password_success(
    client, db_session, jwt_manager, seed_user_groups
):
    user = await create_user(db_session, email="change@example.com")
    access_token = jwt_manager.create_access_token({"user_id": user.id})

    response = await client.post(
        "/accounts/change-password/",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    await db_session.refresh(user)
    assert user.verify_password(NEW_PASSWORD)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_change_password_requires_auth(client):
    response = await client.post(
        "/accounts/change-password/",
        json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_can_change_user_group(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    admin = await create_user(
        db_session,
        email="admin@example.com",
        group=UserGroupEnum.ADMIN,
    )
    user = await create_user(db_session, email="ordinary@example.com")
    access_token = jwt_manager.create_access_token({"user_id": admin.id})

    response = await client.post(
        f"/admin/users/{user.id}/group/",
        json={"group_name": "MODERATOR"},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    await db_session.refresh(user)
    assert (
        user.group_id == (await get_user_group(db_session, UserGroupEnum.MODERATOR)).id
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_admin_cannot_change_user_group(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    current_user = await create_user(db_session, email="not-admin@example.com")
    target_user = await create_user(db_session, email="target@example.com")
    access_token = jwt_manager.create_access_token({"user_id": current_user.id})

    response = await client.post(
        f"/admin/users/{target_user.id}/group/",
        json={"group_name": "MODERATOR"},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "You do not have permission to perform this action."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_group_change_rejects_invalid_group(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    admin = await create_user(
        db_session,
        email="invalid-group-admin@example.com",
        group=UserGroupEnum.ADMIN,
    )
    user = await create_user(db_session, email="invalid-group-user@example.com")
    access_token = jwt_manager.create_access_token({"user_id": admin.id})

    response = await client.post(
        f"/admin/users/{user.id}/group/",
        json={"group_name": "manager"},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_can_manually_activate_user(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    admin = await create_user(
        db_session,
        email="activation-admin@example.com",
        group=UserGroupEnum.ADMIN,
    )
    user = await create_user(
        db_session,
        email="manual-activation@example.com",
        is_active=False,
    )
    access_token = jwt_manager.create_access_token({"user_id": admin.id})

    response = await client.post(
        f"/admin/users/{user.id}/activate/",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    await db_session.refresh(user)
    assert user.is_active is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_expired_tokens_task_removes_only_expired_tokens(
    db_session,
    seed_user_groups,
):
    expired_activation_user = await create_user(
        db_session,
        email="expired-activation-token@example.com",
    )
    active_activation_user = await create_user(
        db_session,
        email="active-activation-token@example.com",
    )
    expired_reset_user = await create_user(
        db_session,
        email="expired-reset-token@example.com",
    )
    active_reset_user = await create_user(
        db_session,
        email="active-reset-token@example.com",
    )

    expired_activation = ActivationTokenModel(
        user_id=expired_activation_user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    active_activation = ActivationTokenModel(
        user_id=active_activation_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    expired_reset = PasswordResetTokenModel(
        user_id=expired_reset_user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    active_reset = PasswordResetTokenModel(
        user_id=active_reset_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add_all(
        [expired_activation, active_activation, expired_reset, active_reset]
    )
    await db_session.commit()

    expired_activation_id = expired_activation.id
    active_activation_id = active_activation.id
    expired_reset_id = expired_reset.id
    active_reset_id = active_reset.id

    await _delete_expired_tokens()

    db_session.expire_all()

    assert await db_session.get(ActivationTokenModel, expired_activation_id) is None
    assert await db_session.get(PasswordResetTokenModel, expired_reset_id) is None
    assert await db_session.get(ActivationTokenModel, active_activation_id) is not None
    assert await db_session.get(PasswordResetTokenModel, active_reset_id) is not None
