from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.database import (
    CartItemModel,
    CartModel,
    CertificationModel,
    MovieModel,
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
        _hashed_password="not-used-in-cart-model-tests",
        is_active=True,
        group_id=group.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def build_movie(
    name: str,
    certification: CertificationModel | None = None,
) -> MovieModel:
    return MovieModel(
        name=name,
        year=2024,
        time=120,
        imdb=8.0,
        votes=1000,
        description=f"{name} description.",
        price=Decimal("12.99"),
        certification=certification or CertificationModel(name="PG-13"),
    )


@pytest.mark.asyncio
async def test_cart_models_support_one_cart_with_unique_movie_items(
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, "cart-owner@example.com")
    certification = CertificationModel(name="PG-13")
    first_movie = build_movie("First Cart Movie", certification)
    second_movie = build_movie("Second Cart Movie", certification)
    cart = CartModel(user_id=user.id)
    cart.items = [
        CartItemModel(movie=first_movie),
        CartItemModel(movie=second_movie),
    ]
    db_session.add(cart)
    await db_session.commit()

    loaded_cart = await db_session.scalar(
        select(CartModel)
        .where(CartModel.id == cart.id)
        .options(
            selectinload(CartModel.user),
            selectinload(CartModel.items).selectinload(CartItemModel.movie),
        )
    )
    loaded_user = await db_session.scalar(
        select(UserModel)
        .where(UserModel.id == user.id)
        .options(selectinload(UserModel.cart))
    )

    assert loaded_cart is not None
    assert loaded_user is not None
    assert loaded_cart.user.id == user.id
    assert loaded_user.cart is not None
    assert loaded_user.cart.id == loaded_cart.id
    assert {item.movie.name for item in loaded_cart.items} == {
        "First Cart Movie",
        "Second Cart Movie",
    }
    assert all(item.added_at is not None for item in loaded_cart.items)


@pytest.mark.asyncio
async def test_user_cannot_have_multiple_carts(
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, "single-cart-owner@example.com")
    db_session.add(CartModel(user_id=user.id))
    await db_session.commit()

    db_session.add(CartModel(user_id=user.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_same_movie_cannot_be_added_to_cart_twice(
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, "unique-cart-item@example.com")
    movie = build_movie("Unique Cart Movie")
    cart = CartModel(user_id=user.id)
    cart.items = [
        CartItemModel(movie=movie),
        CartItemModel(movie=movie),
    ]
    db_session.add(cart)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_deleting_cart_removes_its_items(
    db_session,
    seed_user_groups,
):
    user = await create_user(db_session, "deleted-cart@example.com")
    cart = CartModel(user_id=user.id)
    cart.items = [CartItemModel(movie=build_movie("Deleted Cart Movie"))]
    db_session.add(cart)
    await db_session.commit()

    await db_session.delete(cart)
    await db_session.commit()

    cart_count = await db_session.scalar(select(func.count()).select_from(CartModel))
    item_count = await db_session.scalar(
        select(func.count()).select_from(CartItemModel)
    )
    assert cart_count == 0
    assert item_count == 0


@pytest.mark.asyncio
async def test_movie_in_cart_cannot_be_deleted(
    db_session,
    seed_user_groups,
):
    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    user = await create_user(db_session, "protected-cart-movie@example.com")
    movie = build_movie("Protected Cart Movie")
    cart = CartModel(user_id=user.id)
    cart.items = [CartItemModel(movie=movie)]
    db_session.add(cart)
    await db_session.commit()

    movie_id = movie.id
    db_session.expire_all()
    stored_movie = await db_session.get(MovieModel, movie_id)
    assert stored_movie is not None
    await db_session.delete(stored_movie)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()
    assert await db_session.get(MovieModel, movie_id) is not None
