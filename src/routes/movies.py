import math
from typing import Annotated

from fastapi import APIRouter, Depends, status, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.database import (
    UserModel,
    MovieModel,
    CertificationModel,
    StarModel,
    GenreModel,
    DirectorModel,
)
from src.schemas.movies import (
    MovieUpdateSchema,
    MovieCreateSchema,
    MovieDetailSchema,
    MovieListItemSchema,
    MovieListResponseSchema,
    MovieFilterParams,
)
from src.database import get_db
from src.security.dependencies import get_admin_user, get_moderator_or_admin_user
from src.services import apply_movie_filters

router = APIRouter()


@router.get("/movies/", response_model=MovieListResponseSchema)
async def get_movie_list(
    request: Request,
    filters: Annotated[MovieFilterParams, Query()],
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    filtered_stmt = apply_movie_filters(
        statement=select(MovieModel),
        filters=filters,
    )

    offset = (filters.page - 1) * filters.per_page

    count_stmt = select(func.count()).select_from(
        filtered_stmt.order_by(None).subquery()
    )
    total_items = await db.scalar(count_stmt) or 0

    movies_stmt = (
        filtered_stmt.order_by(desc(MovieModel.id))
        .offset(offset)
        .limit(filters.per_page)
    )

    movies = list((await db.scalars(movies_stmt)).all())

    movie_list = [MovieListItemSchema.model_validate(movie) for movie in movies]

    total_pages = math.ceil(total_items / filters.per_page)

    prev_page = (
        str(
            request.url.include_query_params(
                page=filters.page - 1,
                per_page=filters.per_page,
            )
        )
        if filters.page > 1
        else None
    )

    next_page = (
        str(
            request.url.include_query_params(
                page=filters.page + 1,
                per_page=filters.per_page,
            )
        )
        if filters.page < total_pages
        else None
    )

    return MovieListResponseSchema(
        movies=movie_list,
        prev_page=prev_page,
        next_page=next_page,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.post(
    "/movies/", response_model=MovieDetailSchema, status_code=status.HTTP_201_CREATED
)
async def create_movie(
    movie_data: MovieCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_moderator_or_admin_user),
) -> MovieDetailSchema:
    existing_movie = await db.scalar(
        select(MovieModel).where(
            MovieModel.name == movie_data.name,
            MovieModel.year == movie_data.year,
            MovieModel.time == movie_data.time,
        )
    )

    if existing_movie:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A movie with the name '{movie_data.name}', year "
                f"'{movie_data.year}' and time '{movie_data.time}' already exists."
            ),
        )

    try:
        certification = await db.scalar(
            select(CertificationModel).where(
                CertificationModel.name == movie_data.certification
            )
        )

        if not certification:
            certification = CertificationModel(name=movie_data.certification)
            db.add(certification)
            await db.flush()

        stars = []
        for star_name in movie_data.stars:
            star = await db.scalar(select(StarModel).where(StarModel.name == star_name))

            if not star:
                star = StarModel(name=star_name)
                db.add(star)
                await db.flush()
            stars.append(star)

        genres = []
        for genre_name in movie_data.genres:
            genre = await db.scalar(
                select(GenreModel).where(GenreModel.name == genre_name)
            )

            if not genre:
                genre = GenreModel(name=genre_name)
                db.add(genre)
                await db.flush()
            genres.append(genre)

        directors = []
        for director_name in movie_data.directors:
            director = await db.scalar(
                select(DirectorModel).where(DirectorModel.name == director_name)
            )

            if not director:
                director = DirectorModel(name=director_name)
                db.add(director)
                await db.flush()
            directors.append(director)

        movie = MovieModel(
            name=movie_data.name,
            year=movie_data.year,
            time=movie_data.time,
            imdb=movie_data.imdb,
            votes=movie_data.votes,
            meta_score=movie_data.meta_score,
            gross=movie_data.gross,
            description=movie_data.description,
            price=movie_data.price,
            certification=certification,
            stars=stars,
            genres=genres,
            directors=directors,
        )
        db.add(movie)
        await db.commit()
        await db.refresh(movie, ["stars", "genres", "directors"])

        return MovieDetailSchema.model_validate(movie)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid input data."
        )


@router.get("/movies/{movie_uuid}/", response_model=MovieDetailSchema)
async def get_movie_by_uuid(
    movie_uuid: str, db: AsyncSession = Depends(get_db)
) -> MovieDetailSchema:
    stmt = (
        select(MovieModel)
        .options(
            joinedload(MovieModel.certification),
            selectinload(MovieModel.stars),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.directors),
        )
        .where(MovieModel.uuid == movie_uuid)
    )

    movie = await db.scalar(stmt)

    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    return MovieDetailSchema.model_validate(movie)


@router.patch("/movies/{movie_uuid}/")
async def update_movie(
    movie_uuid: str,
    movie_data: MovieUpdateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_moderator_or_admin_user),
):
    movie = await db.scalar(select(MovieModel).where(MovieModel.uuid == movie_uuid))

    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    for field, value in movie_data.model_dump(exclude_unset=True).items():
        setattr(movie, field, value)

    try:
        await db.commit()
        await db.refresh(movie)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid input data."
        )

    return {"detail": "Movie updated successfully."}


@router.delete("/movies/{movie_uuid}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_movie(
    movie_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_admin_user),
):
    movie = await db.scalar(select(MovieModel).where(MovieModel.uuid == movie_uuid))

    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    await db.delete(movie)
    await db.commit()

    return {"detail": "Movie deleted successfully."}
