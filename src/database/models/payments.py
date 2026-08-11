from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base

if TYPE_CHECKING:
    from src.database.models.accounts import UserModel
    from src.database.models.order import OrderItemModel, OrderModel


class PaymentStatusEnum(StrEnum):
    PENDING = "pending"
    SUCCESSFUL = "successful"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class PaymentModel(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    status: Mapped[PaymentStatusEnum] = mapped_column(
        Enum(
            PaymentStatusEnum,
            name="payment_status_enum",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=PaymentStatusEnum.PENDING,
        server_default=PaymentStatusEnum.PENDING.value,
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )
    external_payment_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
    )

    user: Mapped["UserModel"] = relationship(back_populates="payments")
    order: Mapped["OrderModel"] = relationship(back_populates="payments")
    items: Mapped[list["PaymentItemModel"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="check_payments_amount_non_negative",
        ),
        Index("ix_payments_user_created_at", "user_id", "created_at"),
        Index("ix_payments_order_id", "order_id"),
        Index("ix_payments_status_created_at", "status", "created_at"),
    )


class PaymentItemModel(Base):
    __tablename__ = "payment_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey(
            "payments.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey(
            "order_items.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    price_at_payment: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    payment: Mapped["PaymentModel"] = relationship(back_populates="items")
    order_item: Mapped["OrderItemModel"] = relationship(back_populates="payment_items")

    __table_args__ = (
        CheckConstraint(
            "price_at_payment >= 0",
            name="check_payment_items_price_at_payment_non_negative",
        ),
        UniqueConstraint(
            "payment_id",
            "order_item_id",
            name="unique_payment_items_payment_id_order_item_id",
        ),
        Index("ix_payment_items_order_item_id", "order_item_id"),
    )
