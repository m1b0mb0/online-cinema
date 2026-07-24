from sqlalchemy import or_
from sqlalchemy.sql import Select

from src.database import MovieModel, GenreModel, CertificationModel
from src.schemas import MovieFilterParams


def apply_movie_filters(statement: Select, filters: MovieFilterParams) -> Select:
    if filters.search:
        search_pattern = f"%{filters.search}%"

        statement = statement.where(
            or_(
                MovieModel.name.ilike(search_pattern),
                MovieModel.description.ilike(search_pattern),
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
