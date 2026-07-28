from sqlalchemy import or_
from sqlalchemy.sql import Select

from src.database import MovieModel, GenreModel, CertificationModel
from src.schemas import MovieFilterParams, MovieSortField, SortOrder

SORT_COLUMNS = {
    MovieSortField.NEWEST: MovieModel.id,
    MovieSortField.NAME: MovieModel.name,
    MovieSortField.YEAR: MovieModel.year,
    MovieSortField.PRICE: MovieModel.price,
    MovieSortField.IMDB: MovieModel.imdb,
    MovieSortField.POPULARITY: MovieModel.votes,
}


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
