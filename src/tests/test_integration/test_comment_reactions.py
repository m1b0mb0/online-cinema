from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.database import (
    CertificationModel,
    CommentModel,
    CommentReactionModel,
    MovieModel,
    ReactionTypeEnum,
    UserGroupEnum,
    UserModel,
)
from src.tests.helpers import create_auth_headers

pytestmark = pytest.mark.integration


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


async def create_user_with_headers(
    db_session,
    jwt_manager,
    email: str,
) -> tuple[UserModel, dict[str, str]]:
    headers = await create_auth_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        email,
    )
    user = await db_session.scalar(
        select(UserModel).where(UserModel.email == email)
    )
    assert user is not None
    return user, headers


@pytest.mark.asyncio
async def test_comment_reaction_can_be_created_repeated_switched_and_removed(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "comment-reaction-user@example.com",
    )
    movie = build_movie("Comment Reaction Movie")
    comment = CommentModel(
        content="A comment with a reaction.",
        user=user,
        movie=movie,
    )
    db_session.add(comment)
    await db_session.commit()

    empty_response = await client.get(
        f"/theater/comments/{comment.uuid}/reaction/",
        headers=headers,
    )
    assert empty_response.status_code == 200
    assert empty_response.json() == {
        "comment_uuid": str(comment.uuid),
        "likes_count": 0,
        "dislikes_count": 0,
        "current_user_reaction": None,
    }

    like_response = await client.put(
        f"/theater/comments/{comment.uuid}/reaction/",
        json={"reaction_type": "like"},
        headers=headers,
    )
    assert like_response.status_code == 200
    assert like_response.json()["current_user_reaction"] == "like"
    assert like_response.json()["likes_count"] == 1
    assert like_response.json()["dislikes_count"] == 0

    reaction = await db_session.get(
        CommentReactionModel,
        (user.id, comment.id),
    )
    assert reaction is not None
    assert reaction.reaction_type == ReactionTypeEnum.LIKE
    assert reaction.created_at is not None
    assert reaction.updated_at is not None

    repeated_response = await client.put(
        f"/theater/comments/{comment.uuid}/reaction/",
        json={"reaction_type": "like"},
        headers=headers,
    )
    reaction_count = await db_session.scalar(
        select(func.count())
        .select_from(CommentReactionModel)
        .where(
            CommentReactionModel.user_id == user.id,
            CommentReactionModel.comment_id == comment.id,
        )
    )
    assert repeated_response.status_code == 200
    assert reaction_count == 1

    dislike_response = await client.put(
        f"/theater/comments/{comment.uuid}/reaction/",
        json={"reaction_type": "dislike"},
        headers=headers,
    )
    assert dislike_response.status_code == 200
    assert dislike_response.json()["current_user_reaction"] == "dislike"
    assert dislike_response.json()["likes_count"] == 0
    assert dislike_response.json()["dislikes_count"] == 1

    user_id = user.id
    comment_id = comment.id
    comment_uuid = comment.uuid
    db_session.expire_all()
    switched_reaction = await db_session.get(
        CommentReactionModel,
        (user_id, comment_id),
    )
    assert switched_reaction is not None
    assert switched_reaction.reaction_type == ReactionTypeEnum.DISLIKE

    delete_response = await client.delete(
        f"/theater/comments/{comment_uuid}/reaction/",
        headers=headers,
    )
    repeated_delete_response = await client.delete(
        f"/theater/comments/{comment_uuid}/reaction/",
        headers=headers,
    )
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert repeated_delete_response.status_code == 204

    summary_response = await client.get(
        f"/theater/comments/{comment_uuid}/reactions/"
    )
    assert summary_response.status_code == 200
    assert summary_response.json() == {
        "comment_uuid": str(comment_uuid),
        "likes_count": 0,
        "dislikes_count": 0,
    }


@pytest.mark.asyncio
async def test_comment_reaction_counts_and_current_reaction_are_separate(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    first_user, first_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "first-comment-reaction@example.com",
    )
    _, second_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "second-comment-reaction@example.com",
    )
    movie = build_movie("Aggregated Comment Reactions")
    comment = CommentModel(
        content="A comment reacted to by two users.",
        user=first_user,
        movie=movie,
    )
    db_session.add(comment)
    await db_session.commit()

    first_response = await client.put(
        f"/theater/comments/{comment.uuid}/reaction/",
        json={"reaction_type": "like"},
        headers=first_headers,
    )
    second_response = await client.put(
        f"/theater/comments/{comment.uuid}/reaction/",
        json={"reaction_type": "dislike"},
        headers=second_headers,
    )
    assert first_response.status_code == 200
    assert second_response.status_code == 200

    public_summary = await client.get(
        f"/theater/comments/{comment.uuid}/reactions/"
    )
    first_user_state = await client.get(
        f"/theater/comments/{comment.uuid}/reaction/",
        headers=first_headers,
    )
    second_user_state = await client.get(
        f"/theater/comments/{comment.uuid}/reaction/",
        headers=second_headers,
    )

    assert public_summary.status_code == 200
    assert public_summary.json() == {
        "comment_uuid": str(comment.uuid),
        "likes_count": 1,
        "dislikes_count": 1,
    }
    assert first_user_state.json()["current_user_reaction"] == "like"
    assert second_user_state.json()["current_user_reaction"] == "dislike"


@pytest.mark.asyncio
async def test_comment_reaction_mutations_require_authentication(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        "protected-comment-reaction@example.com",
    )
    movie = build_movie("Protected Comment Reactions")
    comment = CommentModel(
        content="A protected reaction target.",
        user=user,
        movie=movie,
    )
    db_session.add(comment)
    await db_session.commit()

    responses = [
        await client.get(f"/theater/comments/{comment.uuid}/reaction/"),
        await client.put(
            f"/theater/comments/{comment.uuid}/reaction/",
            json={"reaction_type": "like"},
        ),
        await client.delete(
            f"/theater/comments/{comment.uuid}/reaction/"
        ),
    ]

    assert all(response.status_code == 401 for response in responses)
    public_response = await client.get(
        f"/theater/comments/{comment.uuid}/reactions/"
    )
    assert public_response.status_code == 200


@pytest.mark.asyncio
async def test_comment_reaction_api_validates_input_and_unknown_comments(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "validated-comment-reaction@example.com",
    )
    movie = build_movie("Validated Comment Reactions")
    comment = CommentModel(
        content="A validated reaction target.",
        user=user,
        movie=movie,
    )
    db_session.add(comment)
    await db_session.commit()

    invalid_type_response = await client.put(
        f"/theater/comments/{comment.uuid}/reaction/",
        json={"reaction_type": "love"},
        headers=headers,
    )
    extra_field_response = await client.put(
        f"/theater/comments/{comment.uuid}/reaction/",
        json={"reaction_type": "like", "unexpected": True},
        headers=headers,
    )
    unknown_uuid = uuid4()
    unknown_summary_response = await client.get(
        f"/theater/comments/{unknown_uuid}/reactions/"
    )
    unknown_set_response = await client.put(
        f"/theater/comments/{unknown_uuid}/reaction/",
        json={"reaction_type": "like"},
        headers=headers,
    )

    assert invalid_type_response.status_code == 422
    assert extra_field_response.status_code == 422
    assert unknown_summary_response.status_code == 404
    assert unknown_set_response.status_code == 404
