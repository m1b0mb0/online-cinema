from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from src.database import (
    CertificationModel,
    GenreModel,
    MovieModel,
    StarModel,
    UserGroupEnum,
)
from src.tests.helpers import create_auth_headers

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_catalog_entity_lists_and_details_are_public(client, db_session):
    drama = GenreModel(name="Drama")
    action = GenreModel(name="Action")
    tom_hanks = StarModel(name="Tom Hanks")
    emma_stone = StarModel(name="Emma Stone")
    db_session.add_all(
        [
            drama,
            action,
            tom_hanks,
            emma_stone,
        ]
    )
    await db_session.commit()

    genres_response = await client.get(
        "/theater/genres/",
        params={"page": 1, "per_page": 1, "search": "a"},
    )

    assert genres_response.status_code == 200
    genres_data = genres_response.json()
    assert genres_data["genres"] == [
        {"id": action.id, "name": "Action", "movie_count": 0}
    ]
    assert genres_data["prev_page"] is None
    assert parse_qs(urlparse(genres_data["next_page"]).query) == {
        "page": ["2"],
        "per_page": ["1"],
        "search": ["a"],
    }
    assert {key: genres_data[key] for key in ("total_pages", "total_items")} == {
        "total_pages": 2,
        "total_items": 2,
    }
    assert "page" not in genres_data
    assert "per_page" not in genres_data

    second_page_response = await client.get(genres_data["next_page"])
    second_page_data = second_page_response.json()
    assert second_page_response.status_code == 200
    assert second_page_data["genres"] == [
        {"id": drama.id, "name": "Drama", "movie_count": 0}
    ]
    assert second_page_data["next_page"] is None
    assert parse_qs(urlparse(second_page_data["prev_page"]).query) == {
        "page": ["1"],
        "per_page": ["1"],
        "search": ["a"],
    }

    actors_response = await client.get(
        "/theater/actors/",
        params={"search": "hanks"},
    )

    assert actors_response.status_code == 200
    actors_data = actors_response.json()
    assert actors_data["total_items"] == 1
    assert actors_data["actors"][0]["name"] == "Tom Hanks"
    assert actors_data["prev_page"] is None
    assert actors_data["next_page"] is None

    actor_id = actors_data["actors"][0]["id"]
    detail_response = await client.get(f"/theater/actors/{actor_id}/")

    assert detail_response.status_code == 200
    assert detail_response.json() == {"id": actor_id, "name": "Tom Hanks"}


@pytest.mark.asyncio
async def test_genre_list_includes_movie_counts(client, db_session):
    certification = CertificationModel(name="PG-13")
    drama = GenreModel(name="Drama")
    action = GenreModel(name="Action")
    documentary = GenreModel(name="Documentary")
    first_movie = MovieModel(
        name="First Movie",
        year=2020,
        time=120,
        imdb=8.0,
        votes=1000,
        description="First movie description.",
        price=Decimal("9.99"),
        certification=certification,
        genres=[drama, action],
    )
    second_movie = MovieModel(
        name="Second Movie",
        year=2021,
        time=100,
        imdb=7.5,
        votes=500,
        description="Second movie description.",
        price=Decimal("7.99"),
        certification=certification,
        genres=[drama],
    )
    db_session.add_all(
        [
            first_movie,
            second_movie,
            documentary,
        ]
    )
    await db_session.commit()

    response = await client.get(
        "/theater/genres/",
        params={"per_page": 100},
    )

    assert response.status_code == 200
    counts_by_genre = {
        genre["name"]: genre["movie_count"] for genre in response.json()["genres"]
    }
    assert counts_by_genre == {
        "Action": 1,
        "Documentary": 0,
        "Drama": 2,
    }


@pytest.mark.parametrize(
    ("group_name", "email"),
    [
        (UserGroupEnum.MODERATOR, "moderator-catalog@example.com"),
        (UserGroupEnum.ADMIN, "admin-catalog@example.com"),
    ],
)
@pytest.mark.asyncio
async def test_moderator_and_admin_can_manage_genres_and_actors(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
    group_name,
    email,
):
    headers = await create_auth_headers(
        db_session,
        jwt_manager,
        group_name,
        email,
    )

    genre_response = await client.post(
        "/theater/genres/",
        json={"name": "science fiction"},
        headers=headers,
    )
    assert genre_response.status_code == 201
    assert genre_response.json()["name"] == "Science Fiction"
    genre_id = genre_response.json()["id"]

    duplicate_response = await client.post(
        "/theater/genres/",
        json={"name": "SCIENCE FICTION"},
        headers=headers,
    )
    assert duplicate_response.status_code == 409

    genre_update_response = await client.patch(
        f"/theater/genres/{genre_id}/",
        json={"name": "space opera"},
        headers=headers,
    )
    assert genre_update_response.status_code == 200
    assert genre_update_response.json()["name"] == "Space Opera"

    actor_response = await client.post(
        "/theater/actors/",
        json={"name": "Sigourney Weaver"},
        headers=headers,
    )
    assert actor_response.status_code == 201
    assert actor_response.json()["name"] == "Sigourney Weaver"
    actor_id = actor_response.json()["id"]

    actor_update_response = await client.patch(
        f"/theater/actors/{actor_id}/",
        json={"name": "Zoe Saldana"},
        headers=headers,
    )
    assert actor_update_response.status_code == 200
    assert actor_update_response.json()["name"] == "Zoe Saldana"

    actor_delete_response = await client.delete(
        f"/theater/actors/{actor_id}/",
        headers=headers,
    )
    genre_delete_response = await client.delete(
        f"/theater/genres/{genre_id}/",
        headers=headers,
    )

    assert actor_delete_response.status_code == 204
    assert actor_delete_response.content == b""
    assert genre_delete_response.status_code == 204
    assert genre_delete_response.content == b""

    assert (await client.get(f"/theater/actors/{actor_id}/")).status_code == 404
    assert (await client.get(f"/theater/genres/{genre_id}/")).status_code == 404


@pytest.mark.asyncio
async def test_regular_user_cannot_modify_genres_or_actors(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    headers = await create_auth_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "catalog-user@example.com",
    )
    genre = GenreModel(name="Drama")
    actor = StarModel(name="Example Actor")
    db_session.add_all([genre, actor])
    await db_session.commit()

    requests = [
        client.post("/theater/genres/", json={"name": "Comedy"}, headers=headers),
        client.patch(
            f"/theater/genres/{genre.id}/",
            json={"name": "Crime"},
            headers=headers,
        ),
        client.delete(f"/theater/genres/{genre.id}/", headers=headers),
        client.post(
            "/theater/actors/",
            json={"name": "Another Actor"},
            headers=headers,
        ),
        client.patch(
            f"/theater/actors/{actor.id}/",
            json={"name": "Updated Actor"},
            headers=headers,
        ),
        client.delete(f"/theater/actors/{actor.id}/", headers=headers),
    ]

    for request in requests:
        response = await request
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_anonymous_user_cannot_create_genre_or_actor(client):
    genre_response = await client.post(
        "/theater/genres/",
        json={"name": "Drama"},
    )
    actor_response = await client.post(
        "/theater/actors/",
        json={"name": "Example Actor"},
    )

    assert genre_response.status_code == 401
    assert actor_response.status_code == 401
