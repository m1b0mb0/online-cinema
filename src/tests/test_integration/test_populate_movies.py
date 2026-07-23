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

    assert len(movies) == 2
    assert movies[0].description == "A first movie."
    assert movies[1].certification.name == "Unrated"
    assert {genre.name for genre in movies[0].genres} == {"Drama", "Crime"}
    assert all(isinstance(movie.price, Decimal) for movie in movies)
    assert all(movie.price.as_tuple().exponent == -2 for movie in movies)
    assert all(Decimal("4.99") <= movie.price <= Decimal("49.99") for movie in movies)


@pytest.mark.asyncio
async def test_populate_movies_is_idempotent(db_session, tmp_path):
    csv_path = tmp_path / "movies.csv"
    write_movie_csv(csv_path)

    await populate_movies(db_session, csv_path=csv_path, price_seed=7)
    original_prices = (
        await db_session.execute(
            select(MovieModel.name, MovieModel.price).order_by(MovieModel.name)
        )
    ).all()

    await populate_movies(db_session, csv_path=csv_path, price_seed=99)

    movie_count = await db_session.scalar(select(func.count(MovieModel.id)))
    certification_count = await db_session.scalar(
        select(func.count(CertificationModel.id))
    )
    director_count = await db_session.scalar(select(func.count(DirectorModel.id)))
    genre_count = await db_session.scalar(select(func.count(GenreModel.id)))
    star_count = await db_session.scalar(select(func.count(StarModel.id)))
    current_prices = (
        await db_session.execute(
            select(MovieModel.name, MovieModel.price).order_by(MovieModel.name)
        )
    ).all()

    assert movie_count == 2
    assert certification_count == 2
    assert director_count == 1
    assert genre_count == 2
    assert star_count == 2
    assert current_prices == original_prices
