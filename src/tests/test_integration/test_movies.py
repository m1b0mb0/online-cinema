from decimal import Decimal

import pytest

from src.database import CertificationModel, GenreModel, MovieModel


pytestmark = pytest.mark.integration


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

    matching_movie = MovieModel(
        name="Matching Movie",
        year=2015,
        time=120,
        imdb=8.5,
        votes=1000,
        description="A matching description.",
        price=Decimal("14.99"),
        certification=certification,
        genres=[drama],
    )
    other_movie = MovieModel(
        name="Other Movie",
        year=1995,
        time=95,
        imdb=6.5,
        votes=500,
        description="Another description.",
        price=Decimal("9.99"),
        certification=certification,
        genres=[action],
    )
    db_session.add_all([matching_movie, other_movie])
    await db_session.commit()

    response = await client.get(
        "/theater/movies/",
        params={
            "year_from": 2000,
            "imdb_min": 8,
            "price_max": "20.00",
            "genre_ids": drama.id,
        },
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["total_items"] == 1
    assert [movie["name"] for movie in response_data["movies"]] == [
        "Matching Movie"
    ]
