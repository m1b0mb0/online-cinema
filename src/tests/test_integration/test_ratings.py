from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.database import (
    CertificationModel,
    MovieModel,
    MovieRatingModel,
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
async def test_rating_model_enforces_score_range(
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        "invalid-rating-model@example.com",
    )
    movie = build_movie("Invalid Rating Model Movie")
    db_session.add(movie)
    await db_session.flush()
    db_session.add(
        MovieRatingModel(
            user_id=user.id,
            movie_id=movie.id,
            score=0,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_movie_rating_can_be_created_updated_and_removed(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "rating-user@example.com",
    )
    movie = build_movie("Rated Movie")
    db_session.add(movie)
    await db_session.commit()

    public_empty_response = await client.get(f"/theater/movies/{movie.uuid}/ratings/")
    current_empty_response = await client.get(
        f"/theater/movies/{movie.uuid}/rating/",
        headers=headers,
    )
    assert public_empty_response.status_code == 200
    assert public_empty_response.json() == {
        "movie_uuid": str(movie.uuid),
        "average_rating": None,
        "ratings_count": 0,
    }
    assert current_empty_response.json()["current_user_rating"] is None

    create_response = await client.put(
        f"/theater/movies/{movie.uuid}/rating/",
        json={"score": 8},
        headers=headers,
    )
    assert create_response.status_code == 200
    assert create_response.json() == {
        "movie_uuid": str(movie.uuid),
        "average_rating": 8.0,
        "ratings_count": 1,
        "current_user_rating": 8,
    }

    rating = await db_session.get(
        MovieRatingModel,
        (user.id, movie.id),
    )
    assert rating is not None
    assert rating.score == 8
    assert rating.created_at is not None
    assert rating.updated_at is not None

    repeated_response = await client.put(
        f"/theater/movies/{movie.uuid}/rating/",
        json={"score": 8},
        headers=headers,
    )
    rating_count = await db_session.scalar(
        select(func.count())
        .select_from(MovieRatingModel)
        .where(
            MovieRatingModel.user_id == user.id,
            MovieRatingModel.movie_id == movie.id,
        )
    )
    assert repeated_response.status_code == 200
    assert rating_count == 1

    update_response = await client.put(
        f"/theater/movies/{movie.uuid}/rating/",
        json={"score": 6},
        headers=headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["average_rating"] == 6.0
    assert update_response.json()["current_user_rating"] == 6

    user_id = user.id
    movie_id = movie.id
    movie_uuid = movie.uuid
    db_session.expire_all()
    updated_rating = await db_session.get(
        MovieRatingModel,
        (user_id, movie_id),
    )
    assert updated_rating is not None
    assert updated_rating.score == 6

    delete_response = await client.delete(
        f"/theater/movies/{movie_uuid}/rating/",
        headers=headers,
    )
    repeated_delete_response = await client.delete(
        f"/theater/movies/{movie_uuid}/rating/",
        headers=headers,
    )
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert repeated_delete_response.status_code == 204

    public_summary = await client.get(f"/theater/movies/{movie_uuid}/ratings/")
    assert public_summary.json()["average_rating"] is None
    assert public_summary.json()["ratings_count"] == 0


@pytest.mark.asyncio
async def test_movie_ratings_are_aggregated_and_current_rating_is_private(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, first_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "first-rating-user@example.com",
    )
    _, second_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "second-rating-user@example.com",
    )
    movie = build_movie("Aggregated Ratings Movie")
    db_session.add(movie)
    await db_session.commit()

    first_response = await client.put(
        f"/theater/movies/{movie.uuid}/rating/",
        json={"score": 8},
        headers=first_headers,
    )
    second_response = await client.put(
        f"/theater/movies/{movie.uuid}/rating/",
        json={"score": 9},
        headers=second_headers,
    )
    assert first_response.status_code == 200
    assert second_response.status_code == 200

    public_summary = await client.get(f"/theater/movies/{movie.uuid}/ratings/")
    first_user_state = await client.get(
        f"/theater/movies/{movie.uuid}/rating/",
        headers=first_headers,
    )
    second_user_state = await client.get(
        f"/theater/movies/{movie.uuid}/rating/",
        headers=second_headers,
    )

    assert public_summary.json() == {
        "movie_uuid": str(movie.uuid),
        "average_rating": 8.5,
        "ratings_count": 2,
    }
    assert "current_user_rating" not in public_summary.json()
    assert first_user_state.json()["current_user_rating"] == 8
    assert second_user_state.json()["current_user_rating"] == 9

    update_response = await client.put(
        f"/theater/movies/{movie.uuid}/rating/",
        json={"score": 10},
        headers=first_headers,
    )
    assert update_response.json()["average_rating"] == 9.5
    assert update_response.json()["ratings_count"] == 2


@pytest.mark.asyncio
async def test_rating_mutations_require_authentication(
    client,
    db_session,
):
    movie = build_movie("Protected Ratings Movie")
    db_session.add(movie)
    await db_session.commit()

    responses = [
        await client.get(f"/theater/movies/{movie.uuid}/rating/"),
        await client.put(
            f"/theater/movies/{movie.uuid}/rating/",
            json={"score": 8},
        ),
        await client.delete(f"/theater/movies/{movie.uuid}/rating/"),
    ]

    assert all(response.status_code == 401 for response in responses)
    public_response = await client.get(f"/theater/movies/{movie.uuid}/ratings/")
    assert public_response.status_code == 200


@pytest.mark.asyncio
async def test_rating_api_validates_input_and_unknown_movies(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    _, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "validated-rating-user@example.com",
    )
    movie = build_movie("Validated Ratings Movie")
    db_session.add(movie)
    await db_session.commit()

    invalid_responses = [
        await client.put(
            f"/theater/movies/{movie.uuid}/rating/",
            json={"score": 0},
            headers=headers,
        ),
        await client.put(
            f"/theater/movies/{movie.uuid}/rating/",
            json={"score": 11},
            headers=headers,
        ),
        await client.put(
            f"/theater/movies/{movie.uuid}/rating/",
            json={"score": 8.5},
            headers=headers,
        ),
        await client.put(
            f"/theater/movies/{movie.uuid}/rating/",
            json={"score": True},
            headers=headers,
        ),
        await client.put(
            f"/theater/movies/{movie.uuid}/rating/",
            json={"score": 8, "unexpected": True},
            headers=headers,
        ),
    ]
    unknown_uuid = uuid4()
    unknown_summary_response = await client.get(
        f"/theater/movies/{unknown_uuid}/ratings/"
    )
    unknown_set_response = await client.put(
        f"/theater/movies/{unknown_uuid}/rating/",
        json={"score": 8},
        headers=headers,
    )

    assert all(response.status_code == 422 for response in invalid_responses)
    assert unknown_summary_response.status_code == 404
    assert unknown_set_response.status_code == 404
