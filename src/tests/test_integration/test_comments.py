from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

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
    group: UserGroupEnum = UserGroupEnum.USER,
) -> tuple[UserModel, dict[str, str]]:
    headers = await create_auth_headers(
        db_session,
        jwt_manager,
        group,
        email,
    )
    user = await db_session.scalar(
        select(UserModel).where(UserModel.email == email)
    )
    assert user is not None
    return user, headers


@pytest.mark.asyncio
async def test_user_can_create_and_public_can_read_movie_comment(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "comment-api-user@example.com",
    )
    movie = build_movie("Public Comments Movie")
    db_session.add(movie)
    await db_session.commit()

    empty_response = await client.get(
        f"/theater/movies/{movie.uuid}/comments/"
    )
    anonymous_create_response = await client.post(
        f"/theater/movies/{movie.uuid}/comments/",
        json={"content": "Anonymous comment."},
    )
    assert empty_response.status_code == 200
    assert empty_response.json()["comments"] == []
    assert anonymous_create_response.status_code == 401

    create_response = await client.post(
        f"/theater/movies/{movie.uuid}/comments/",
        json={"content": "  A useful movie comment.  "},
        headers=headers,
    )

    assert create_response.status_code == 201
    created_comment = create_response.json()
    comment_uuid = created_comment["uuid"]
    assert created_comment["content"] == "A useful movie comment."
    assert created_comment["movie_uuid"] == str(movie.uuid)
    assert created_comment["parent_uuid"] is None
    assert created_comment["replies_count"] == 0
    assert created_comment["author"] == {
        "id": user.id,
        "first_name": None,
        "last_name": None,
        "avatar": None,
    }
    assert "email" not in created_comment["author"]

    detail_response = await client.get(
        f"/theater/comments/{comment_uuid}/"
    )
    list_response = await client.get(
        f"/theater/movies/{movie.uuid}/comments/"
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["uuid"] == comment_uuid
    assert list_response.status_code == 200
    assert list_response.json()["total_items"] == 1
    assert list_response.json()["comments"][0]["uuid"] == comment_uuid


@pytest.mark.asyncio
async def test_comment_replies_are_in_movie_list_and_grouped_by_parent(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, first_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "root-comment-author@example.com",
    )
    _, second_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "reply-comment-author@example.com",
    )
    movie = build_movie("Nested Comments Movie")
    db_session.add(movie)
    await db_session.commit()

    root_response = await client.post(
        f"/theater/movies/{movie.uuid}/comments/",
        json={"content": "Root comment."},
        headers=first_headers,
    )
    root_uuid = root_response.json()["uuid"]
    reply_response = await client.post(
        f"/theater/comments/{root_uuid}/replies/",
        json={"content": "Direct reply."},
        headers=second_headers,
    )
    reply_uuid = reply_response.json()["uuid"]
    nested_response = await client.post(
        f"/theater/comments/{reply_uuid}/replies/",
        json={"content": "Nested reply."},
        headers=first_headers,
    )
    nested_uuid = nested_response.json()["uuid"]

    assert root_response.status_code == 201
    assert reply_response.status_code == 201
    assert nested_response.status_code == 201
    assert reply_response.json()["parent_uuid"] == root_uuid
    assert nested_response.json()["parent_uuid"] == reply_uuid
    assert reply_response.json()["movie_uuid"] == str(movie.uuid)

    root_replies_response = await client.get(
        f"/theater/comments/{root_uuid}/replies/",
        params={"sort_order": "asc"},
    )
    nested_replies_response = await client.get(
        f"/theater/comments/{reply_uuid}/replies/",
        params={"sort_order": "asc"},
    )
    movie_comments_response = await client.get(
        f"/theater/movies/{movie.uuid}/comments/",
        params={"sort_order": "asc"},
    )
    root_detail_response = await client.get(
        f"/theater/comments/{root_uuid}/"
    )

    assert [
        comment["uuid"]
        for comment in root_replies_response.json()["comments"]
    ] == [reply_uuid]
    assert [
        comment["uuid"]
        for comment in nested_replies_response.json()["comments"]
    ] == [nested_uuid]
    movie_comments = movie_comments_response.json()["comments"]
    assert movie_comments_response.json()["total_items"] == 3
    assert [comment["uuid"] for comment in movie_comments] == [
        root_uuid,
        reply_uuid,
        nested_uuid,
    ]
    assert [comment["parent_uuid"] for comment in movie_comments] == [
        None,
        root_uuid,
        reply_uuid,
    ]
    assert root_detail_response.json()["replies_count"] == 1


