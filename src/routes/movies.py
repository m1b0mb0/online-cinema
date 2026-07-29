import math
from typing import Annotated

from fastapi import APIRouter, Depends, status, HTTPException, Query, Request
from sqlalchemy import func, select
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
from src.services import (
    apply_movie_filters,
    apply_movie_sorting,
    get_or_create_models_by_name,
)

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

    count_stmt = select(func.count()).select_from(
        filtered_stmt.order_by(None).subquery()
    )
    total_items = await db.scalar(count_stmt) or 0

    sorted_stmt = apply_movie_sorting(statement=filtered_stmt, filters=filters)

    offset = (filters.page - 1) * filters.per_page

    movies_stmt = sorted_stmt.offset(offset).limit(filters.per_page)

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
        certifications = await get_or_create_models_by_name(
            db, CertificationModel, [movie_data.certification]
        )
        stars = await get_or_create_models_by_name(db, StarModel, movie_data.stars)
        genres = await get_or_create_models_by_name(db, GenreModel, movie_data.genres)
        directors = await get_or_create_models_by_name(
            db, DirectorModel, movie_data.directors
        )

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
            certification=certifications[0],
            stars=stars,
            genres=genres,
            directors=directors,
        )
        db.add(movie)
        await db.commit()
        await db.refresh(movie, ["certification", "stars", "genres", "directors"])

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


@router.patch("/movies/{movie_uuid}/", response_model=MovieDetailSchema)
async def update_movie(
    movie_uuid: str,
    movie_data: MovieUpdateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_moderator_or_admin_user),
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

    update_data = movie_data.model_dump(exclude_unset=True)

    certification_name = update_data.pop("certification", None)
    star_names = update_data.pop("stars", None)
    genre_names = update_data.pop("genres", None)
    director_names = update_data.pop("directors", None)

    for field, value in update_data.items():
        setattr(movie, field, value)

    if certification_name is not None:
        certifications = await get_or_create_models_by_name(
            db,
            CertificationModel,
            [certification_name],
        )
        movie.certification = certifications[0]

    if star_names is not None:
        movie.stars = await get_or_create_models_by_name(
            db,
            StarModel,
            star_names,
        )

    if genre_names is not None:
        movie.genres = await get_or_create_models_by_name(
            db,
            GenreModel,
            genre_names,
        )

    if director_names is not None:
        movie.directors = await get_or_create_models_by_name(
            db,
            DirectorModel,
            director_names,
        )

    try:
        await db.commit()
        await db.refresh(
            movie,
            ["certification", "stars", "genres", "directors"],
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid input data."
        )

    return MovieDetailSchema.model_validate(movie)


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
