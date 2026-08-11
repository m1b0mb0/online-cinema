from datetime import datetime
from decimal import Decimal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
)

from src.database.models.payments import PaymentStatusEnum
from src.schemas.order import OrderMovieSchema
from src.schemas.pagination import PaginationResponseSchema


class PaymentOrderItemSchema(BaseModel):
    id: int
    price_at_order: Decimal = Field(ge=0)
    movie: OrderMovieSchema

    model_config = ConfigDict(from_attributes=True)


class PaymentItemResponseSchema(BaseModel):
    id: int
    price_at_payment: Decimal = Field(ge=0)
    order_item: PaymentOrderItemSchema

    model_config = ConfigDict(from_attributes=True)


class PaymentResponseSchema(BaseModel):
    id: int
    order_id: int
    created_at: datetime
    status: PaymentStatusEnum
    amount: Decimal = Field(ge=0)
    external_payment_id: str | None
    items_count: int = Field(ge=0)
    items: list[PaymentItemResponseSchema]

    model_config = ConfigDict(from_attributes=True)


class PaymentCheckoutResponseSchema(BaseModel):
    payment: PaymentResponseSchema
    checkout_url: AnyHttpUrl


class PaymentConfirmationResponseSchema(BaseModel):
    confirmed: bool
    message: str
    payment: PaymentResponseSchema


class PaymentListResponseSchema(PaginationResponseSchema):
    payments: list[PaymentResponseSchema]


class PaymentRefundRequestSchema(BaseModel):
    reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Optional reason for requesting a refund.",
    )

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class PaymentRefundResponseSchema(BaseModel):
    payment: PaymentResponseSchema
    refund_id: str
    refund_status: str


class PaymentWebhookResponseSchema(BaseModel):
    received: bool = True


class AdminPaymentUserSchema(BaseModel):
    id: int
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class AdminPaymentResponseSchema(PaymentResponseSchema):
    user: AdminPaymentUserSchema


class AdminPaymentListResponseSchema(PaginationResponseSchema):
    payments: list[AdminPaymentResponseSchema]
