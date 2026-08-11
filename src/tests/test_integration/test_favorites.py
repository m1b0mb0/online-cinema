from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.database import (
    CertificationModel,
    FavoriteModel,
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
    year: int,
    time: int,
    imdb: float,
    votes: int,
    price: str,
    genres: list[GenreModel] | None = None,
) -> MovieModel:
    return MovieModel(
        name=name,
        year=year,
        time=time,
        imdb=imdb,
        votes=votes,
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
    user = await db_session.scalar(select(UserModel).where(UserModel.email == email))
    assert user is not None
    return user, headers


@pytest.mark.asyncio
async def test_user_can_add_list_and_remove_favorite(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "favorite-user@example.com",
    )
    certification = CertificationModel(name="PG-13")
    movie = build_movie(
        "Favorite Movie",
        certification,
        year=2024,
        time=120,
        imdb=8.4,
        votes=2500,
        price="14.99",
    )
    db_session.add(movie)
    await db_session.commit()

    create_response = await client.post(
        f"/theater/favorites/{movie.uuid}/",
        headers=headers,
    )

    assert create_response.status_code == 201
    assert create_response.json()["movie"]["uuid"] == str(movie.uuid)
    assert create_response.json()["added_at"]
    assert await db_session.get(FavoriteModel, (user.id, movie.id)) is not None

    duplicate_response = await client.post(
        f"/theater/favorites/{movie.uuid}/",
        headers=headers,
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "Movie is already in favorites."

    list_response = await client.get(
        "/theater/favorites/",
        headers=headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["total_items"] == 1
    assert [item["uuid"] for item in list_response.json()["movies"]] == [
        str(movie.uuid)
    ]

    delete_response = await client.delete(
        f"/theater/favorites/{movie.uuid}/",
        headers=headers,
    )
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert await db_session.get(FavoriteModel, (user.id, movie.id)) is None

    repeated_delete_response = await client.delete(
        f"/theater/favorites/{movie.uuid}/",
        headers=headers,
    )
    assert repeated_delete_response.status_code == 404


@pytest.mark.asyncio
async def test_favorites_support_catalog_filters_sorting_and_pagination(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "filtered-favorites@example.com",
    )
    other_user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        "other-favorites@example.com",
    )
    certification = CertificationModel(name="PG")
    drama = GenreModel(name="Drama")
    action = GenreModel(name="Action")
    alpha = build_movie(
        "Alpha Favorite",
        certification,
        year=2022,
        time=101,
        imdb=9.0,
        votes=100,
        price="12.00",
        genres=[drama],
    )
    bravo = build_movie(
        "Bravo Favorite",
        certification,
        year=2020,
        time=102,
        imdb=8.0,
        votes=300,
        price="15.00",
        genres=[drama],
    )
    filtered_out = build_movie(
        "Charlie Favorite",
        certification,
        year=2018,
        time=103,
        imdb=7.0,
        votes=200,
        price="8.00",
        genres=[action],
    )
    other_users_movie = build_movie(
        "Excluded Favorite",
        certification,
        year=2023,
        time=104,
        imdb=9.5,
        votes=1000,
        price="20.00",
        genres=[drama],
    )
    db_session.add_all([alpha, bravo, filtered_out, other_users_movie])
    await db_session.flush()
    db_session.add_all(
        [
            FavoriteModel(user_id=user.id, movie_id=alpha.id),
            FavoriteModel(user_id=user.id, movie_id=bravo.id),
            FavoriteModel(user_id=user.id, movie_id=filtered_out.id),
            FavoriteModel(
                user_id=other_user.id,
                movie_id=other_users_movie.id,
            ),
        ]
    )
    await db_session.commit()

    query_params = {
        "search": "Favorite",
        "year_from": 2020,
        "imdb_min": 8,
        "price_min": "10.00",
        "genre_ids": drama.id,
        "certification_ids": certification.id,
        "sort_by": "name",
        "sort_order": "asc",
        "page": 1,
        "per_page": 1,
    }
    first_response = await client.get(
        "/theater/favorites/",
        params=query_params,
        headers=headers,
    )

    assert first_response.status_code == 200
    first_page = first_response.json()
    assert first_page["total_items"] == 2
    assert first_page["total_pages"] == 2
    assert [movie["name"] for movie in first_page["movies"]] == ["Alpha Favorite"]
    assert first_page["prev_page"] is None
    assert first_page["next_page"] is not None

    next_page_params = parse_qs(urlparse(first_page["next_page"]).query)
    assert next_page_params == {
        key: [str(value)] for key, value in query_params.items()
    } | {"page": ["2"]}

    second_response = await client.get(
        first_page["next_page"],
        headers=headers,
    )
    assert second_response.status_code == 200
    assert [movie["name"] for movie in second_response.json()["movies"]] == [
        "Bravo Favorite"
    ]


@pytest.mark.asyncio
async def test_favorites_require_authentication_and_are_user_specific(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    owner, owner_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "favorite-owner@example.com",
    )
    _, other_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "favorite-outsider@example.com",
    )
    certification = CertificationModel(name="R")
    movie = build_movie(
        "Private Favorite",
        certification,
        year=2021,
        time=110,
        imdb=7.8,
        votes=500,
        price="11.00",
    )
    db_session.add(movie)
    await db_session.flush()
    db_session.add(FavoriteModel(user_id=owner.id, movie_id=movie.id))
    await db_session.commit()

    anonymous_responses = [
        await client.get("/theater/favorites/"),
        await client.post(f"/theater/favorites/{movie.uuid}/"),
        await client.delete(f"/theater/favorites/{movie.uuid}/"),
    ]
    assert all(response.status_code == 401 for response in anonymous_responses)

    other_list_response = await client.get(
        "/theater/favorites/",
        headers=other_headers,
    )
    other_delete_response = await client.delete(
        f"/theater/favorites/{movie.uuid}/",
        headers=other_headers,
    )

    assert other_list_response.status_code == 200
    assert other_list_response.json()["movies"] == []
    assert other_delete_response.status_code == 404

    owner_list_response = await client.get(
        "/theater/favorites/",
        headers=owner_headers,
    )
    assert owner_list_response.json()["total_items"] == 1


@pytest.mark.asyncio
async def test_add_favorite_returns_404_for_unknown_movie(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "missing-favorite@example.com",
    )

    response = await client.post(
        f"/theater/favorites/{uuid4()}/",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == ("Movie with the given UUID was not found.")
