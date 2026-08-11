from collections.abc import Sequence
from typing import TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.interfaces import LoaderOption
from sqlalchemy.sql import Select

from src.database import (
    CertificationModel,
    DirectorModel,
    FavoriteModel,
    GenreModel,
    MovieGenresModel,
    MovieModel,
    StarModel,
)
from src.schemas import MovieFilterParams, MovieSortField, SortOrder

SORT_COLUMNS = {
    MovieSortField.NEWEST: MovieModel.id,
    MovieSortField.NAME: MovieModel.name,
    MovieSortField.YEAR: MovieModel.year,
    MovieSortField.PRICE: MovieModel.price,
    MovieSortField.IMDB: MovieModel.imdb,
    MovieSortField.POPULARITY: MovieModel.votes,
}

ModelType = TypeVar(
    "ModelType",
    CertificationModel,
    DirectorModel,
    GenreModel,
    StarModel,
)


async def get_movie_by_uuid_or_404(
    db: AsyncSession,
    movie_uuid: UUID,
    loader_options: Sequence[LoaderOption] = (),
) -> MovieModel:
    statement = select(MovieModel).where(MovieModel.uuid == movie_uuid)
    if loader_options:
        statement = statement.options(*loader_options)

    movie = await db.scalar(statement)
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    return movie


def apply_movie_sorting(statement: Select, filters: MovieFilterParams) -> Select:
    column = SORT_COLUMNS[filters.sort_by]

    primary_order = (
        column.asc() if filters.sort_order == SortOrder.ASC else column.desc()
    )

    tie_breaker = (
        MovieModel.id.asc()
        if filters.sort_order == SortOrder.ASC
        else MovieModel.id.desc()
    )

    return statement.order_by(primary_order, tie_breaker)


def apply_movie_filters(statement: Select, filters: MovieFilterParams) -> Select:
    if filters.search:
        search_pattern = f"%{filters.search}%"

        statement = statement.where(
            or_(
                MovieModel.name.ilike(search_pattern),
                MovieModel.description.ilike(search_pattern),
                MovieModel.stars.any(StarModel.name.ilike(search_pattern)),
                MovieModel.directors.any(DirectorModel.name.ilike(search_pattern)),
            )
        )

    if filters.years:
        statement = statement.where(MovieModel.year.in_(filters.years))

    if filters.year_from is not None:
        statement = statement.where(MovieModel.year >= filters.year_from)

    if filters.year_to is not None:
        statement = statement.where(MovieModel.year <= filters.year_to)

    if filters.imdb_min is not None:
        statement = statement.where(MovieModel.imdb >= filters.imdb_min)

    if filters.imdb_max is not None:
        statement = statement.where(MovieModel.imdb <= filters.imdb_max)

    if filters.price_min is not None:
        statement = statement.where(MovieModel.price >= filters.price_min)

    if filters.price_max is not None:
        statement = statement.where(MovieModel.price <= filters.price_max)

    if filters.genre_ids:
        statement = statement.where(
            MovieModel.genres.any(GenreModel.id.in_(filters.genre_ids))
        )

    if filters.certification_ids:
        statement = statement.where(
            MovieModel.certification.has(
                CertificationModel.id.in_(filters.certification_ids)
            )
        )

    return statement


async def get_or_create_models_by_name(
    db: AsyncSession, model: type[ModelType], names: list[str]
) -> list[ModelType]:
    normalized_names = list(dict.fromkeys(names))

    existing_items = (
        await db.scalars(select(model).where(model.name.in_(normalized_names)))
    ).all()

    items_by_name = {item.name: item for item in existing_items}

    missing_items = [
        model(name=name) for name in normalized_names if name not in items_by_name
    ]

    if missing_items:
        db.add_all(missing_items)
        await db.flush()

        items_by_name.update({item.name: item for item in missing_items})

    return [items_by_name[name] for name in normalized_names]


async def get_named_models_page(
    db: AsyncSession,
    model: type[ModelType],
    page: int,
    per_page: int,
    search: str | None = None,
) -> tuple[list[ModelType], int]:
    statement = select(model)
    count_statement = select(func.count(model.id))

    if search:
        search_condition = model.name.ilike(f"%{search}%")
        statement = statement.where(search_condition)
        count_statement = count_statement.where(search_condition)

    statement = (
        statement.order_by(func.lower(model.name), model.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )

    items = list((await db.scalars(statement)).all())
    total_items = await db.scalar(count_statement) or 0
    return items, total_items


async def get_genres_with_movie_counts(
    db: AsyncSession,
    page: int,
    per_page: int,
    search: str | None = None,
) -> tuple[list[dict[str, int | str]], int]:
    search_condition = None
    if search:
        search_condition = GenreModel.name.ilike(f"%{search}%")

    count_statement = select(func.count(GenreModel.id))
    if search_condition is not None:
        count_statement = count_statement.where(search_condition)

    movie_count = func.count(MovieGenresModel.c.movie_id).label("movie_count")
    statement = (
        select(
            GenreModel.id,
            GenreModel.name,
            movie_count,
        )
        .outerjoin(
            MovieGenresModel,
            GenreModel.id == MovieGenresModel.c.genre_id,
        )
        .group_by(GenreModel.id, GenreModel.name)
        .order_by(func.lower(GenreModel.name), GenreModel.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )

    if search_condition is not None:
        statement = statement.where(search_condition)

    rows = (await db.execute(statement)).mappings().all()
    genres = [dict(row) for row in rows]
    total_items = await db.scalar(count_statement) or 0
    return genres, total_items


async def get_named_model_by_id(
    db: AsyncSession,
    model: type[ModelType],
    item_id: int,
) -> ModelType | None:
    return await db.get(model, item_id)


async def get_named_model_by_name(
    db: AsyncSession,
    model: type[ModelType],
    name: str,
) -> ModelType | None:
    return await db.scalar(select(model).where(func.lower(model.name) == name.lower()))


async def get_favorite_movies_page(
    db: AsyncSession,
    user_id: int,
    filters: MovieFilterParams,
) -> tuple[list[MovieModel], int]:
    statement = (
        select(MovieModel)
        .join(FavoriteModel, FavoriteModel.movie_id == MovieModel.id)
        .where(FavoriteModel.user_id == user_id)
    )
    statement = apply_movie_filters(statement, filters)

    count_statement = select(func.count()).select_from(
        statement.order_by(None).subquery()
    )
    total_items = await db.scalar(count_statement) or 0

    statement = apply_movie_sorting(statement, filters)
    statement = statement.offset((filters.page - 1) * filters.per_page).limit(
        filters.per_page
    )
    movies = list((await db.scalars(statement)).all())

    return movies, total_items
