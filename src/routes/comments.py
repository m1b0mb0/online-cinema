import math
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload

from src.config import BaseAppSettings, get_email_notificator, get_settings
from src.database import CommentModel, MovieModel, UserModel, get_db
from src.notifications import EmailSenderInterface
from src.schemas import (
    CommentAuthorSchema,
    CommentCreateSchema,
    CommentListParams,
    CommentListResponseSchema,
    CommentSchema,
    CommentSortOrder,
    CommentUpdateSchema,
)
from src.security.dependencies import (
    ALLOWED_GROUPS,
    get_current_active_user,
)
from src.services import get_movie_by_uuid_or_404

router = APIRouter()

AUTH_RESPONSES = {
    401: {"description": "Access token is missing or invalid."},
    403: {"description": "User account is not activated or access is denied."},
}


def _serialize_comment(
    comment: CommentModel,
    replies_count: int,
) -> CommentSchema:
    profile = comment.user.profile
    return CommentSchema(
        uuid=comment.uuid,
        movie_uuid=comment.movie.uuid,
        parent_uuid=(comment.parent.uuid if comment.parent is not None else None),
        content=comment.content,
        author=CommentAuthorSchema(
            id=comment.user.id,
            first_name=(profile.first_name if profile is not None else None),
            last_name=(profile.last_name if profile is not None else None),
            avatar=(profile.avatar if profile is not None else None),
        ),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        replies_count=replies_count,
    )


