from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.database.models.reactions import ReactionTypeEnum


class ReactionRequestSchema(BaseModel):
    reaction_type: ReactionTypeEnum = Field(
        description="Reaction to set for the current user.",
        examples=[ReactionTypeEnum.LIKE],
    )

    model_config = ConfigDict(extra="forbid")


class MovieReactionSummarySchema(BaseModel):
    movie_uuid: UUID
    likes_count: int = Field(ge=0)
    dislikes_count: int = Field(ge=0)


class CurrentMovieReactionSchema(MovieReactionSummarySchema):
    current_user_reaction: ReactionTypeEnum | None
