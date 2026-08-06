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
    UserGroupEnum,
    UserModel,
)
from src.tests.helpers import create_auth_headers

pytestmark = pytest.mark.integration


def build_movie(
    name: str,
    certification: CertificationModel,
    price: str,
) -> MovieModel:
    return MovieModel(
        name=name,
        year=2024,
        time=120,
        imdb=8.0,
        votes=1000,
        description=f"{name} description.",
        price=Decimal(price),
        certification=certification,
    )


def build_order(
    user: UserModel,
    movie: MovieModel,
    status: OrderStatusEnum,
    created_at: datetime,
) -> OrderModel:
    return OrderModel(
        user=user,
        status=status,
        created_at=created_at,
        total_amount=movie.price,
        items=[OrderItemModel(movie=movie, price_at_order=movie.price)],
    )


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
    user = await db_session.scalar(
        select(UserModel).where(UserModel.email == email)
    )
    assert user is not None
    return user, headers


@pytest.mark.asyncio
async def test_admin_can_list_all_orders_with_users_and_pagination(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, admin_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.ADMIN,
        "order-list-admin@example.com",
    )
    first_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "first-order-owner@example.com",
    )
    second_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "second-order-owner@example.com",
    )
    certification = CertificationModel(name="PG-13")
    orders = [
        build_order(
            first_user,
            build_movie("Old Admin Order Movie", certification, "10.00"),
            OrderStatusEnum.PAID,
            datetime(2025, 1, 1, 10, tzinfo=timezone.utc),
        ),
        build_order(
            second_user,
            build_movie("Middle Admin Order Movie", certification, "11.00"),
            OrderStatusEnum.CANCELED,
            datetime(2025, 1, 2, 10, tzinfo=timezone.utc),
        ),
        build_order(
            first_user,
            build_movie("New Admin Order Movie", certification, "12.00"),
            OrderStatusEnum.PENDING,
            datetime(2025, 1, 3, 10, tzinfo=timezone.utc),
        ),
    ]
    db_session.add_all(orders)
    await db_session.commit()

    response = await client.get(
        "/admin/orders/",
        params={"page": 1, "per_page": 2},
        headers=admin_headers,
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["total_items"] == 3
    assert response_data["total_pages"] == 2
    assert response_data["prev_page"] is None
    assert response_data["next_page"] is not None
    assert [order["id"] for order in response_data["orders"]] == [
        orders[2].id,
        orders[1].id,
    ]
    assert response_data["orders"][0]["user"] == {
        "id": first_user.id,
        "email": first_user.email,
    }
    assert response_data["orders"][0]["items_count"] == 1
    assert response_data["orders"][0]["items"][0]["movie"]["name"] == (
        "New Admin Order Movie"
    )

    next_page_response = await client.get(
        response_data["next_page"],
        headers=admin_headers,
    )

    assert next_page_response.status_code == 200
    assert [order["id"] for order in next_page_response.json()["orders"]] == [
        orders[0].id
    ]


@pytest.mark.asyncio
async def test_admin_can_combine_user_status_and_date_filters(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, admin_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.ADMIN,
        "order-filter-admin@example.com",
    )
    first_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "filtered-order-owner@example.com",
    )
    second_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "other-filtered-order-owner@example.com",
    )
    certification = CertificationModel(name="R")
    matching_orders = [
        build_order(
            first_user,
            build_movie("Morning Filtered Movie", certification, "5.00"),
            OrderStatusEnum.PAID,
            datetime(2025, 2, 15, 0, tzinfo=timezone.utc),
        ),
        build_order(
            first_user,
            build_movie("Evening Filtered Movie", certification, "6.00"),
            OrderStatusEnum.PAID,
            datetime(2025, 2, 15, 23, 59, 59, tzinfo=timezone.utc),
        ),
    ]
    excluded_orders = [
        build_order(
            first_user,
            build_movie("Wrong Status Movie", certification, "7.00"),
            OrderStatusEnum.CANCELED,
            datetime(2025, 2, 15, 12, tzinfo=timezone.utc),
        ),
        build_order(
            first_user,
            build_movie("Wrong Date Movie", certification, "8.00"),
            OrderStatusEnum.PAID,
            datetime(2025, 2, 16, 0, tzinfo=timezone.utc),
        ),
        build_order(
            second_user,
            build_movie("Wrong User Movie", certification, "9.00"),
            OrderStatusEnum.PAID,
            datetime(2025, 2, 15, 12, tzinfo=timezone.utc),
        ),
    ]
    db_session.add_all([*matching_orders, *excluded_orders])
    await db_session.commit()

    response = await client.get(
        "/admin/orders/",
        params={
            "user_id": first_user.id,
            "status": "paid",
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
    assert response_data["total_pages"] == 2
    assert [order["id"] for order in response_data["orders"]] == [
        matching_orders[1].id
    ]
    next_page_query = parse_qs(urlparse(response_data["next_page"]).query)
    assert next_page_query == {
        "user_id": [str(first_user.id)],
        "status": ["paid"],
        "date_from": ["2025-02-15"],
        "date_to": ["2025-02-15"],
        "page": ["2"],
        "per_page": ["1"],
    }

    next_page_response = await client.get(
        response_data["next_page"],
        headers=admin_headers,
    )
    assert next_page_response.status_code == 200
    assert [order["id"] for order in next_page_response.json()["orders"]] == [
        matching_orders[0].id
    ]


@pytest.mark.asyncio
async def test_admin_order_filters_are_validated(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, admin_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.ADMIN,
        "order-validation-admin@example.com",
    )

    reversed_dates_response = await client.get(
        "/admin/orders/",
        params={"date_from": "2025-03-02", "date_to": "2025-03-01"},
        headers=admin_headers,
    )
    invalid_status_response = await client.get(
        "/admin/orders/",
        params={"status": "refunded"},
        headers=admin_headers,
    )
    maximum_date_response = await client.get(
        "/admin/orders/",
        params={"date_to": "9999-12-31"},
        headers=admin_headers,
    )

    assert reversed_dates_response.status_code == 422
    assert invalid_status_response.status_code == 422
    assert maximum_date_response.status_code == 200
    assert maximum_date_response.json()["orders"] == []


@pytest.mark.asyncio
async def test_admin_order_list_requires_admin_role(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, user_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "unauthorized-order-viewer@example.com",
    )

    anonymous_response = await client.get("/admin/orders/")
    user_response = await client.get(
        "/admin/orders/",
        headers=user_headers,
    )

    assert anonymous_response.status_code == 401
    assert user_response.status_code == 403
