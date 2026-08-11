from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.database import (
    CartItemModel,
    CartModel,
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


def build_order(
    user_id: int,
    movie: MovieModel,
    status: OrderStatusEnum,
) -> OrderModel:
    return OrderModel(
        user_id=user_id,
        status=status,
        total_amount=movie.price,
        items=[
            OrderItemModel(
                movie=movie,
                price_at_order=movie.price,
            )
        ],
    )


@pytest.mark.asyncio
async def test_create_order_excludes_purchased_and_pending_movies(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "order-api-owner@example.com",
    )
    certification = CertificationModel(name="PG-13")
    eligible_movie = build_movie("Eligible Order Movie", certification, "10.00")
    purchased_movie = build_movie("Purchased Order Movie", certification, "11.00")
    pending_movie = build_movie("Pending Order Movie", certification, "12.00")
    canceled_movie = build_movie("Canceled Order Movie", certification, "13.00")
    db_session.add_all([eligible_movie, purchased_movie, pending_movie, canceled_movie])
    await db_session.flush()

    paid_order = build_order(user.id, purchased_movie, OrderStatusEnum.PAID)
    pending_order = build_order(user.id, pending_movie, OrderStatusEnum.PENDING)
    canceled_order = build_order(user.id, canceled_movie, OrderStatusEnum.CANCELED)
    cart = CartModel(
        user_id=user.id,
        items=[
            CartItemModel(movie=eligible_movie),
            CartItemModel(movie=purchased_movie),
            CartItemModel(movie=pending_movie),
            CartItemModel(movie=canceled_movie),
        ],
    )
    db_session.add_all([paid_order, pending_order, canceled_order, cart])
    await db_session.commit()

    response = await client.post("/theater/orders/", headers=headers)

    assert response.status_code == 201
    response_data = response.json()
    assert response_data["status"] == "pending"
    assert response_data["items_count"] == 2
    assert Decimal(response_data["total_amount"]) == Decimal("23.00")
    assert {item["movie"]["uuid"] for item in response_data["items"]} == {
        str(eligible_movie.uuid),
        str(canceled_movie.uuid),
    }
    assert {
        item["movie"]["uuid"]: item["reason"]
        for item in response_data["excluded_movies"]
    } == {
        str(purchased_movie.uuid): "already_purchased",
        str(pending_movie.uuid): "already_pending",
    }

    cart_item_count = await db_session.scalar(
        select(func.count(CartItemModel.id))
        .join(CartModel)
        .where(CartModel.user_id == user.id)
    )
    assert cart_item_count == 0

    created_order = await db_session.scalar(
        select(OrderModel)
        .where(OrderModel.id == response_data["id"])
        .options(selectinload(OrderModel.items))
    )
    assert created_order is not None
    assert {item.movie_id: item.price_at_order for item in created_order.items} == {
        eligible_movie.id: Decimal("10.00"),
        canceled_movie.id: Decimal("13.00"),
    }


@pytest.mark.asyncio
async def test_order_creation_rejects_empty_or_fully_excluded_cart(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    empty_user, empty_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "empty-order-cart@example.com",
    )
    excluded_user, excluded_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "excluded-order-cart@example.com",
    )
    movie = build_movie(
        "Fully Excluded Order Movie",
        CertificationModel(name="R"),
        "9.99",
    )
    paid_order = build_order(excluded_user.id, movie, OrderStatusEnum.PAID)
    cart = CartModel(
        user_id=excluded_user.id,
        items=[CartItemModel(movie=movie)],
    )
    db_session.add_all([paid_order, cart])
    await db_session.commit()

    empty_response = await client.post(
        "/theater/orders/",
        headers=empty_headers,
    )
    excluded_response = await client.post(
        "/theater/orders/",
        headers=excluded_headers,
    )

    assert empty_user.id != excluded_user.id
    assert empty_response.status_code == 400
    assert empty_response.json()["detail"] == "Shopping cart is empty."
    assert excluded_response.status_code == 409
    assert excluded_response.json()["detail"] == (
        "The cart contains no movies eligible for ordering."
    )

    remaining_item_count = await db_session.scalar(
        select(func.count(CartItemModel.id)).where(CartItemModel.cart_id == cart.id)
    )
    assert remaining_item_count == 1


