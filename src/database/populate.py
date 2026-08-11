import ast
import asyncio
import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from random import Random
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db_contextmanager
from src.database.models.accounts import UserGroupEnum, UserGroupModel
from src.database.models.movies import (
    CertificationModel,
    DirectorModel,
    GenreModel,
    MovieModel,
    StarModel,
)

MOVIES_CSV_PATH = Path(__file__).parent / "seed_data" / "imdb_movies.csv"
MOVIE_IMPORT_BATCH_SIZE = 500
MOVIE_PRICE_RANDOM_SEED = 2026
MIN_MOVIE_PRICE_CENTS = 499
MAX_MOVIE_PRICE_CENTS = 4999
DEFAULT_CERTIFICATION = "Unrated"

NamedModel = TypeVar(
    "NamedModel",
    CertificationModel,
    DirectorModel,
    GenreModel,
    StarModel,
)


@dataclass(frozen=True, slots=True)
class MovieSeedData:
    name: str
    year: int
    time: int
    imdb: float
    votes: int
    meta_score: float | None
    gross: float | None
    description: str
    price: Decimal
    certification: str
    stars: list[str]
    genres: list[str]
    directors: list[str]

    @property
    def unique_key(self) -> tuple[str, int, int]:
        return self.name, self.year, self.time


async def populate_user_groups(db_session: AsyncSession | None = None) -> None:
    """Create default user groups if they do not exist."""
    if db_session is None:
        async with get_db_contextmanager() as session:
            await _populate_user_groups(session)
        return

    await _populate_user_groups(db_session)


async def _populate_user_groups(session: AsyncSession) -> None:
    for group_name in UserGroupEnum:
        exists = await session.scalar(
            select(UserGroupModel).where(UserGroupModel.name == group_name)
        )
        if not exists:
            session.add(UserGroupModel(name=group_name))
    await session.commit()
    print("User groups populated successfully.")


def _get_required_value(
    row: dict[str, str | None], field_name: str, line_number: int
) -> str:
    value = row.get(field_name)
    if value is None or not value.strip():
        raise ValueError(
            f"Missing required value '{field_name}' on CSV line {line_number}."
        )
    return value.strip()


def _parse_list_field(
    row: dict[str, str | None], field_name: str, line_number: int
) -> list[str]:
    raw_value = _get_required_value(row, field_name, line_number)
    try:
        parsed_value = ast.literal_eval(raw_value)
    except (SyntaxError, ValueError) as error:
        raise ValueError(
            f"Invalid list in '{field_name}' on CSV line {line_number}."
        ) from error

    if not isinstance(parsed_value, list):
        raise ValueError(
            f"Expected a list in '{field_name}' on CSV line {line_number}."
        )

    return list(
        dict.fromkeys(str(item).strip() for item in parsed_value if str(item).strip())
    )


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _generate_movie_price(randomizer: Random) -> Decimal:
    cents = randomizer.randint(MIN_MOVIE_PRICE_CENTS, MAX_MOVIE_PRICE_CENTS)
    return Decimal(cents).scaleb(-2)


def _read_movie_seed_data(
    csv_path: Path, price_seed: int = MOVIE_PRICE_RANDOM_SEED
) -> list[MovieSeedData]:
    randomizer = Random(price_seed)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required_columns = {
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
        }
        missing_columns = required_columns.difference(reader.fieldnames or [])
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"CSV file is missing required columns: {missing}.")

        movies = []
        for line_number, row in enumerate(reader, start=2):
            description_words = _parse_list_field(row, "Description", line_number)
            certification = (row.get("Certification") or "").strip()

            try:
                movie = MovieSeedData(
                    name=_get_required_value(row, "Movie Name", line_number),
                    year=int(_get_required_value(row, "Year of Release", line_number)),
                    time=int(
                        _get_required_value(row, "Run Time in minutes", line_number)
                    ),
                    imdb=float(_get_required_value(row, "Movie Rating", line_number)),
                    votes=int(_get_required_value(row, "Votes", line_number)),
                    meta_score=_parse_optional_float(row.get("MetaScore")),
                    gross=_parse_optional_float(row.get("Gross")),
                    description=" ".join(description_words),
                    price=_generate_movie_price(randomizer),
                    certification=certification or DEFAULT_CERTIFICATION,
                    stars=_parse_list_field(row, "Stars", line_number),
                    genres=_parse_list_field(row, "Genre", line_number),
                    directors=_parse_list_field(row, "Director", line_number),
                )
            except ValueError as error:
                if "CSV line" in str(error):
                    raise
                raise ValueError(
                    f"Invalid numeric value on CSV line {line_number}."
                ) from error

            movies.append(movie)

    return movies


