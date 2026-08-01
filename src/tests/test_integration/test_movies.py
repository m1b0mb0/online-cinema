from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from src.database import (
    CertificationModel,
    DirectorModel,
    GenreModel,
    MovieModel,
    StarModel,
    UserGroupEnum,
)
from src.tests.helpers import create_auth_headers

pytestmark = pytest.mark.integration


def build_movie(
    name: str,
    certification: CertificationModel,
    *,
    year: int = 2020,
    time: int = 120,
    imdb: float = 8.0,
    votes: int = 1000,
    price: str = "9.99",
    description: str | None = None,
    genres: list[GenreModel] | None = None,
    stars: list[StarModel] | None = None,
    directors: list[DirectorModel] | None = None,
) -> MovieModel:
    return MovieModel(
        name=name,
        year=year,
        time=time,
        imdb=imdb,
        votes=votes,
        description=description or f"{name} description.",
        price=Decimal(price),
        certification=certification,
        genres=genres or [],
        stars=stars or [],
        directors=directors or [],
    )


def movie_payload(name: str = "Created Movie") -> dict:
    return {
        "name": name,
        "year": 2024,
        "time": 130,
        "imdb": 8.4,
        "votes": 2500,
        "meta_score": 82,
        "gross": 1_500_000,
        "description": "A movie created through the catalog API.",
        "price": "14.99",
        "certification": "PG-13",
        "stars": ["Actor One", "Actor Two"],
        "genres": ["Drama", "Science Fiction"],
        "directors": ["Director One"],
    }


@pytest.mark.asyncio
async def test_get_movie_list_without_filters(client):
    response = await client.get("/theater/movies/")

    assert response.status_code == 200
    assert response.json() == {
        "movies": [],
        "prev_page": None,
        "next_page": None,
        "total_pages": 0,
        "total_items": 0,
    }


