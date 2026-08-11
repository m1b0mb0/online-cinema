from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.database import (
    CartItemModel,
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
)
from src.schemas.filters import MovieFilterParams
from src.database import get_db
from src.security.dependencies import get_moderator_or_admin_user
from src.services import (
    apply_movie_filters,
    apply_movie_sorting,
    get_movie_by_uuid_or_404,
    get_or_create_models_by_name,
)
from src.utils import build_pagination

router = APIRouter()

AUTH_RESPONSES = {
    401: {"description": "A valid access token is required."},
    403: {"description": "Moderator or administrator privileges are required."},
}


@router.get(
    "/movies/",
    response_model=MovieListResponseSchema,
    summary="List Movies",
    description=(
        "Return a paginated movie catalog. Supports search by title, description, "
        "actor, or director; filtering by year, IMDb rating, price, genre, and "
        "certification; and sorting by name, year, price, IMDb rating, popularity, "
        "or newest catalog entry."
    ),
    response_description="Paginated movie catalog.",
)
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

    pagination = build_pagination(
        request=request,
        page=filters.page,
        per_page=filters.per_page,
        total_items=total_items,
    )

    return MovieListResponseSchema(
        movies=movie_list,
        **pagination,
    )


@router.post(
    "/movies/",
    response_model=MovieDetailSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Movie",
    description=(
        "Create a movie and reuse or create its certification, actors, genres, "
        "and directors. Moderator or administrator access is required."
    ),
    response_description="Created movie with all catalog relationships.",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "The supplied movie data violates a database constraint."},
        409: {
            "description": (
                "A movie with the same name, release year, and runtime already exists."
            )
        },
    },
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


@router.get(
    "/movies/{movie_uuid}/",
    response_model=MovieDetailSchema,
    summary="Get Movie Details",
    description="Return a movie and its certification, actors, genres, and directors.",
    response_description="Detailed movie information.",
    responses={404: {"description": "Movie was not found."}},
)
async def get_movie_by_uuid(
    movie_uuid: UUID, db: AsyncSession = Depends(get_db)
) -> MovieDetailSchema:
    movie = await get_movie_by_uuid_or_404(
        db,
        movie_uuid,
        loader_options=(
            joinedload(MovieModel.certification),
            selectinload(MovieModel.stars),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.directors),
        ),
    )

    return MovieDetailSchema.model_validate(movie)


@router.patch(
    "/movies/{movie_uuid}/",
    response_model=MovieDetailSchema,
    summary="Update Movie",
    description=(
        "Partially update movie fields and optionally replace its certification, "
        "actors, genres, or directors. Moderator or administrator access is required."
    ),
    response_description="Updated movie with all catalog relationships.",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "The supplied movie data violates a database constraint."},
        404: {"description": "Movie was not found."},
    },
)
async def update_movie(
    movie_uuid: UUID,
    movie_data: MovieUpdateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_moderator_or_admin_user),
) -> MovieDetailSchema:
    movie = await get_movie_by_uuid_or_404(
        db,
        movie_uuid,
        loader_options=(
            joinedload(MovieModel.certification),
            selectinload(MovieModel.stars),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.directors),
        ),
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


@router.delete(
    "/movies/{movie_uuid}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Movie",
    description="Delete a movie. Moderator or administrator access is required.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
        409: {"description": "Movie is currently present in a user's cart."},
    },
)
async def delete_movie(
    movie_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_moderator_or_admin_user),
) -> Response:
    movie = await get_movie_by_uuid_or_404(db, movie_uuid)

    cart_item_id = await db.scalar(
        select(CartItemModel.id)
        .where(CartItemModel.movie_id == movie.id)
        .limit(1)
    )
    if cart_item_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Movie cannot be deleted because it is currently in a user's cart."
            ),
        )

    try:
        await db.delete(movie)
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Movie cannot be deleted because it is currently in use.",
        ) from error

    return Response(status_code=status.HTTP_204_NO_CONTENT)
