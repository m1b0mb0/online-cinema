from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from main import app
from src.database import (
    CartItemModel,
    CartModel,
    CertificationModel,
    GenreModel,
    MovieModel,
    UserGroupEnum,
    UserModel,
    get_db,
)
from src.tests.helpers import create_auth_headers

pytestmark = pytest.mark.integration


def build_movie(
    name: str,
    certification: CertificationModel,
    *,
    price: str,
    genres: list[GenreModel] | None = None,
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
        genres=genres or [],
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
    user = await db_session.scalar(
        select(UserModel).where(UserModel.email == email)
    )
    assert user is not None
    return user, headers


@pytest.mark.asyncio
async def test_user_can_add_view_remove_and_clear_cart(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "cart-user@example.com",
    )
    certification = CertificationModel(name="PG-13")
    drama = GenreModel(name="Drama")
    first_movie = build_movie(
        "First Cart API Movie",
        certification,
        price="12.99",
        genres=[drama],
    )
    second_movie = build_movie(
        "Second Cart API Movie",
        certification,
        price="17.50",
    )
    db_session.add_all([first_movie, second_movie])
    await db_session.commit()

    empty_response = await client.get("/theater/cart/", headers=headers)

    assert empty_response.status_code == 200
    empty_cart = empty_response.json()
    assert empty_cart["items"] == []
    assert empty_cart["items_count"] == 0
    assert Decimal(empty_cart["total_amount"]) == Decimal("0.00")

    stored_cart = await db_session.scalar(
        select(CartModel).where(CartModel.user_id == user.id)
    )
    assert stored_cart is not None
    assert empty_cart["id"] == stored_cart.id

    first_add_response = await client.post(
        f"/theater/cart/items/{first_movie.uuid}/",
        headers=headers,
    )
    second_add_response = await client.post(
        f"/theater/cart/items/{second_movie.uuid}/",
        headers=headers,
    )

    assert first_add_response.status_code == 201
    assert first_add_response.json()["movie"] == {
        "uuid": str(first_movie.uuid),
        "name": first_movie.name,
        "year": first_movie.year,
        "price": "12.99",
        "genres": [{"id": drama.id, "name": drama.name}],
    }
    assert first_add_response.json()["added_at"]
    assert second_add_response.status_code == 201

    cart_response = await client.get("/theater/cart/", headers=headers)

    assert cart_response.status_code == 200
    cart_data = cart_response.json()
    assert cart_data["id"] == stored_cart.id
    assert cart_data["items_count"] == 2
    assert Decimal(cart_data["total_amount"]) == Decimal("30.49")
    assert {item["movie"]["uuid"] for item in cart_data["items"]} == {
        str(first_movie.uuid),
        str(second_movie.uuid),
    }

    remove_response = await client.delete(
        f"/theater/cart/items/{first_movie.uuid}/",
        headers=headers,
    )
    assert remove_response.status_code == 204
    assert remove_response.content == b""

    remaining_response = await client.get("/theater/cart/", headers=headers)
    assert remaining_response.json()["items_count"] == 1
    assert remaining_response.json()["items"][0]["movie"]["uuid"] == str(
        second_movie.uuid
    )

    clear_response = await client.delete("/theater/cart/", headers=headers)
    repeated_clear_response = await client.delete(
        "/theater/cart/",
        headers=headers,
    )
    assert clear_response.status_code == 204
    assert repeated_clear_response.status_code == 204

    cleared_response = await client.get("/theater/cart/", headers=headers)
    assert cleared_response.json()["id"] == stored_cart.id
    assert cleared_response.json()["items"] == []
    assert cleared_response.json()["items_count"] == 0
    assert await db_session.scalar(
        select(func.count()).select_from(CartModel)
    ) == 1
    assert await db_session.scalar(
        select(func.count()).select_from(CartItemModel)
    ) == 0


@pytest.mark.asyncio
async def test_cart_rejects_duplicates_and_handles_missing_movies(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "validated-cart-user@example.com",
    )
    movie = build_movie(
        "Validated Cart Movie",
        CertificationModel(name="R"),
        price="9.99",
    )
    db_session.add(movie)
    await db_session.commit()

    create_response = await client.post(
        f"/theater/cart/items/{movie.uuid}/",
        headers=headers,
    )
    duplicate_response = await client.post(
        f"/theater/cart/items/{movie.uuid}/",
        headers=headers,
    )
    unknown_uuid = uuid4()
    unknown_add_response = await client.post(
        f"/theater/cart/items/{unknown_uuid}/",
        headers=headers,
    )
    unknown_remove_response = await client.delete(
        f"/theater/cart/items/{unknown_uuid}/",
        headers=headers,
    )

    assert create_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "Movie is already in the cart."
    assert unknown_add_response.status_code == 404
    assert unknown_add_response.json()["detail"] == (
        "Movie with the given UUID was not found."
    )
    assert unknown_remove_response.status_code == 404
    assert unknown_remove_response.json()["detail"] == (
        "Movie is not in the user's cart."
    )

    remove_response = await client.delete(
        f"/theater/cart/items/{movie.uuid}/",
        headers=headers,
    )
    repeated_remove_response = await client.delete(
        f"/theater/cart/items/{movie.uuid}/",
        headers=headers,
    )
    assert remove_response.status_code == 204
    assert repeated_remove_response.status_code == 404


@pytest.mark.asyncio
async def test_add_movie_recovers_when_another_request_creates_cart_first(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
    monkeypatch,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "concurrent-cart-user@example.com",
    )
    movie = build_movie(
        "Concurrent Cart Movie",
        CertificationModel(name="TV-MA"),
        price="13.50",
    )
    existing_cart = CartModel(user_id=user.id)
    db_session.add_all([movie, existing_cart])
    await db_session.commit()

    original_scalar = db_session.scalar
    cart_lookup_was_hidden = False

    async def scalar_with_stale_first_cart_lookup(statement, *args, **kwargs):
        nonlocal cart_lookup_was_hidden
        entity = statement.column_descriptions[0].get("entity")
        if entity is CartModel and not cart_lookup_was_hidden:
            cart_lookup_was_hidden = True
            return None
        return await original_scalar(statement, *args, **kwargs)

    async def override_get_db():
        yield db_session

    monkeypatch.setattr(db_session, "scalar", scalar_with_stale_first_cart_lookup)
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = await client.post(
            f"/theater/cart/items/{movie.uuid}/",
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 201
    assert response.json()["movie"]["uuid"] == str(movie.uuid)
    assert await db_session.scalar(
        select(func.count())
        .select_from(CartModel)
        .where(CartModel.user_id == user.id)
    ) == 1
    cart_item = await db_session.scalar(
        select(CartItemModel).where(
            CartItemModel.cart_id == existing_cart.id,
            CartItemModel.movie_id == movie.id,
        )
    )
    assert cart_item is not None


@pytest.mark.asyncio
async def test_cart_requires_authentication_and_is_user_specific(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, owner_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "cart-owner-api@example.com",
    )
    _, other_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "cart-outsider-api@example.com",
    )
    movie = build_movie(
        "Private Cart Movie",
        CertificationModel(name="PG"),
        price="15.00",
    )
    db_session.add(movie)
    await db_session.commit()

    owner_add_response = await client.post(
        f"/theater/cart/items/{movie.uuid}/",
        headers=owner_headers,
    )
    assert owner_add_response.status_code == 201

    other_cart_response = await client.get(
        "/theater/cart/",
        headers=other_headers,
    )
    other_remove_response = await client.delete(
        f"/theater/cart/items/{movie.uuid}/",
        headers=other_headers,
    )
    other_clear_response = await client.delete(
        "/theater/cart/",
        headers=other_headers,
    )
    assert other_cart_response.status_code == 200
    assert other_cart_response.json()["items"] == []
    assert other_remove_response.status_code == 404
    assert other_clear_response.status_code == 204

    owner_cart_response = await client.get(
        "/theater/cart/",
        headers=owner_headers,
    )
    assert owner_cart_response.json()["items_count"] == 1

    anonymous_responses = [
        await client.get("/theater/cart/"),
        await client.post(f"/theater/cart/items/{movie.uuid}/"),
        await client.delete(f"/theater/cart/items/{movie.uuid}/"),
        await client.delete("/theater/cart/"),
    ]
    assert all(response.status_code == 401 for response in anonymous_responses)


@pytest.mark.asyncio
async def test_moderator_cannot_delete_movie_while_it_is_in_a_cart(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, user_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "protected-cart-owner@example.com",
    )
    moderator_headers = await create_auth_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.MODERATOR,
        "cart-moderator@example.com",
    )
    movie = build_movie(
        "Movie Protected By Cart",
        CertificationModel(name="NC-17"),
        price="20.00",
    )
    db_session.add(movie)
    await db_session.commit()
    movie_id = movie.id

    add_response = await client.post(
        f"/theater/cart/items/{movie.uuid}/",
        headers=user_headers,
    )
    delete_response = await client.delete(
        f"/theater/movies/{movie.uuid}/",
        headers=moderator_headers,
    )

    assert add_response.status_code == 201
    assert delete_response.status_code == 409
    assert delete_response.json()["detail"] == (
        "Movie cannot be deleted because it is currently in a user's cart."
    )
    db_session.expire_all()
    assert await db_session.get(MovieModel, movie_id) is not None

    await client.delete(
        f"/theater/cart/items/{movie.uuid}/",
        headers=user_headers,
    )
    successful_delete_response = await client.delete(
        f"/theater/movies/{movie.uuid}/",
        headers=moderator_headers,
    )
    assert successful_delete_response.status_code == 204
    db_session.expire_all()
    assert await db_session.get(MovieModel, movie_id) is None