@pytest.mark.asyncio
async def test_get_movie_list_applies_combined_filters(client, db_session):
    certification = CertificationModel(name="PG-13")
    drama = GenreModel(name="Drama")
    action = GenreModel(name="Action")

    matching_movie = build_movie(
        "Matching Movie",
        certification,
        year=2015,
        imdb=8.5,
        price="14.99",
        genres=[drama],
    )
    other_movie = build_movie(
        "Other Movie",
        certification,
        year=1995,
        time=95,
        imdb=6.5,
        votes=500,
        price="9.99",
        genres=[action],
    )
    db_session.add_all([matching_movie, other_movie])
    await db_session.commit()

    response = await client.get(
        "/theater/movies/",
        params={
            "years": 2015,
            "year_from": 2000,
            "year_to": 2020,
            "imdb_min": 8,
            "imdb_max": 9,
            "price_min": "10.00",
            "price_max": "20.00",
            "genre_ids": drama.id,
            "certification_ids": certification.id,
        },
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["total_items"] == 1
    assert [movie["name"] for movie in response_data["movies"]] == [
        "Matching Movie"
    ]


@pytest.mark.asyncio
async def test_movie_search_includes_title_description_actor_and_director(
    client,
    db_session,
):
    certification = CertificationModel(name="R")
    actor = StarModel(name="Searchable Actor")
    director = DirectorModel(name="Searchable Director")
    movies = [
        build_movie("Title Match", certification),
        build_movie(
            "Description Movie",
            certification,
            description="Contains a unique synopsis phrase.",
        ),
        build_movie("Actor Movie", certification, stars=[actor]),
        build_movie("Director Movie", certification, directors=[director]),
    ]
    db_session.add_all(movies)
    await db_session.commit()

    search_cases = {
        "Title Match": "Title Match",
        "unique synopsis": "Description Movie",
        "Searchable Actor": "Actor Movie",
        "Searchable Director": "Director Movie",
    }

    for search, expected_name in search_cases.items():
        response = await client.get(
            "/theater/movies/",
            params={"search": search},
        )
        assert response.status_code == 200
        assert [movie["name"] for movie in response.json()["movies"]] == [
            expected_name
        ]


@pytest.mark.asyncio
async def test_movie_list_supports_sorting_and_preserves_pagination_params(
    client,
    db_session,
):
    certification = CertificationModel(name="PG")
    movies = [
        build_movie(
            "Bravo",
            certification,
            year=2020,
            imdb=7.0,
            votes=300,
            price="12.00",
        ),
        build_movie(
            "Alpha",
            certification,
            year=2022,
            imdb=9.0,
            votes=100,
            price="8.00",
        ),
        build_movie(
            "Charlie",
            certification,
            year=2018,
            imdb=8.0,
            votes=200,
            price="10.00",
        ),
    ]
    db_session.add_all(movies)
    await db_session.commit()

    sorting_cases = [
        ("name", "asc", ["Alpha", "Bravo", "Charlie"]),
        ("year", "desc", ["Alpha", "Bravo", "Charlie"]),
        ("price", "asc", ["Alpha", "Charlie", "Bravo"]),
        ("imdb", "desc", ["Alpha", "Charlie", "Bravo"]),
        ("popularity", "desc", ["Bravo", "Charlie", "Alpha"]),
        ("newest", "desc", ["Charlie", "Alpha", "Bravo"]),
    ]

    for sort_by, sort_order, expected_names in sorting_cases:
        response = await client.get(
            "/theater/movies/",
            params={
                "sort_by": sort_by,
                "sort_order": sort_order,
                "per_page": 20,
            },
        )
        assert response.status_code == 200
        assert [movie["name"] for movie in response.json()["movies"]] == expected_names

    first_page_response = await client.get(
        "/theater/movies/",
        params={
            "sort_by": "name",
            "sort_order": "asc",
            "page": 1,
            "per_page": 2,
        },
    )
    first_page = first_page_response.json()

    assert [movie["name"] for movie in first_page["movies"]] == ["Alpha", "Bravo"]
    assert parse_qs(urlparse(first_page["next_page"]).query) == {
        "sort_by": ["name"],
        "sort_order": ["asc"],
        "page": ["2"],
        "per_page": ["2"],
    }


@pytest.mark.asyncio
async def test_movie_filter_rejects_invalid_ranges(client):
    invalid_params = [
        {"year_from": 2024, "year_to": 2000},
        {"imdb_min": 9, "imdb_max": 5},
        {"price_min": "20.00", "price_max": "10.00"},
    ]

    for params in invalid_params:
        response = await client.get("/theater/movies/", params=params)
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_movie_details_and_uuid_validation(client, db_session):
    certification = CertificationModel(name="PG-13")
    genre = GenreModel(name="Drama")
    actor = StarModel(name="Example Actor")
    director = DirectorModel(name="Example Director")
    movie = build_movie(
        "Detailed Movie",
        certification,
        genres=[genre],
        stars=[actor],
        directors=[director],
    )
    db_session.add(movie)
    await db_session.commit()

    response = await client.get(f"/theater/movies/{movie.uuid}/")

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["name"] == "Detailed Movie"
    assert response_data["certification"]["name"] == "PG-13"
    assert [item["name"] for item in response_data["genres"]] == ["Drama"]
    assert [item["name"] for item in response_data["stars"]] == ["Example Actor"]
    assert [item["name"] for item in response_data["directors"]] == [
        "Example Director"
    ]

    not_found_response = await client.get(f"/theater/movies/{uuid4()}/")
    invalid_uuid_response = await client.get("/theater/movies/not-a-uuid/")

    assert not_found_response.status_code == 404
    assert invalid_uuid_response.status_code == 422


@pytest.mark.asyncio
async def test_moderator_can_create_update_and_delete_movie(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    headers = await create_auth_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.MODERATOR,
        "movie-moderator@example.com",
    )
    payload = movie_payload()

    create_response = await client.post(
        "/theater/movies/",
        json=payload,
        headers=headers,
    )

    assert create_response.status_code == 201
    created_movie = create_response.json()
    movie_uuid = created_movie["uuid"]
    assert created_movie["certification"]["name"] == "PG-13"
    assert {item["name"] for item in created_movie["genres"]} == {
        "Drama",
        "Science Fiction",
    }

    duplicate_response = await client.post(
        "/theater/movies/",
        json=payload,
        headers=headers,
    )
    assert duplicate_response.status_code == 409

    update_response = await client.patch(
        f"/theater/movies/{movie_uuid}/",
        json={
            "name": "Updated Movie",
            "price": "19.99",
            "certification": "R",
            "stars": ["Replacement Actor"],
            "genres": ["Thriller"],
            "directors": ["Replacement Director"],
        },
        headers=headers,
    )

    assert update_response.status_code == 200
    updated_movie = update_response.json()
    assert updated_movie["name"] == "Updated Movie"
    assert updated_movie["price"] == "19.99"
    assert updated_movie["certification"]["name"] == "R"
    assert [item["name"] for item in updated_movie["stars"]] == [
        "Replacement Actor"
    ]
    assert [item["name"] for item in updated_movie["genres"]] == ["Thriller"]
    assert [item["name"] for item in updated_movie["directors"]] == [
        "Replacement Director"
    ]

    delete_response = await client.delete(
        f"/theater/movies/{movie_uuid}/",
        headers=headers,
    )

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert (await client.get(f"/theater/movies/{movie_uuid}/")).status_code == 404


@pytest.mark.asyncio
async def test_movie_mutations_require_catalog_permissions(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    certification = CertificationModel(name="PG")
    movie = build_movie("Protected Movie", certification)
    db_session.add(movie)
    await db_session.commit()

    user_headers = await create_auth_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        "movie-user@example.com",
    )
    payload = movie_payload("Permission Test Movie")
    protected_requests = [
        ("post", "/theater/movies/", payload),
        ("patch", f"/theater/movies/{movie.uuid}/", {"name": "Forbidden Update"}),
        ("delete", f"/theater/movies/{movie.uuid}/", None),
    ]

    for method, url, body in protected_requests:
        anonymous_response = await client.request(method, url, json=body)
        user_response = await client.request(
            method,
            url,
            json=body,
            headers=user_headers,
        )

        assert anonymous_response.status_code == 401
        assert user_response.status_code == 403
