from pydantic import BaseModel, ConfigDict, Field


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number.")
    per_page: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of items per page.",
    )

    model_config = ConfigDict(extra="forbid")


class AdminPaginationParams(PaginationParams):
    per_page: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of items per page.",
    )


class PaginationResponseSchema(BaseModel):
    prev_page: str | None
    next_page: str | None
    total_pages: int = Field(ge=0)
    total_items: int = Field(ge=0)
