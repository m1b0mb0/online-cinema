from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.schemas.movies import GenreSchema


class CartMovieSchema(BaseModel):
    uuid: UUID
    name: str
    year: int
    price: Decimal = Field(ge=0)
    genres: list[GenreSchema]

    model_config = ConfigDict(from_attributes=True)


class CartItemResponseSchema(BaseModel):
    id: int
    added_at: datetime
    movie: CartMovieSchema

    model_config = ConfigDict(from_attributes=True)


class CartResponseSchema(BaseModel):
    id: int
    items: list[CartItemResponseSchema]
    items_count: int = Field(ge=0)
    total_amount: Decimal = Field(ge=0)

    model_config = ConfigDict(from_attributes=True)


class AdminCartUserSchema(BaseModel):
    id: int
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class AdminCartSummarySchema(BaseModel):
    id: int
    user: AdminCartUserSchema
    items_count: int = Field(ge=0)
    total_amount: Decimal = Field(ge=0)

    model_config = ConfigDict(from_attributes=True)


class AdminCartListResponseSchema(BaseModel):
    carts: list[AdminCartSummarySchema]
    prev_page: str | None
    next_page: str | None
    total_pages: int = Field(ge=0)
    total_items: int = Field(ge=0)


class AdminCartDetailResponseSchema(AdminCartSummarySchema):
    items: list[CartItemResponseSchema]
