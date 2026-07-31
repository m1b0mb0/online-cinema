import math
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import FavoriteModel, MovieModel, UserModel, get_db
from src.schemas import (
    FavoriteResponseSchema,
    MovieFilterParams,
    MovieListItemSchema,
    MovieListResponseSchema,
)
from src.security.dependencies import get_current_active_user
from src.services import get_favorite_movies_page

router = APIRouter()

AUTH_RESPONSES = {
    401: {"description": "Access token is missing or invalid."},
    403: {"description": "User account is not activated."},
}


@router.get(
    "/favorites/",
    response_model=MovieListResponseSchema,
    summary="List Favorite Movies",
    description=(
        "Return the current user's favorite movies. The endpoint supports the "
        "same pagination, search, filtering, and sorting parameters as the movie "
        "catalog."
    ),
    response_description="Paginated favorite movie catalog.",
    responses=AUTH_RESPONSES,
)
async def get_favorite_movies(
    request: Request,
    filters: Annotated[MovieFilterParams, Query()],
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    movies, total_items = await get_favorite_movies_page(
        db,
        current_user.id,
        filters,
    )
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
        movies=[MovieListItemSchema.model_validate(movie) for movie in movies],
        prev_page=prev_page,
        next_page=next_page,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.post(
    "/favorites/{movie_uuid}/",
    response_model=FavoriteResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Add Movie To Favorites",
    description="Add a movie to the current user's favorites.",
    response_description="Created favorite entry.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
        409: {"description": "Movie is already in the user's favorites."},
    },
)
async def add_movie_to_favorites(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteResponseSchema:
    movie = await db.scalar(select(MovieModel).where(MovieModel.uuid == movie_uuid))
    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    favorite = await db.get(
        FavoriteModel,
        (current_user.id, movie.id),
    )
    if favorite:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Movie is already in favorites.",
        )

    favorite = FavoriteModel(
        user_id=current_user.id,
        movie_id=movie.id,
    )
    db.add(favorite)

    try:
        await db.commit()
        await db.refresh(favorite)
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Movie is already in favorites.",
        ) from error

    return FavoriteResponseSchema(
        added_at=favorite.added_at,
        movie=MovieListItemSchema.model_validate(movie),
    )


@router.delete(
    "/favorites/{movie_uuid}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Movie From Favorites",
    description="Remove a movie from the current user's favorites.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie is not in the user's favorites."},
    },
)
async def remove_movie_from_favorites(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    favorite = await db.scalar(
        select(FavoriteModel)
        .join(MovieModel, FavoriteModel.movie_id == MovieModel.id)
        .where(
            FavoriteModel.user_id == current_user.id,
            MovieModel.uuid == movie_uuid,
        )
    )
    if not favorite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie is not in favorites.",
        )

    await db.delete(favorite)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
