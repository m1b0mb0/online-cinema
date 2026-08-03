from pydantic import BaseModel, Field


class PaginationResponseSchema(BaseModel):
    prev_page: str | None
    next_page: str | None
    total_pages: int = Field(ge=0)
    total_items: int = Field(ge=0)