@pytest.mark.asyncio
async def test_comment_list_supports_sorting_and_pagination(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "paginated-comments@example.com",
    )
    movie = build_movie("Paginated Comments Movie")
    db_session.add(movie)
    await db_session.commit()

    for content in ("First comment.", "Second comment.", "Third comment."):
        response = await client.post(
            f"/theater/movies/{movie.uuid}/comments/",
            json={"content": content},
            headers=headers,
        )
        assert response.status_code == 201

    first_page_response = await client.get(
        f"/theater/movies/{movie.uuid}/comments/",
        params={
            "page": 1,
            "per_page": 2,
            "sort_order": "asc",
        },
    )
    first_page = first_page_response.json()

    assert first_page_response.status_code == 200
    assert [comment["content"] for comment in first_page["comments"]] == [
        "First comment.",
        "Second comment.",
    ]
    assert first_page["total_items"] == 3
    assert first_page["total_pages"] == 2
    assert first_page["prev_page"] is None
    assert parse_qs(urlparse(first_page["next_page"]).query) == {
        "page": ["2"],
        "per_page": ["2"],
        "sort_order": ["asc"],
    }

    second_page_response = await client.get(first_page["next_page"])
    assert [
        comment["content"]
        for comment in second_page_response.json()["comments"]
    ] == ["Third comment."]


@pytest.mark.asyncio
async def test_comment_update_and_delete_permissions(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, owner_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "owned-comment@example.com",
    )
    _, other_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "other-comment-user@example.com",
    )
    _, moderator_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "comment-moderator@example.com",
        UserGroupEnum.MODERATOR,
    )
    movie = build_movie("Moderated Comments Movie")
    db_session.add(movie)
    await db_session.commit()

    root_response = await client.post(
        f"/theater/movies/{movie.uuid}/comments/",
        json={"content": "Original content."},
        headers=owner_headers,
    )
    root_uuid = root_response.json()["uuid"]
    reply_response = await client.post(
        f"/theater/comments/{root_uuid}/replies/",
        json={"content": "Reply that should be deleted."},
        headers=other_headers,
    )
    reply_uuid = reply_response.json()["uuid"]

    forbidden_update_response = await client.patch(
        f"/theater/comments/{root_uuid}/",
        json={"content": "Unauthorized update."},
        headers=other_headers,
    )
    forbidden_delete_response = await client.delete(
        f"/theater/comments/{root_uuid}/",
        headers=other_headers,
    )
    owner_update_response = await client.patch(
        f"/theater/comments/{root_uuid}/",
        json={"content": "  Updated by the author.  "},
        headers=owner_headers,
    )

    assert forbidden_update_response.status_code == 403
    assert forbidden_delete_response.status_code == 403
    assert owner_update_response.status_code == 200
    assert owner_update_response.json()["content"] == "Updated by the author."

    moderator_delete_response = await client.delete(
        f"/theater/comments/{root_uuid}/",
        headers=moderator_headers,
    )
    assert moderator_delete_response.status_code == 204
    assert (await client.get(f"/theater/comments/{root_uuid}/")).status_code == 404
    assert (await client.get(f"/theater/comments/{reply_uuid}/")).status_code == 404


@pytest.mark.asyncio
async def test_comment_api_validates_content_and_unknown_resources(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "validated-comments@example.com",
    )
    movie = build_movie("Validated Comments Movie")
    db_session.add(movie)
    await db_session.commit()

    blank_response = await client.post(
        f"/theater/movies/{movie.uuid}/comments/",
        json={"content": "   "},
        headers=headers,
    )
    extra_field_response = await client.post(
        f"/theater/movies/{movie.uuid}/comments/",
        json={"content": "Valid content.", "unexpected": True},
        headers=headers,
    )
    unknown_movie_response = await client.post(
        f"/theater/movies/{uuid4()}/comments/",
        json={"content": "Valid content."},
        headers=headers,
    )
    unknown_comment_response = await client.get(
        f"/theater/comments/{uuid4()}/"
    )

    assert blank_response.status_code == 422
    assert extra_field_response.status_code == 422
    assert unknown_movie_response.status_code == 404
    assert unknown_comment_response.status_code == 404
