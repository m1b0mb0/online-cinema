from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from src.database import (
    CommentModel,
    CommentReactionModel,
    MovieModel,
    MovieReactionModel,
    ReactionTypeEnum,
    UserModel,
    get_db,
)
from src.schemas import (
    CommentReactionSummarySchema,
    CurrentCommentReactionSchema,
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

TargetModel = TypeVar("TargetModel", MovieModel, CommentModel)
ReactionModel = TypeVar(
    "ReactionModel",
    MovieReactionModel,
    CommentReactionModel,
)


async def _get_reaction_target_or_404(
    db: AsyncSession,
    model: type[TargetModel],
    target_uuid: UUID,
    entity_name: str,
) -> TargetModel:
    target = await db.scalar(
        select(model).where(model.uuid == target_uuid)
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{entity_name} with the given UUID was not found.",
        )
    return target


async def _get_reaction_counts(
    db: AsyncSession,
    reaction_model: type[ReactionModel],
    target_column: InstrumentedAttribute[int],
    target_id: int,
) -> tuple[int, int]:
    counts_statement = select(
        func.sum(
            case(
                (
                    reaction_model.reaction_type == ReactionTypeEnum.LIKE,
                    1,
                ),
                else_=0,
            )
        ).label("likes_count"),
        func.sum(
            case(
                (
                    reaction_model.reaction_type == ReactionTypeEnum.DISLIKE,
                    1,
                ),
                else_=0,
            )
        ).label("dislikes_count"),
    ).where(target_column == target_id)
    counts = (await db.execute(counts_statement)).one()
    return (
        int(counts.likes_count or 0),
        int(counts.dislikes_count or 0),
    )


async def _set_reaction(
    db: AsyncSession,
    key: tuple[int, int],
    new_reaction: ReactionModel,
) -> ReactionModel:
    reaction_model = type(new_reaction)
    reaction = await db.get(reaction_model, key)
    if reaction is None:
        reaction = new_reaction
        db.add(reaction)
    elif reaction.reaction_type != new_reaction.reaction_type:
        reaction.reaction_type = new_reaction.reaction_type

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        reaction = await db.get(reaction_model, key)
        if reaction is None:
            raise
        if reaction.reaction_type != new_reaction.reaction_type:
            reaction.reaction_type = new_reaction.reaction_type
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise
    except SQLAlchemyError:
        await db.rollback()
        raise

    return reaction


async def _remove_reaction(
    db: AsyncSession,
    reaction_model: type[ReactionModel],
    key: tuple[int, int],
) -> None:
    reaction = await db.get(reaction_model, key)
    if reaction is None:
        return

    await db.delete(reaction)
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise


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
    movie = await _get_reaction_target_or_404(
        db,
        MovieModel,
        movie_uuid,
        "Movie",
    )
    likes_count, dislikes_count = await _get_reaction_counts(
        db,
        MovieReactionModel,
        MovieReactionModel.movie_id,
        movie.id,
    )

    return MovieReactionSummarySchema(
        movie_uuid=movie.uuid,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
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
    movie = await _get_reaction_target_or_404(
        db,
        MovieModel,
        movie_uuid,
        "Movie",
    )

    reaction = await db.get(
        MovieReactionModel,
        (current_user.id, movie.id),
    )
    likes_count, dislikes_count = await _get_reaction_counts(
        db,
        MovieReactionModel,
        MovieReactionModel.movie_id,
        movie.id,
    )

    return CurrentMovieReactionSchema(
        movie_uuid=movie.uuid,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
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
    movie = await _get_reaction_target_or_404(
        db,
        MovieModel,
        movie_uuid,
        "Movie",
    )
    reaction = await _set_reaction(
        db,
        (current_user.id, movie.id),
        MovieReactionModel(
            user_id=current_user.id,
            movie_id=movie.id,
            reaction_type=data.reaction_type,
        ),
    )
    likes_count, dislikes_count = await _get_reaction_counts(
        db,
        MovieReactionModel,
        MovieReactionModel.movie_id,
        movie.id,
    )

    return CurrentMovieReactionSchema(
        movie_uuid=movie.uuid,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
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
    movie = await _get_reaction_target_or_404(
        db,
        MovieModel,
        movie_uuid,
        "Movie",
    )
    await _remove_reaction(
        db,
        MovieReactionModel,
        (current_user.id, movie.id),
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/comments/{comment_uuid}/reactions/",
    response_model=CommentReactionSummarySchema,
    summary="Get Comment Reaction Summary",
    description="Return public like and dislike counts for a comment.",
    response_description="Comment reaction counts.",
    responses={404: {"description": "Comment was not found."}},
)
async def get_comment_reaction_summary(
    comment_uuid: UUID,
    db: AsyncSession = Depends(get_db),
) -> CommentReactionSummarySchema:
    comment = await _get_reaction_target_or_404(
        db,
        CommentModel,
        comment_uuid,
        "Comment",
    )
    likes_count, dislikes_count = await _get_reaction_counts(
        db,
        CommentReactionModel,
        CommentReactionModel.comment_id,
        comment.id,
    )

    return CommentReactionSummarySchema(
        comment_uuid=comment.uuid,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
    )


@router.get(
    "/comments/{comment_uuid}/reaction/",
    response_model=CurrentCommentReactionSchema,
    summary="Get Current User Comment Reaction",
    description=(
        "Return the current user's reaction and aggregate reaction counts "
        "for a comment."
    ),
    response_description="Current reaction and comment reaction counts.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Comment was not found."},
    },
)
async def get_current_user_comment_reaction(
    comment_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentCommentReactionSchema:
    comment = await _get_reaction_target_or_404(
        db,
        CommentModel,
        comment_uuid,
        "Comment",
    )

    reaction = await db.get(
        CommentReactionModel,
        (current_user.id, comment.id),
    )
    likes_count, dislikes_count = await _get_reaction_counts(
        db,
        CommentReactionModel,
        CommentReactionModel.comment_id,
        comment.id,
    )

    return CurrentCommentReactionSchema(
        comment_uuid=comment.uuid,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
        current_user_reaction=(
            reaction.reaction_type if reaction is not None else None
        ),
    )


@router.put(
    "/comments/{comment_uuid}/reaction/",
    response_model=CurrentCommentReactionSchema,
    summary="Set Current User Comment Reaction",
    description=(
        "Create or replace the current user's reaction to a comment. "
        "Repeating the same request is idempotent."
    ),
    response_description="Updated reaction and comment reaction counts.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Comment was not found."},
    },
)
async def set_current_user_comment_reaction(
    comment_uuid: UUID,
    data: ReactionRequestSchema,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentCommentReactionSchema:
    comment = await _get_reaction_target_or_404(
        db,
        CommentModel,
        comment_uuid,
        "Comment",
    )
    reaction = await _set_reaction(
        db,
        (current_user.id, comment.id),
        CommentReactionModel(
            user_id=current_user.id,
            comment_id=comment.id,
            reaction_type=data.reaction_type,
        ),
    )
    likes_count, dislikes_count = await _get_reaction_counts(
        db,
        CommentReactionModel,
        CommentReactionModel.comment_id,
        comment.id,
    )

    return CurrentCommentReactionSchema(
        comment_uuid=comment.uuid,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
        current_user_reaction=reaction.reaction_type,
    )


@router.delete(
    "/comments/{comment_uuid}/reaction/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Current User Comment Reaction",
    description=(
        "Remove the current user's reaction from a comment. The operation "
        "is idempotent and also succeeds when no reaction exists."
    ),
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Comment was not found."},
    },
)
async def remove_current_user_comment_reaction(
    comment_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    comment = await _get_reaction_target_or_404(
        db,
        CommentModel,
        comment_uuid,
        "Comment",
    )
    await _remove_reaction(
        db,
        CommentReactionModel,
        (current_user.id, comment.id),
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
