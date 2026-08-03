from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.pagination import PaginationResponseSchema


class CommentSortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class CommentListParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number.")
    per_page: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of comments per page.",
    )
    sort_order: CommentSortOrder = Field(
        default=CommentSortOrder.DESC,
        description="Sort direction based on comment creation time.",
    )

    model_config = ConfigDict(extra="forbid")


class CommentContentSchema(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=5000,
        description="Comment text.",
        examples=["A thoughtful comment about the movie."],
    )

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class CommentCreateSchema(CommentContentSchema):
    pass


class CommentUpdateSchema(CommentContentSchema):
    pass


class CommentAuthorSchema(BaseModel):
    id: int
    first_name: str | None
    last_name: str | None
    avatar: str | None


class CommentSchema(BaseModel):
    uuid: UUID
    movie_uuid: UUID
    parent_uuid: UUID | None
    content: str
    author: CommentAuthorSchema
    created_at: datetime
    updated_at: datetime
    replies_count: int = Field(ge=0)


class CommentListResponseSchema(PaginationResponseSchema):
    comments: list[CommentSchema]
