from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

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


class AdminOrderFilterParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number.")
    per_page: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of orders per page.",
    )
    user_id: int | None = Field(
        default=None,
        gt=0,
        description="Return orders created by this user.",
    )
    date_from: date | None = Field(
        default=None,
        description="Minimum order creation date in UTC, inclusive.",
    )
    date_to: date | None = Field(
        default=None,
        description="Maximum order creation date in UTC, inclusive.",
    )
    status: OrderStatusEnum | None = Field(
        default=None,
        description="Return orders with this status.",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_date_range(self) -> "AdminOrderFilterParams":
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from cannot be greater than date_to.")

        return self


class AdminOrderUserSchema(BaseModel):
    id: int
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class AdminOrderResponseSchema(OrderResponseSchema):
    user: AdminOrderUserSchema


class AdminOrderListResponseSchema(PaginationResponseSchema):
    orders: list[AdminOrderResponseSchema]
