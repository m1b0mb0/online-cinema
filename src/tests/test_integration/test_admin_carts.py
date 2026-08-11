from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from src.database import (
    CartItemModel,
    CartModel,
    CertificationModel,
    GenreModel,
    MovieModel,
    UserGroupEnum,
    UserModel,
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


@pytest.mark.asyncio
async def test_admin_can_list_all_carts_with_totals_and_pagination(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, admin_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.ADMIN,
        "cart-list-admin@example.com",
    )
    first_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "first-listed-cart@example.com",
    )
    second_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "second-listed-cart@example.com",
    )
    third_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "empty-listed-cart@example.com",
    )

    certification = CertificationModel(name="PG-13")
    first_movie = build_movie(
        "First Admin Cart Movie",
        certification,
        price="10.25",
    )
    second_movie = build_movie(
        "Second Admin Cart Movie",
        certification,
        price="4.75",
    )
    third_movie = build_movie(
        "Third Admin Cart Movie",
        certification,
        price="8.00",
    )
    first_cart = CartModel(
        user_id=first_user.id,
        items=[
            CartItemModel(movie=first_movie),
            CartItemModel(movie=second_movie),
        ],
    )
    second_cart = CartModel(
        user_id=second_user.id,
        items=[CartItemModel(movie=third_movie)],
    )
    third_cart = CartModel(user_id=third_user.id, items=[])
    db_session.add_all([first_cart, second_cart, third_cart])
    await db_session.commit()

    first_page_response = await client.get(
        "/admin/carts/",
        params={"page": 1, "per_page": 2},
        headers=admin_headers,
    )

    assert first_page_response.status_code == 200
    first_page = first_page_response.json()
    assert "page" not in first_page
    assert "per_page" not in first_page
    assert first_page["total_items"] == 3
    assert first_page["total_pages"] == 2
    assert first_page["prev_page"] is None
    assert first_page["next_page"] is not None
    assert [cart["id"] for cart in first_page["carts"]] == [
        first_cart.id,
        second_cart.id,
    ]
    assert first_page["carts"][0]["user"]["email"] == first_user.email
    assert first_page["carts"][0]["items_count"] == 2
    assert Decimal(first_page["carts"][0]["total_amount"]) == Decimal("15.00")
    assert first_page["carts"][1]["items_count"] == 1
    assert Decimal(first_page["carts"][1]["total_amount"]) == Decimal("8.00")
    assert parse_qs(urlparse(first_page["next_page"]).query) == {
        "page": ["2"],
        "per_page": ["2"],
    }

    second_page_response = await client.get(
        first_page["next_page"],
        headers=admin_headers,
    )
    second_page = second_page_response.json()
    assert second_page_response.status_code == 200
    assert second_page["next_page"] is None
    assert second_page["prev_page"] is not None
    assert [cart["id"] for cart in second_page["carts"]] == [third_cart.id]
    assert second_page["carts"][0]["items_count"] == 0
    assert Decimal(second_page["carts"][0]["total_amount"]) == Decimal("0.00")

    empty_page_response = await client.get(
        "/admin/carts/",
        params={"page": 3, "per_page": 2},
        headers=admin_headers,
    )
    assert empty_page_response.status_code == 200
    assert empty_page_response.json()["carts"] == []


@pytest.mark.asyncio
async def test_admin_can_view_cart_details_without_creating_missing_cart(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, admin_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.ADMIN,
        "cart-detail-admin@example.com",
    )
    cart_owner, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "detailed-cart-owner@example.com",
    )
    user_without_cart, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "user-without-cart@example.com",
    )
    genre = GenreModel(name="Drama")
    movie = build_movie(
        "Detailed Admin Cart Movie",
        CertificationModel(name="R"),
        price="19.99",
        genres=[genre],
    )
    cart = CartModel(
        user_id=cart_owner.id,
        items=[CartItemModel(movie=movie)],
    )
    db_session.add(cart)
    await db_session.commit()

    detail_response = await client.get(
        f"/admin/users/{cart_owner.id}/cart/",
        headers=admin_headers,
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == cart.id
    assert detail["user"] == {
        "id": cart_owner.id,
        "email": cart_owner.email,
    }
    assert detail["items_count"] == 1
    assert Decimal(detail["total_amount"]) == Decimal("19.99")
    assert detail["items"][0]["movie"]["uuid"] == str(movie.uuid)
    assert detail["items"][0]["movie"]["genres"] == [{"id": genre.id, "name": "Drama"}]

    carts_before = await db_session.scalar(select(func.count()).select_from(CartModel))
    missing_response = await client.get(
        f"/admin/users/{user_without_cart.id}/cart/",
        headers=admin_headers,
    )
    carts_after = await db_session.scalar(select(func.count()).select_from(CartModel))

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == (
        "Shopping cart was not found for the requested user."
    )
    assert carts_after == carts_before


@pytest.mark.asyncio
async def test_admin_cart_endpoints_require_admin_role(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, user_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "unauthorized-cart-viewer@example.com",
    )

    anonymous_responses = [
        await client.get("/admin/carts/"),
        await client.get(f"/admin/users/{user.id}/cart/"),
    ]
    user_responses = [
        await client.get("/admin/carts/", headers=user_headers),
        await client.get(
            f"/admin/users/{user.id}/cart/",
            headers=user_headers,
        ),
    ]

    assert all(response.status_code == 401 for response in anonymous_responses)
    assert all(response.status_code == 403 for response in user_responses)