@pytest.mark.asyncio
async def test_order_history_and_details_are_private_and_paginated(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    owner, owner_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "order-history-owner@example.com",
    )
    other_user, other_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "order-history-outsider@example.com",
    )
    certification = CertificationModel(name="PG")
    first_movie = build_movie("First History Movie", certification, "5.00")
    second_movie = build_movie("Second History Movie", certification, "6.00")
    third_movie = build_movie("Third History Movie", certification, "7.00")
    other_movie = build_movie("Other User History Movie", certification, "8.00")
    owner_orders = [
        build_order(owner.id, first_movie, OrderStatusEnum.PAID),
        build_order(owner.id, second_movie, OrderStatusEnum.CANCELED),
        build_order(owner.id, third_movie, OrderStatusEnum.PENDING),
    ]
    other_order = build_order(
        other_user.id,
        other_movie,
        OrderStatusEnum.PENDING,
    )
    db_session.add_all([*owner_orders, other_order])
    await db_session.commit()

    first_page_response = await client.get(
        "/theater/orders/",
        params={"page": 1, "per_page": 2},
        headers=owner_headers,
    )

    assert first_page_response.status_code == 200
    first_page = first_page_response.json()
    assert first_page["total_items"] == 3
    assert first_page["total_pages"] == 2
    assert first_page["prev_page"] is None
    assert first_page["next_page"] is not None
    assert [order["id"] for order in first_page["orders"]] == [
        owner_orders[2].id,
        owner_orders[1].id,
    ]

    second_page_response = await client.get(
        first_page["next_page"],
        headers=owner_headers,
    )
    assert second_page_response.status_code == 200
    assert [order["id"] for order in second_page_response.json()["orders"]] == [
        owner_orders[0].id
    ]

    detail_response = await client.get(
        f"/theater/orders/{owner_orders[0].id}/",
        headers=owner_headers,
    )
    private_detail_response = await client.get(
        f"/theater/orders/{owner_orders[0].id}/",
        headers=other_headers,
    )
    other_list_response = await client.get(
        "/theater/orders/",
        headers=other_headers,
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == owner_orders[0].id
    assert private_detail_response.status_code == 404
    assert other_list_response.json()["total_items"] == 1
    assert other_list_response.json()["orders"][0]["id"] == other_order.id


@pytest.mark.asyncio
async def test_only_owned_pending_order_can_be_canceled(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    owner, owner_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "cancel-order-owner@example.com",
    )
    _, other_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "cancel-order-outsider@example.com",
    )
    certification = CertificationModel(name="NC-17")
    pending_order = build_order(
        owner.id,
        build_movie("Cancelable Order Movie", certification, "10.00"),
        OrderStatusEnum.PENDING,
    )
    paid_order = build_order(
        owner.id,
        build_movie("Paid Order Movie", certification, "11.00"),
        OrderStatusEnum.PAID,
    )
    db_session.add_all([pending_order, paid_order])
    await db_session.commit()
    pending_order_id = pending_order.id
    paid_order_id = paid_order.id

    private_response = await client.post(
        f"/theater/orders/{pending_order_id}/cancel/",
        headers=other_headers,
    )
    paid_response = await client.post(
        f"/theater/orders/{paid_order_id}/cancel/",
        headers=owner_headers,
    )
    cancel_response = await client.post(
        f"/theater/orders/{pending_order_id}/cancel/",
        headers=owner_headers,
    )
    repeated_response = await client.post(
        f"/theater/orders/{pending_order_id}/cancel/",
        headers=owner_headers,
    )

    assert private_response.status_code == 404
    assert paid_response.status_code == 409
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "canceled"
    assert cancel_response.json()["items_count"] == 1
    assert repeated_response.status_code == 409

    db_session.expire_all()
    stored_order = await db_session.get(OrderModel, pending_order_id)
    assert stored_order is not None
    assert stored_order.status == OrderStatusEnum.CANCELED


@pytest.mark.asyncio
async def test_order_endpoints_require_authentication(client):
    responses = [
        await client.post("/theater/orders/"),
        await client.get("/theater/orders/"),
        await client.get("/theater/orders/1/"),
        await client.post("/theater/orders/1/cancel/"),
    ]

    assert all(response.status_code == 401 for response in responses)