def _get_or_create_named_model(
    cache: dict[str, NamedModel],
    model_class: type[NamedModel],
    name: str,
) -> NamedModel:
    model = cache.get(name)
    if model is None:
        model = model_class(name=name)
        cache[name] = model
    return model


async def populate_movies(
    db_session: AsyncSession | None = None,
    csv_path: Path = MOVIES_CSV_PATH,
    batch_size: int = MOVIE_IMPORT_BATCH_SIZE,
    price_seed: int = MOVIE_PRICE_RANDOM_SEED,
) -> None:
    """Populate the movie catalog from the IMDb CSV file."""
    if batch_size < 1:
        raise ValueError("Movie import batch size must be greater than zero.")
    if not csv_path.is_file():
        raise FileNotFoundError(f"Movie seed file was not found: {csv_path}")

    if db_session is None:
        async with get_db_contextmanager() as session:
            await _populate_movies(session, csv_path, batch_size, price_seed)
        return

    await _populate_movies(db_session, csv_path, batch_size, price_seed)


async def _populate_movies(
    session: AsyncSession,
    csv_path: Path,
    batch_size: int,
    price_seed: int,
) -> None:
    movie_data = _read_movie_seed_data(csv_path, price_seed)
    existing_movie_rows = await session.execute(
        select(MovieModel.name, MovieModel.year, MovieModel.time)
    )
    existing_movie_keys = {
        (name, year, time) for name, year, time in existing_movie_rows.all()
    }
    pending_movies = [
        movie for movie in movie_data if movie.unique_key not in existing_movie_keys
    ]

    if not pending_movies:
        print(f"Movie catalog is already populated. Skipped {len(movie_data)} movies.")
        return

    certifications = {
        item.name: item
        for item in (await session.scalars(select(CertificationModel))).all()
    }
    stars = {
        item.name: item for item in (await session.scalars(select(StarModel))).all()
    }
    genres = {
        item.name: item for item in (await session.scalars(select(GenreModel))).all()
    }
    directors = {
        item.name: item for item in (await session.scalars(select(DirectorModel))).all()
    }

    created = 0
    for item in pending_movies:
        movie = MovieModel(
            name=item.name,
            year=item.year,
            time=item.time,
            imdb=item.imdb,
            votes=item.votes,
            meta_score=item.meta_score,
            gross=item.gross,
            description=item.description,
            price=item.price,
            certification=_get_or_create_named_model(
                certifications, CertificationModel, item.certification
            ),
            stars=[
                _get_or_create_named_model(stars, StarModel, name)
                for name in item.stars
            ],
            genres=[
                _get_or_create_named_model(genres, GenreModel, name)
                for name in item.genres
            ],
            directors=[
                _get_or_create_named_model(directors, DirectorModel, name)
                for name in item.directors
            ],
        )
        session.add(movie)
        created += 1

        if created % batch_size == 0:
            await session.commit()

    if created % batch_size:
        await session.commit()

    skipped = len(movie_data) - created
    print(
        f"Movie catalog populated successfully: {created} created, {skipped} skipped."
    )


async def main() -> None:
    await populate_user_groups()
    await populate_movies()


if __name__ == "__main__":
    asyncio.run(main())
