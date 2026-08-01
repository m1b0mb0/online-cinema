from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RatingRequestSchema(BaseModel):
    score: int = Field(
        ge=1,
        le=10,
        strict=True,
        description="Movie score on a 10-point scale.",
        examples=[8],
    )

    model_config = ConfigDict(extra="forbid")


class MovieRatingsSummarySchema(BaseModel):
    movie_uuid: UUID
    average_rating: float | None = Field(default=None, ge=1, le=10)
    ratings_count: int = Field(ge=0)


class CurrentMovieRatingsSchema(MovieRatingsSummarySchema):
    current_user_rating: int | None = Field(default=None, ge=1, le=10)
