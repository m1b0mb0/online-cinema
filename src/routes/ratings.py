from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Response,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import (
    MovieRatingModel,
    UserModel,
    get_db,
)
from src.schemas import (
    RatingRequestSchema,
    MovieRatingsSummarySchema,
    CurrentMovieRatingsSchema,
)
from src.security.dependencies import get_current_active_user
from src.services import get_movie_by_uuid_or_404

router = APIRouter()

AUTH_RESPONSES = {
    401: {"description": "Access token is missing or invalid."},
    403: {"description": "User account is not activated."},
}


async def _get_rating_summary(
    db: AsyncSession,
    movie_id: int,
) -> tuple[float | None, int]:
    average_rating, ratings_count = (
        await db.execute(
            select(
                func.avg(MovieRatingModel.score),
                func.count(MovieRatingModel.score),
            ).where(MovieRatingModel.movie_id == movie_id)
        )
    ).one()
    return (
        round(float(average_rating), 2)
        if average_rating is not None
        else None,
        int(ratings_count),
    )


@router.get(
    "/movies/{movie_uuid}/ratings/",
    response_model=MovieRatingsSummarySchema,
    summary="Get Movie Rating Summary",
    description="Return the public average score and rating count for a movie.",
    response_description="Movie rating summary.",
    responses={404: {"description": "Movie was not found."}},
)
async def get_movie_rating(
    movie_uuid: UUID,
    db: AsyncSession = Depends(get_db),
) -> MovieRatingsSummarySchema:
    movie = await get_movie_by_uuid_or_404(db, movie_uuid)

    average_rating, ratings_count = await _get_rating_summary(db, movie.id)

    return MovieRatingsSummarySchema(
        movie_uuid=movie.uuid,
        average_rating=average_rating,
        ratings_count=ratings_count,
    )


@router.get(
    "/movies/{movie_uuid}/rating/",
    response_model=CurrentMovieRatingsSchema,
    summary="Get Current User Movie Rating",
    description=(
        "Return the current user's score together with the public rating "
        "summary for a movie."
    ),
    response_description="Current score and movie rating summary.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
    },
)
async def get_current_user_movie_rating(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentMovieRatingsSchema:
    movie = await get_movie_by_uuid_or_404(db, movie_uuid)

    rating = await db.get(
        MovieRatingModel,
        (current_user.id, movie.id),
    )
    average_rating, ratings_count = await _get_rating_summary(db, movie.id)

    return CurrentMovieRatingsSchema(
        movie_uuid=movie.uuid,
        average_rating=average_rating,
        ratings_count=ratings_count,
        current_user_rating=(rating.score if rating is not None else None),
    )


@router.put(
    "/movies/{movie_uuid}/rating/",
    response_model=CurrentMovieRatingsSchema,
    summary="Set Current User Movie Rating",
    description=(
        "Create or replace the current user's score on a 10-point scale. "
        "Repeating the same request is idempotent."
    ),
    response_description="Updated score and movie rating summary.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
    },
)
async def set_current_user_movie_rating(
    movie_uuid: UUID,
    rating_data: RatingRequestSchema,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentMovieRatingsSchema:
    movie = await get_movie_by_uuid_or_404(db, movie_uuid)

    rating = await db.get(
        MovieRatingModel,
        (current_user.id, movie.id),
    )
    if rating is None:
        rating = MovieRatingModel(
            user_id=current_user.id,
            movie_id=movie.id,
            score=rating_data.score,
        )
        db.add(rating)
    elif rating.score != rating_data.score:
        rating.score = rating_data.score

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        rating = await db.get(
            MovieRatingModel,
            (current_user.id, movie.id),
        )
        if rating is None:
            raise
        if rating.score != rating_data.score:
            rating.score = rating_data.score
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise
    except SQLAlchemyError:
        await db.rollback()
        raise

    average_rating, ratings_count = await _get_rating_summary(db, movie.id)
    return CurrentMovieRatingsSchema(
        movie_uuid=movie.uuid,
        average_rating=average_rating,
        ratings_count=ratings_count,
        current_user_rating=rating.score,
    )


@router.delete(
    "/movies/{movie_uuid}/rating/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Current User Movie Rating",
    description=(
        "Remove the current user's score from a movie. The operation is "
        "idempotent and also succeeds when no score exists."
    ),
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
    },
)
async def remove_current_user_movie_rating(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    movie = await get_movie_by_uuid_or_404(db, movie_uuid)

    rating = await db.get(
        MovieRatingModel,
        (current_user.id, movie.id),
    )
    if rating is not None:
        await db.delete(rating)
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise

    return Response(status_code=status.HTTP_204_NO_CONTENT)
