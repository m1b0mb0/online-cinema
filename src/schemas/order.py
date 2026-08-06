from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.database.models.order import OrderStatusEnum
from src.schemas.pagination import PaginationResponseSchema


class OrderMovieSchema(BaseModel):
    uuid: UUID
    name: str
    year: int

    model_config = ConfigDict(from_attributes=True)


class OrderExclusionReasonEnum(StrEnum):
    ALREADY_PURCHASED = "already_purchased"
    ALREADY_PENDING = "already_pending"
    UNAVAILABLE = "unavailable"


class ExcludedOrderMovieSchema(BaseModel):
    movie: OrderMovieSchema
    reason: OrderExclusionReasonEnum
    detail: str


class OrderItemResponseSchema(BaseModel):
    id: int
    price_at_order: Decimal = Field(ge=0)
    movie: OrderMovieSchema

    model_config = ConfigDict(from_attributes=True)


class OrderResponseSchema(BaseModel):
    id: int
    created_at: datetime
    status: OrderStatusEnum
    total_amount: Decimal = Field(ge=0)
    items_count: int = Field(ge=0)
    items: list[OrderItemResponseSchema]

    model_config = ConfigDict(from_attributes=True)


class OrderCreateResponseSchema(OrderResponseSchema):
    excluded_movies: list[ExcludedOrderMovieSchema] = Field(default_factory=list)


class OrderListResponseSchema(PaginationResponseSchema):
    orders: list[OrderResponseSchema]
