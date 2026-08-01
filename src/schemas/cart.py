from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
