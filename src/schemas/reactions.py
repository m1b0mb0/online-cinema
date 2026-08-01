from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.database.models.reactions import ReactionTypeEnum


class ReactionRequestSchema(BaseModel):
    reaction_type: ReactionTypeEnum = Field(
        description="Reaction to set for the current user.",
        examples=[ReactionTypeEnum.LIKE],
    )

    model_config = ConfigDict(extra="forbid")


class ReactionSummarySchema(BaseModel):
    likes_count: int = Field(ge=0)
    dislikes_count: int = Field(ge=0)


class MovieReactionSummarySchema(ReactionSummarySchema):
    movie_uuid: UUID


class CurrentMovieReactionSchema(MovieReactionSummarySchema):
    current_user_reaction: ReactionTypeEnum | None


class CommentReactionSummarySchema(ReactionSummarySchema):
    comment_uuid: UUID


class CurrentCommentReactionSchema(CommentReactionSummarySchema):
    current_user_reaction: ReactionTypeEnum | None
