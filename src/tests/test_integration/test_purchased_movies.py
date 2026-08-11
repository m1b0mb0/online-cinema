from datetime import datetime, timedelta, timezone
from decimal import Decimal

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


def build_movie(name: str, certification: CertificationModel) -> MovieModel:
    return MovieModel(
        name=name,
        year=2024,
        time=120,
        imdb=8.0,
        votes=1000,
        description=f"{name} description.",
        price=Decimal("10.00"),
        certification=certification,
    )


def build_order(
    user_id: int,
    movie: MovieModel,
    status: OrderStatusEnum,
    created_at: datetime,
) -> OrderModel:
    return OrderModel(
        user_id=user_id,
        created_at=created_at,
        status=status,
        total_amount=movie.price,
        items=[OrderItemModel(movie=movie, price_at_order=movie.price)],
    )


async def create_user_with_headers(
    db_session,
    jwt_manager,
    email: str,
) -> tuple[UserModel, dict[str, str]]:
    headers = await create_auth_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        email,
    )
    user = await db_session.scalar(select(UserModel).where(UserModel.email == email))
    assert user is not None
    return user, headers


@pytest.mark.asyncio
async def test_purchased_movies_are_private_and_include_only_paid_orders(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    owner, owner_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "purchased-owner@example.com",
    )
    outsider, outsider_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "purchased-outsider@example.com",
    )
    certification = CertificationModel(name="PG-13")
    paid_movie = build_movie("Paid Movie", certification)
    pending_movie = build_movie("Pending Movie", certification)
    canceled_movie = build_movie("Canceled Movie", certification)
    outsider_movie = build_movie("Outsider Movie", certification)
    now = datetime.now(timezone.utc)

    db_session.add_all(
        [
            build_order(owner.id, paid_movie, OrderStatusEnum.PAID, now),
            build_order(owner.id, pending_movie, OrderStatusEnum.PENDING, now),
            build_order(owner.id, canceled_movie, OrderStatusEnum.CANCELED, now),
            build_order(outsider.id, outsider_movie, OrderStatusEnum.PAID, now),
        ]
    )
    await db_session.commit()

    anonymous_response = await client.get("/theater/movies/purchased/")
    owner_response = await client.get(
        "/theater/movies/purchased/",
        headers=owner_headers,
    )
    outsider_response = await client.get(
        "/theater/movies/purchased/",
        headers=outsider_headers,
    )

    assert anonymous_response.status_code == 401
    assert owner_response.status_code == 200
    assert owner_response.json()["total_items"] == 1
    assert [movie["name"] for movie in owner_response.json()["movies"]] == [
        "Paid Movie"
    ]
    assert outsider_response.status_code == 200
    assert [movie["name"] for movie in outsider_response.json()["movies"]] == [
        "Outsider Movie"
    ]


@pytest.mark.asyncio
async def test_purchased_movies_are_unique_and_paginated_by_latest_purchase(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "purchased-pagination@example.com",
    )
    certification = CertificationModel(name="R")
    first_movie = build_movie("First Purchased Movie", certification)
    latest_movie = build_movie("Latest Purchased Movie", certification)
    now = datetime.now(timezone.utc)

    db_session.add_all(
        [
            build_order(
                user.id,
                first_movie,
                OrderStatusEnum.PAID,
                now - timedelta(days=2),
            ),
            build_order(
                user.id,
                first_movie,
                OrderStatusEnum.PAID,
                now - timedelta(days=1),
            ),
            build_order(user.id, latest_movie, OrderStatusEnum.PAID, now),
        ]
    )
    await db_session.commit()

    first_page_response = await client.get(
        "/theater/movies/purchased/",
        params={"page": 1, "per_page": 1},
        headers=headers,
    )

    assert first_page_response.status_code == 200
    first_page = first_page_response.json()
    assert first_page["total_items"] == 2
    assert first_page["total_pages"] == 2
    assert [movie["name"] for movie in first_page["movies"]] == [
        "Latest Purchased Movie"
    ]
    assert first_page["prev_page"] is None
    assert first_page["next_page"] is not None

    second_page_response = await client.get(
        first_page["next_page"],
        headers=headers,
    )

    assert second_page_response.status_code == 200
    second_page = second_page_response.json()
    assert [movie["name"] for movie in second_page["movies"]] == [
        "First Purchased Movie"
    ]
    assert second_page["prev_page"] is not None
    assert second_page["next_page"] is None
