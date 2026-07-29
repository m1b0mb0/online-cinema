import csv
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from src.database import (
    CertificationModel,
    DirectorModel,
    GenreModel,
    MovieModel,
    StarModel,
)
from src.database.populate import populate_movies

pytestmark = pytest.mark.integration

CSV_FIELD_NAMES = [
    "Movie Name",
    "Year of Release",
    "Run Time in minutes",
    "Movie Rating",
    "Votes",
    "MetaScore",
    "Gross",
    "Genre",
    "Certification",
    "Director",
    "Stars",
    "Description",
]


def write_movie_csv(csv_path) -> None:
    rows = [
        {
            "Movie Name": "First Movie",
            "Year of Release": "2001",
            "Run Time in minutes": "120",
            "Movie Rating": "8.1",
            "Votes": "1000",
            "MetaScore": "75.0",
            "Gross": "123456.0",
            "Genre": "['Drama', 'Crime']",
            "Certification": "R",
            "Director": "['Example Director']",
            "Stars": "['First Star', 'Shared Star']",
            "Description": "['A', 'first', 'movie.']",
        },
        {
            "Movie Name": "Second Movie",
            "Year of Release": "2002",
            "Run Time in minutes": "90",
            "Movie Rating": "7.5",
            "Votes": "500",
            "MetaScore": "",
            "Gross": "",
            "Genre": "['Drama']",
            "Certification": "",
            "Director": "['Example Director']",
            "Stars": "['Shared Star']",
            "Description": "['A', 'second', 'movie.']",
        },
    ]

    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELD_NAMES)
        writer.writeheader()
        writer.writerows(rows)


async def get_movie_catalog_snapshot(db_session) -> dict[str, dict]:
    movies = (
        await db_session.scalars(
            select(MovieModel)
            .options(
                joinedload(MovieModel.certification),
                selectinload(MovieModel.stars),
                selectinload(MovieModel.genres),
                selectinload(MovieModel.directors),
            )
            .order_by(MovieModel.name)
        )
    ).all()

    return {
        movie.name: {
            "year": movie.year,
            "time": movie.time,
            "imdb": movie.imdb,
            "votes": movie.votes,
            "meta_score": movie.meta_score,
            "gross": movie.gross,
            "description": movie.description,
            "price": movie.price,
            "certification": movie.certification.name,
            "genres": tuple(sorted(genre.name for genre in movie.genres)),
            "stars": tuple(sorted(star.name for star in movie.stars)),
            "directors": tuple(
                sorted(director.name for director in movie.directors)
            ),
        }
        for movie in movies
    }


async def get_catalog_counts(db_session) -> dict[str, int]:
    models = {
        "movies": MovieModel,
        "certifications": CertificationModel,
        "directors": DirectorModel,
        "genres": GenreModel,
        "stars": StarModel,
    }
    return {
        name: await db_session.scalar(select(func.count(model.id)))
        for name, model in models.items()
    }


@pytest.mark.asyncio
async def test_populate_movies_creates_catalog_with_decimal_prices(
    db_session, tmp_path
):
    csv_path = tmp_path / "movies.csv"
    write_movie_csv(csv_path)

    await populate_movies(
        db_session,
        csv_path=csv_path,
        batch_size=1,
        price_seed=7,
    )

    catalog = await get_movie_catalog_snapshot(db_session)

    assert catalog == {
        "First Movie": {
            "year": 2001,
            "time": 120,
            "imdb": 8.1,
            "votes": 1000,
            "meta_score": 75.0,
            "gross": 123456.0,
            "description": "A first movie.",
            "price": Decimal("31.51"),
            "certification": "R",
            "genres": ("Crime", "Drama"),
            "stars": ("First Star", "Shared Star"),
            "directors": ("Example Director",),
        },
        "Second Movie": {
            "year": 2002,
            "time": 90,
            "imdb": 7.5,
            "votes": 500,
            "meta_score": None,
            "gross": None,
            "description": "A second movie.",
            "price": Decimal("17.34"),
            "certification": "Unrated",
            "genres": ("Drama",),
            "stars": ("Shared Star",),
            "directors": ("Example Director",),
        },
    }
    assert all(
        isinstance(movie["price"], Decimal)
        and movie["price"].as_tuple().exponent == -2
        for movie in catalog.values()
    )


@pytest.mark.asyncio
async def test_populate_movies_is_idempotent(db_session, tmp_path):
    csv_path = tmp_path / "movies.csv"
    write_movie_csv(csv_path)

    await populate_movies(db_session, csv_path=csv_path, price_seed=7)
    original_catalog = await get_movie_catalog_snapshot(db_session)
    original_counts = await get_catalog_counts(db_session)

    await populate_movies(db_session, csv_path=csv_path, price_seed=99)
    db_session.expire_all()

    assert original_counts == {
        "movies": 2,
        "certifications": 2,
        "directors": 1,
        "genres": 2,
        "stars": 2,
    }
    assert await get_catalog_counts(db_session) == original_counts
    assert await get_movie_catalog_snapshot(db_session) == original_catalog
