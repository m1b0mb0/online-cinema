from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.database import (
    CertificationModel,
    MovieModel,
    OrderItemModel,
    OrderModel,
    OrderStatusEnum,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)

pytestmark = pytest.mark.integration


async def create_user(db_session, email: str) -> UserModel:
    group = await db_session.scalar(
        select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    )
    assert group is not None

    user = UserModel(
        email=email,
        _hashed_password="not-used-in-order-model-tests",
        is_active=True,
        group_id=group.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def build_movie(name: str, price: str = "12.99") -> MovieModel:
    return MovieModel(
        name=name,
        year=2024,
        time=120,
        imdb=8.0,
        votes=1000,
        description=f"{name} description.",
        price=Decimal(price),
        certification=CertificationModel(name=f"{name} Certification"),
    )


@pytest.mark.asyncio
async def test_order_preserves_item_price_and_relationships(
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, "order-owner@example.com")
    movie = build_movie("Order Snapshot Movie", "14.50")
    order = OrderModel(
        user_id=user.id,
        total_amount=Decimal("14.50"),
        items=[
            OrderItemModel(
                movie=movie,
                price_at_order=Decimal("14.50"),
            )
        ],
    )
    db_session.add(order)
    await db_session.commit()

    order_id = order.id
    user_id = user.id
    movie_id = movie.id
    movie.price = Decimal("20.00")
    await db_session.commit()
    db_session.expire_all()

    loaded_order = await db_session.scalar(
        select(OrderModel)
        .where(OrderModel.id == order_id)
        .options(
            selectinload(OrderModel.user),
            selectinload(OrderModel.items).selectinload(OrderItemModel.movie),
        )
    )
    loaded_user = await db_session.scalar(
        select(UserModel)
        .where(UserModel.id == user_id)
        .options(selectinload(UserModel.orders))
    )

    assert loaded_order is not None
    assert loaded_user is not None
    assert loaded_order.status == OrderStatusEnum.PENDING
    assert loaded_order.created_at is not None
    assert loaded_order.total_amount == Decimal("14.50")
    assert loaded_order.user.id == user_id
    assert loaded_order.items[0].price_at_order == Decimal("14.50")
    assert loaded_order.items[0].movie.id == movie_id
    assert loaded_order.items[0].movie.price == Decimal("20.00")
    assert [stored_order.id for stored_order in loaded_user.orders] == [order_id]


@pytest.mark.asyncio
async def test_same_movie_cannot_appear_twice_in_one_order(
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, "unique-order-item@example.com")
    movie = build_movie("Unique Order Movie")
    order = OrderModel(
        user_id=user.id,
        total_amount=Decimal("25.98"),
        items=[
            OrderItemModel(movie=movie, price_at_order=movie.price),
            OrderItemModel(movie=movie, price_at_order=movie.price),
        ],
    )
    db_session.add(order)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.parametrize("negative_field", ["total_amount", "price_at_order"])
@pytest.mark.asyncio
async def test_order_amounts_cannot_be_negative(
    negative_field,
    db_session,
    seed_user_groups,
):
    user = await create_user(
        db_session,
        f"negative-{negative_field}@example.com",
    )
    movie = build_movie(f"Negative {negative_field} Movie")
    total_amount = Decimal("12.99")
    price_at_order = Decimal("12.99")
    if negative_field == "total_amount":
        total_amount = Decimal("-1.00")
    else:
        price_at_order = Decimal("-1.00")

    order = OrderModel(
        user_id=user.id,
        total_amount=total_amount,
        items=[
            OrderItemModel(
                movie=movie,
                price_at_order=price_at_order,
            )
        ],
    )
    db_session.add(order)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_order_history_protects_user_and_movie_but_items_follow_order(
    db_session,
    seed_user_groups,
):
    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    user = await create_user(db_session, "protected-order-owner@example.com")
    movie = build_movie("Protected Order Movie")
    order = OrderModel(
        user_id=user.id,
        total_amount=movie.price,
        items=[OrderItemModel(movie=movie, price_at_order=movie.price)],
    )
    db_session.add(order)
    await db_session.commit()

    user_id = user.id
    movie_id = movie.id
    order_id = order.id
    db_session.expire_all()

    stored_movie = await db_session.get(MovieModel, movie_id)
    assert stored_movie is not None
    await db_session.delete(stored_movie)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    stored_user = await db_session.get(UserModel, user_id)
    assert stored_user is not None
    await db_session.delete(stored_user)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    stored_order = await db_session.get(OrderModel, order_id)
    assert stored_order is not None
    await db_session.delete(stored_order)
    await db_session.commit()

    item_count = await db_session.scalar(
        select(func.count()).select_from(OrderItemModel)
    )
    assert item_count == 0
    assert await db_session.get(MovieModel, movie_id) is not None
    assert await db_session.get(UserModel, user_id) is not None
