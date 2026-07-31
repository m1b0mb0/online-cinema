from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import (
    MovieModel,
    MovieReactionModel,
    ReactionTypeEnum,
    UserModel,
    get_db,
)
from src.schemas import (
    CurrentMovieReactionSchema,
    MovieReactionSummarySchema,
    ReactionRequestSchema,
)
from src.security.dependencies import get_current_active_user

router = APIRouter()

AUTH_RESPONSES = {
    401: {"description": "Access token is missing or invalid."},
    403: {"description": "User account is not activated."},
}


@router.get(
    "/movies/{movie_uuid}/reactions/",
    response_model=MovieReactionSummarySchema,
    summary="Get Movie Reaction Summary",
    description="Return public like and dislike counts for a movie.",
    response_description="Movie reaction counts.",
    responses={404: {"description": "Movie was not found."}},
)
async def get_movie_reaction_summary(
    movie_uuid: UUID,
    db: AsyncSession = Depends(get_db),
) -> MovieReactionSummarySchema:
    movie = await db.scalar(
        select(MovieModel).where(MovieModel.uuid == movie_uuid)
    )
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    counts_statement = select(
        func.sum(
            case(
                (
                    MovieReactionModel.reaction_type
                    == ReactionTypeEnum.LIKE,
                    1,
                ),
                else_=0,
            )
        ).label("likes_count"),
        func.sum(
            case(
                (
                    MovieReactionModel.reaction_type
                    == ReactionTypeEnum.DISLIKE,
                    1,
                ),
                else_=0,
            )
        ).label("dislikes_count"),
    ).where(MovieReactionModel.movie_id == movie.id)
    counts = (await db.execute(counts_statement)).one()

    return MovieReactionSummarySchema(
        movie_uuid=movie.uuid,
        likes_count=int(counts.likes_count or 0),
        dislikes_count=int(counts.dislikes_count or 0),
    )


@router.get(
    "/movies/{movie_uuid}/reaction/",
    response_model=CurrentMovieReactionSchema,
    summary="Get Current User Movie Reaction",
    description=(
        "Return the current user's reaction and aggregate reaction counts "
        "for a movie."
    ),
    response_description="Current reaction and movie reaction counts.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
    },
)
async def get_current_user_movie_reaction(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentMovieReactionSchema:
    movie = await db.scalar(
        select(MovieModel).where(MovieModel.uuid == movie_uuid)
    )
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    reaction = await db.get(
        MovieReactionModel,
        (current_user.id, movie.id),
    )
    counts_statement = select(
        func.sum(
            case(
                (
                    MovieReactionModel.reaction_type
                    == ReactionTypeEnum.LIKE,
                    1,
                ),
                else_=0,
            )
        ).label("likes_count"),
        func.sum(
            case(
                (
                    MovieReactionModel.reaction_type
                    == ReactionTypeEnum.DISLIKE,
                    1,
                ),
                else_=0,
            )
        ).label("dislikes_count"),
    ).where(MovieReactionModel.movie_id == movie.id)
    counts = (await db.execute(counts_statement)).one()

    return CurrentMovieReactionSchema(
        movie_uuid=movie.uuid,
        likes_count=int(counts.likes_count or 0),
        dislikes_count=int(counts.dislikes_count or 0),
        current_user_reaction=(
            reaction.reaction_type if reaction is not None else None
        ),
    )


@router.put(
    "/movies/{movie_uuid}/reaction/",
    response_model=CurrentMovieReactionSchema,
    summary="Set Current User Movie Reaction",
    description=(
        "Create or replace the current user's reaction to a movie. Repeating "
        "the same request is idempotent."
    ),
    response_description="Updated reaction and movie reaction counts.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
    },
)
async def set_current_user_movie_reaction(
    movie_uuid: UUID,
    data: ReactionRequestSchema,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentMovieReactionSchema:
    movie = await db.scalar(
        select(MovieModel).where(MovieModel.uuid == movie_uuid)
    )
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    reaction = await db.get(
        MovieReactionModel,
        (current_user.id, movie.id),
    )
    if reaction is None:
        reaction = MovieReactionModel(
            user_id=current_user.id,
            movie_id=movie.id,
            reaction_type=data.reaction_type,
        )
        db.add(reaction)
    elif reaction.reaction_type != data.reaction_type:
        reaction.reaction_type = data.reaction_type

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        reaction = await db.get(
            MovieReactionModel,
            (current_user.id, movie.id),
        )
        if reaction is None:
            raise
        if reaction.reaction_type != data.reaction_type:
            reaction.reaction_type = data.reaction_type
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise
    except SQLAlchemyError:
        await db.rollback()
        raise

    counts_statement = select(
        func.sum(
            case(
                (
                    MovieReactionModel.reaction_type
                    == ReactionTypeEnum.LIKE,
                    1,
                ),
                else_=0,
            )
        ).label("likes_count"),
        func.sum(
            case(
                (
                    MovieReactionModel.reaction_type
                    == ReactionTypeEnum.DISLIKE,
                    1,
                ),
                else_=0,
            )
        ).label("dislikes_count"),
    ).where(MovieReactionModel.movie_id == movie.id)
    counts = (await db.execute(counts_statement)).one()

    return CurrentMovieReactionSchema(
        movie_uuid=movie.uuid,
        likes_count=int(counts.likes_count or 0),
        dislikes_count=int(counts.dislikes_count or 0),
        current_user_reaction=reaction.reaction_type,
    )


@router.delete(
    "/movies/{movie_uuid}/reaction/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Current User Movie Reaction",
    description=(
        "Remove the current user's reaction from a movie. The operation is "
        "idempotent and also succeeds when no reaction exists."
    ),
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
    },
)
async def remove_current_user_movie_reaction(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    movie = await db.scalar(
        select(MovieModel).where(MovieModel.uuid == movie_uuid)
    )
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given UUID was not found.",
        )

    reaction = await db.get(
        MovieReactionModel,
        (current_user.id, movie.id),
    )
    if reaction is not None:
        await db.delete(reaction)
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise

    return Response(status_code=status.HTTP_204_NO_CONTENT)
