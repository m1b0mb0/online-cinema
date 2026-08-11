from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from src.database import (
    CertificationModel,
    MovieModel,
    OrderItemModel,
    OrderModel,
    OrderStatusEnum,
    PaymentItemModel,
    PaymentModel,
    PaymentStatusEnum,
    UserGroupEnum,
    UserModel,
)
from src.tests.helpers import create_auth_headers

pytestmark = pytest.mark.integration


async def create_user_with_headers(
    db_session,
    jwt_manager,
    group: UserGroupEnum,
    email: str,
) -> tuple[UserModel, dict[str, str]]:
    headers = await create_auth_headers(
        db_session,
        jwt_manager,
        group,
        email,
    )
    user = await db_session.scalar(select(UserModel).where(UserModel.email == email))
    assert user is not None
    return user, headers


def build_payment(
    user: UserModel,
    name: str,
    status: PaymentStatusEnum,
    created_at: datetime,
    amount: str,
) -> PaymentModel:
    certification = CertificationModel(name=f"{name} Certification")
    movie = MovieModel(
        name=name,
        year=2025,
        time=120,
        imdb=8.0,
        votes=1000,
        description=f"{name} description.",
        price=Decimal(amount),
        certification=certification,
    )
    order_item = OrderItemModel(movie=movie, price_at_order=movie.price)
    order = OrderModel(
        user=user,
        status=(
            OrderStatusEnum.PAID
            if status in {PaymentStatusEnum.SUCCESSFUL, PaymentStatusEnum.REFUNDED}
            else OrderStatusEnum.PENDING
        ),
        total_amount=movie.price,
        items=[order_item],
    )
    return PaymentModel(
        user=user,
        order=order,
        created_at=created_at,
        status=status,
        amount=movie.price,
        external_payment_id=f"cs_test_{name.lower().replace(' ', '_')}",
        items=[
            PaymentItemModel(
                order_item=order_item,
                price_at_payment=movie.price,
            )
        ],
    )


@pytest.mark.asyncio
async def test_admin_can_list_all_payments_with_users_and_pagination(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, admin_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.ADMIN,
        "payment-list-admin@example.com",
    )
    first_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "first-payment-owner@example.com",
    )
    second_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "second-payment-owner@example.com",
    )
    payments = [
        build_payment(
            first_user,
            "Old Admin Payment Movie",
            PaymentStatusEnum.SUCCESSFUL,
            datetime(2025, 1, 1, 10, tzinfo=timezone.utc),
            "10.00",
        ),
        build_payment(
            second_user,
            "Middle Admin Payment Movie",
            PaymentStatusEnum.REFUNDED,
            datetime(2025, 1, 2, 10, tzinfo=timezone.utc),
            "11.00",
        ),
        build_payment(
            first_user,
            "New Admin Payment Movie",
            PaymentStatusEnum.PENDING,
            datetime(2025, 1, 3, 10, tzinfo=timezone.utc),
            "12.00",
        ),
    ]
    db_session.add_all(payments)
    await db_session.commit()

    response = await client.get(
        "/admin/payments/",
        params={"page": 1, "per_page": 2},
        headers=admin_headers,
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["total_items"] == 3
    assert response_data["total_pages"] == 2
    assert response_data["prev_page"] is None
    assert [payment["id"] for payment in response_data["payments"]] == [
        payments[2].id,
        payments[1].id,
    ]
    assert response_data["payments"][0]["user"] == {
        "id": first_user.id,
        "email": first_user.email,
    }
    assert response_data["payments"][0]["items_count"] == 1
    assert (
        response_data["payments"][0]["items"][0]["order_item"]["movie"]["name"]
        == "New Admin Payment Movie"
    )

    next_page_response = await client.get(
        response_data["next_page"],
        headers=admin_headers,
    )

    assert next_page_response.status_code == 200
    assert [payment["id"] for payment in next_page_response.json()["payments"]] == [
        payments[0].id
    ]


@pytest.mark.asyncio
async def test_admin_can_combine_payment_user_status_and_date_filters(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, admin_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.ADMIN,
        "payment-filter-admin@example.com",
    )
    first_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "filtered-payment-owner@example.com",
    )
    second_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "other-payment-owner@example.com",
    )
    matching_payments = [
        build_payment(
            first_user,
            "Morning Filtered Payment",
            PaymentStatusEnum.SUCCESSFUL,
            datetime(2025, 2, 15, 0, tzinfo=timezone.utc),
            "5.00",
        ),
        build_payment(
            first_user,
            "Evening Filtered Payment",
            PaymentStatusEnum.SUCCESSFUL,
            datetime(2025, 2, 15, 23, 59, 59, tzinfo=timezone.utc),
            "6.00",
        ),
    ]
    excluded_payments = [
        build_payment(
            first_user,
            "Wrong Payment Status",
            PaymentStatusEnum.REFUNDED,
            datetime(2025, 2, 15, 12, tzinfo=timezone.utc),
            "7.00",
        ),
        build_payment(
            first_user,
            "Wrong Payment Date",
            PaymentStatusEnum.SUCCESSFUL,
            datetime(2025, 2, 16, 0, tzinfo=timezone.utc),
            "8.00",
        ),
        build_payment(
            second_user,
            "Wrong Payment User",
            PaymentStatusEnum.SUCCESSFUL,
            datetime(2025, 2, 15, 12, tzinfo=timezone.utc),
            "9.00",
        ),
    ]
    db_session.add_all([*matching_payments, *excluded_payments])
    await db_session.commit()

    response = await client.get(
        "/admin/payments/",
        params={
            "user_id": first_user.id,
            "status": "successful",
            "date_from": "2025-02-15",
            "date_to": "2025-02-15",
            "page": 1,
            "per_page": 1,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["total_items"] == 2
    assert [payment["id"] for payment in response_data["payments"]] == [
        matching_payments[1].id
    ]
    assert parse_qs(urlparse(response_data["next_page"]).query) == {
        "user_id": [str(first_user.id)],
        "status": ["successful"],
        "date_from": ["2025-02-15"],
        "date_to": ["2025-02-15"],
        "page": ["2"],
        "per_page": ["1"],
    }


@pytest.mark.asyncio
async def test_admin_payment_filters_are_validated(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, admin_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.ADMIN,
        "payment-validation-admin@example.com",
    )

    reversed_dates_response = await client.get(
        "/admin/payments/",
        params={"date_from": "2025-03-02", "date_to": "2025-03-01"},
        headers=admin_headers,
    )
    invalid_status_response = await client.get(
        "/admin/payments/",
        params={"status": "paid"},
        headers=admin_headers,
    )
    maximum_date_response = await client.get(
        "/admin/payments/",
        params={"date_to": "9999-12-31"},
        headers=admin_headers,
    )

    assert reversed_dates_response.status_code == 422
    assert invalid_status_response.status_code == 422
    assert maximum_date_response.status_code == 200


@pytest.mark.asyncio
async def test_admin_payment_list_requires_admin_role(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, user_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "unauthorized-payment-viewer@example.com",
    )

    anonymous_response = await client.get("/admin/payments/")
    user_response = await client.get(
        "/admin/payments/",
        headers=user_headers,
    )

    assert anonymous_response.status_code == 401
    assert user_response.status_code == 403
