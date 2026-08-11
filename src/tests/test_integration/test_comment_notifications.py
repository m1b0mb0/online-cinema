from decimal import Decimal

import pytest
from sqlalchemy import select

from src.database import (
    CertificationModel,
    MovieModel,
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
    user = await db_session.scalar(select(UserModel).where(UserModel.email == email))
    assert user is not None
    return user, headers


@pytest.mark.asyncio
async def test_comment_author_is_notified_about_reply_from_another_user(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
    email_sender_stub,
):
    author, author_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "reply-notification-author@example.com",
    )
    _, replier_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "reply-notification-user@example.com",
    )
    movie = build_movie("Reply Notification Movie")
    db_session.add(movie)
    await db_session.commit()

    comment_response = await client.post(
        f"/theater/movies/{movie.uuid}/comments/",
        json={"content": "A comment waiting for replies."},
        headers=author_headers,
    )
    comment_uuid = comment_response.json()["uuid"]

    reply_response = await client.post(
        f"/theater/comments/{comment_uuid}/replies/",
        json={"content": "A reply from another user."},
        headers=replier_headers,
    )

    assert reply_response.status_code == 201
    reply_uuid = reply_response.json()["uuid"]
    assert email_sender_stub.comment_reply_emails == [
        {
            "email": author.email,
            "comment_link": (f"http://127.0.0.1:8000/theater/comments/{reply_uuid}/"),
        }
    ]
    linked_reply_response = await client.get(
        email_sender_stub.comment_reply_emails[0]["comment_link"]
    )
    assert linked_reply_response.status_code == 200
    assert linked_reply_response.json()["uuid"] == reply_uuid

    own_reply_response = await client.post(
        f"/theater/comments/{comment_uuid}/replies/",
        json={"content": "The author adds another thought."},
        headers=author_headers,
    )

    assert own_reply_response.status_code == 201
    assert len(email_sender_stub.comment_reply_emails) == 1


@pytest.mark.asyncio
async def test_comment_author_is_notified_only_when_comment_receives_like(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
    email_sender_stub,
):
    author, author_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "like-notification-author@example.com",
    )
    _, reactor_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "like-notification-user@example.com",
    )
    movie = build_movie("Like Notification Movie")
    db_session.add(movie)
    await db_session.commit()

    comment_response = await client.post(
        f"/theater/movies/{movie.uuid}/comments/",
        json={"content": "A comment waiting for reactions."},
        headers=author_headers,
    )
    comment_uuid = comment_response.json()["uuid"]
    reaction_url = f"/theater/comments/{comment_uuid}/reaction/"

    dislike_response = await client.put(
        reaction_url,
        json={"reaction_type": "dislike"},
        headers=reactor_headers,
    )
    like_response = await client.put(
        reaction_url,
        json={"reaction_type": "like"},
        headers=reactor_headers,
    )
    repeated_like_response = await client.put(
        reaction_url,
        json={"reaction_type": "like"},
        headers=reactor_headers,
    )

    assert dislike_response.status_code == 200
    assert like_response.status_code == 200
    assert repeated_like_response.status_code == 200
    assert email_sender_stub.comment_like_emails == [
        {
            "email": author.email,
            "comment_link": (f"http://127.0.0.1:8000/theater/comments/{comment_uuid}/"),
        }
    ]

    await client.put(
        reaction_url,
        json={"reaction_type": "dislike"},
        headers=reactor_headers,
    )
    await client.put(
        reaction_url,
        json={"reaction_type": "like"},
        headers=reactor_headers,
    )
    own_like_response = await client.put(
        reaction_url,
        json={"reaction_type": "like"},
        headers=author_headers,
    )

    assert own_like_response.status_code == 200
    assert len(email_sender_stub.comment_like_emails) == 2
