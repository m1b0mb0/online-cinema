from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.database import (
    CertificationModel,
    CommentModel,
    CommentReactionModel,
    MovieModel,
    ReactionTypeEnum,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)

pytestmark = pytest.mark.integration


async def create_user(db_session, email: str) -> UserModel:
    group = await db_session.scalar(
        select(UserGroupModel).where(
            UserGroupModel.name == UserGroupEnum.USER
        )
    )
    assert group is not None

    user = UserModel(
        email=email,
        _hashed_password="not-used-in-comment-model-tests",
        is_active=True,
        group_id=group.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def build_movie(name: str) -> MovieModel:
    return MovieModel(
        name=name,
        year=2024,
        time=120,
        imdb=8.0,
        votes=1000,
        description=f"{name} description.",
        price=Decimal("12.99"),
        certification=CertificationModel(name="PG-13"),
    )


@pytest.mark.asyncio
async def test_comment_models_support_replies_and_reactions(
    db_session,
    seed_user_groups,
):
    author = await create_user(db_session, "comment-author@example.com")
    reader = await create_user(db_session, "comment-reader@example.com")
    movie = build_movie("Commented Movie")
    root_comment = CommentModel(
        content="A root comment.",
        user=author,
        movie=movie,
    )
    reply = CommentModel(
        content="A reply to the root comment.",
        user=reader,
        movie=movie,
        parent=root_comment,
    )
    author_reaction = CommentReactionModel(
        user=author,
        comment=root_comment,
        reaction_type=ReactionTypeEnum.LIKE,
    )
    reader_reaction = CommentReactionModel(
        user=reader,
        comment=root_comment,
        reaction_type=ReactionTypeEnum.LIKE,
    )
    db_session.add_all(
        [root_comment, reply, author_reaction, reader_reaction]
    )
    await db_session.commit()

    loaded_comment = await db_session.scalar(
        select(CommentModel)
        .where(CommentModel.id == root_comment.id)
        .options(
            selectinload(CommentModel.replies),
            selectinload(CommentModel.reactions),
        )
    )

    assert loaded_comment is not None
    assert loaded_comment.uuid is not None
    assert loaded_comment.created_at is not None
    assert loaded_comment.updated_at is not None
    assert [item.content for item in loaded_comment.replies] == [
        "A reply to the root comment."
    ]
    assert loaded_comment.replies[0].parent_id == loaded_comment.id
    assert len(loaded_comment.reactions) == 2
    assert all(
        reaction.reaction_type == ReactionTypeEnum.LIKE
        for reaction in loaded_comment.reactions
    )

    author_reaction.reaction_type = ReactionTypeEnum.DISLIKE
    await db_session.commit()

    reaction_count = await db_session.scalar(
        select(func.count())
        .select_from(CommentReactionModel)
        .where(CommentReactionModel.comment_id == root_comment.id)
    )
    assert reaction_count == 2
    assert author_reaction.reaction_type == ReactionTypeEnum.DISLIKE


@pytest.mark.asyncio
async def test_comment_content_cannot_be_blank(
    db_session,
    seed_user_groups,
):
    author = await create_user(db_session, "blank-comment@example.com")
    movie = build_movie("Blank Comment Movie")
    db_session.add(movie)
    await db_session.flush()
    db_session.add(
        CommentModel(
            content="   ",
            user_id=author.id,
            movie_id=movie.id,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_deleting_parent_comment_removes_reply_branch_and_reactions(
    db_session,
    seed_user_groups,
):
    author = await create_user(db_session, "deleted-comment@example.com")
    movie = build_movie("Deleted Comment Movie")
    root_comment = CommentModel(
        content="Root comment.",
        user=author,
        movie=movie,
    )
    reply = CommentModel(
        content="Nested reply.",
        user=author,
        movie=movie,
        parent=root_comment,
    )
    reaction = CommentReactionModel(
        user=author,
        comment=reply,
        reaction_type=ReactionTypeEnum.LIKE,
    )
    db_session.add_all([root_comment, reply, reaction])
    await db_session.commit()

    await db_session.delete(root_comment)
    await db_session.commit()

    comments_count = await db_session.scalar(
        select(func.count()).select_from(CommentModel)
    )
    reactions_count = await db_session.scalar(
        select(func.count()).select_from(CommentReactionModel)
    )
    assert comments_count == 0
    assert reactions_count == 0