async def _get_comment_or_404(
    db: AsyncSession,
    comment_uuid: UUID,
) -> tuple[CommentModel, int]:
    reply = aliased(CommentModel)
    replies_count = (
        select(func.count(reply.id))
        .where(reply.parent_id == CommentModel.id)
        .correlate(CommentModel)
        .scalar_subquery()
        .label("replies_count")
    )
    row = (
        await db.execute(
            select(CommentModel, replies_count)
            .options(
                joinedload(CommentModel.user).joinedload(UserModel.profile),
                joinedload(CommentModel.movie),
                joinedload(CommentModel.parent),
            )
            .where(CommentModel.uuid == comment_uuid)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment with the given UUID was not found.",
        )
    return row[0], int(row.replies_count or 0)


@router.get(
    "/movies/{movie_uuid}/comments/",
    response_model=CommentListResponseSchema,
    summary="List Movie Comments",
    description=(
        "Return all paginated comments for a movie, including replies. "
        "Replies contain the UUID of their parent comment."
    ),
    response_description="Paginated movie comments and replies.",
    responses={404: {"description": "Movie was not found."}},
)
async def get_movie_comments(
    movie_uuid: UUID,
    request: Request,
    params: Annotated[CommentListParams, Query()],
    db: AsyncSession = Depends(get_db),
) -> CommentListResponseSchema:
    movie = await get_movie_by_uuid_or_404(db, movie_uuid)

    condition = CommentModel.movie_id == movie.id
    total_items = await db.scalar(
        select(func.count(CommentModel.id)).where(condition)
    ) or 0

    order_columns = (CommentModel.created_at, CommentModel.id)
    if params.sort_order == CommentSortOrder.ASC:
        order_by = [column.asc() for column in order_columns]
    else:
        order_by = [column.desc() for column in order_columns]

    reply = aliased(CommentModel)
    replies_count = (
        select(func.count(reply.id))
        .where(reply.parent_id == CommentModel.id)
        .correlate(CommentModel)
        .scalar_subquery()
        .label("replies_count")
    )
    statement = (
        select(CommentModel, replies_count)
        .options(
            joinedload(CommentModel.user).joinedload(UserModel.profile),
            joinedload(CommentModel.movie),
            joinedload(CommentModel.parent),
        )
        .where(condition)
        .order_by(*order_by)
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    rows = (await db.execute(statement)).all()
    comments = [
        _serialize_comment(row[0], int(row.replies_count or 0))
        for row in rows
    ]

    total_pages = math.ceil(total_items / params.per_page)
    prev_page = (
        str(
            request.url.include_query_params(
                page=params.page - 1,
                per_page=params.per_page,
            )
        )
        if params.page > 1
        else None
    )
    next_page = (
        str(
            request.url.include_query_params(
                page=params.page + 1,
                per_page=params.per_page,
            )
        )
        if params.page < total_pages
        else None
    )
    return CommentListResponseSchema(
        comments=comments,
        prev_page=prev_page,
        next_page=next_page,
        page=params.page,
        per_page=params.per_page,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.post(
    "/movies/{movie_uuid}/comments/",
    response_model=CommentSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Movie Comment",
    description="Create a top-level comment for a movie.",
    response_description="Created movie comment.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
    },
)
async def create_movie_comment(
    movie_uuid: UUID,
    data: CommentCreateSchema,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommentSchema:
    movie = await get_movie_by_uuid_or_404(db, movie_uuid)

    comment = CommentModel(
        content=data.content,
        user_id=current_user.id,
        movie_id=movie.id,
    )
    db.add(comment)
    try:
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving the comment.",
        ) from error

    saved_comment, replies_count = await _get_comment_or_404(db, comment.uuid)
    return _serialize_comment(saved_comment, replies_count)


@router.get(
    "/comments/{comment_uuid}/",
    response_model=CommentSchema,
    summary="Get Comment",
    description="Return a single comment by its UUID.",
    response_description="Comment details.",
    responses={404: {"description": "Comment was not found."}},
)
async def get_comment(
    comment_uuid: UUID,
    db: AsyncSession = Depends(get_db),
) -> CommentSchema:
    comment, replies_count = await _get_comment_or_404(db, comment_uuid)
    return _serialize_comment(comment, replies_count)


@router.get(
    "/comments/{comment_uuid}/replies/",
    response_model=CommentListResponseSchema,
    summary="List Comment Replies",
    description="Return paginated direct replies to a comment.",
    response_description="Paginated direct comment replies.",
    responses={404: {"description": "Parent comment was not found."}},
)
async def get_comment_replies(
    comment_uuid: UUID,
    request: Request,
    params: Annotated[CommentListParams, Query()],
    db: AsyncSession = Depends(get_db),
) -> CommentListResponseSchema:
    parent, _ = await _get_comment_or_404(db, comment_uuid)
    condition = CommentModel.parent_id == parent.id
    total_items = await db.scalar(
        select(func.count(CommentModel.id)).where(condition)
    ) or 0

    order_columns = (CommentModel.created_at, CommentModel.id)
    if params.sort_order == CommentSortOrder.ASC:
        order_by = [column.asc() for column in order_columns]
    else:
        order_by = [column.desc() for column in order_columns]

    reply = aliased(CommentModel)
    replies_count = (
        select(func.count(reply.id))
        .where(reply.parent_id == CommentModel.id)
        .correlate(CommentModel)
        .scalar_subquery()
        .label("replies_count")
    )
    statement = (
        select(CommentModel, replies_count)
        .options(
            joinedload(CommentModel.user).joinedload(UserModel.profile),
            joinedload(CommentModel.movie),
            joinedload(CommentModel.parent),
        )
        .where(condition)
        .order_by(*order_by)
        .offset((params.page - 1) * params.per_page)
        .limit(params.per_page)
    )
    rows = (await db.execute(statement)).all()
    comments = [
        _serialize_comment(row[0], int(row.replies_count or 0))
        for row in rows
    ]

    total_pages = math.ceil(total_items / params.per_page)
    prev_page = (
        str(
            request.url.include_query_params(
                page=params.page - 1,
                per_page=params.per_page,
            )
        )
        if params.page > 1
        else None
    )
    next_page = (
        str(
            request.url.include_query_params(
                page=params.page + 1,
                per_page=params.per_page,
            )
        )
        if params.page < total_pages
        else None
    )
    return CommentListResponseSchema(
        comments=comments,
        prev_page=prev_page,
        next_page=next_page,
        page=params.page,
        per_page=params.per_page,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.post(
    "/comments/{comment_uuid}/replies/",
    response_model=CommentSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Reply To Comment",
    description="Create a direct reply to a comment.",
    response_description="Created comment reply.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Parent comment was not found."},
    },
)
async def reply_to_comment(
    comment_uuid: UUID,
    data: CommentCreateSchema,
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    settings: BaseAppSettings = Depends(get_settings),
    email_sender: EmailSenderInterface = Depends(get_email_notificator),
) -> CommentSchema:
    parent, _ = await _get_comment_or_404(db, comment_uuid)
    reply = CommentModel(
        content=data.content,
        user_id=current_user.id,
        movie_id=parent.movie_id,
        parent_id=parent.id,
    )
    db.add(reply)
    try:
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving the comment.",
        ) from error

    if parent.user_id != current_user.id:
        comment_link = (
            f"{settings.APP_BASE_URL}/theater/comments/{reply.uuid}/"
        )
        background_tasks.add_task(
            email_sender.send_comment_reply_email,
            str(parent.user.email),
            comment_link,
        )

    saved_reply, replies_count = await _get_comment_or_404(db, reply.uuid)
    return _serialize_comment(saved_reply, replies_count)


@router.patch(
    "/comments/{comment_uuid}/",
    response_model=CommentSchema,
    summary="Update Comment",
    description="Update the content of the current user's comment.",
    response_description="Updated comment.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Comment was not found."},
    },
)
async def update_comment(
    comment_uuid: UUID,
    data: CommentUpdateSchema,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommentSchema:
    comment, _ = await _get_comment_or_404(db, comment_uuid)
    if comment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own comments.",
        )

    comment.content = data.content
    try:
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving the comment.",
        ) from error

    saved_comment, replies_count = await _get_comment_or_404(db, comment.uuid)
    return _serialize_comment(saved_comment, replies_count)


@router.delete(
    "/comments/{comment_uuid}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Comment",
    description=(
        "Delete a comment and its reply branch. Authors, moderators, and "
        "administrators may perform this action."
    ),
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Comment was not found."},
    },
)
async def delete_comment(
    comment_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    comment, _ = await _get_comment_or_404(db, comment_uuid)
    can_moderate = current_user.group.name in ALLOWED_GROUPS
    if comment.user_id != current_user.id and not can_moderate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this comment.",
        )

    await db.delete(comment)
    try:
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the comment.",
        ) from error

    return Response(status_code=status.HTTP_204_NO_CONTENT)
