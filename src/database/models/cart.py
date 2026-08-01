from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base

if TYPE_CHECKING:
    from src.database.models.accounts import UserModel
    from src.database.models.movies import MovieModel


class CartModel(Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    user: Mapped["UserModel"] = relationship(back_populates="cart")
    items: Mapped[list["CartItemModel"]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
    )


class CartItemModel(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    cart: Mapped["CartModel"] = relationship(back_populates="items")
    movie: Mapped["MovieModel"] = relationship(back_populates="cart_items")

    __table_args__ = (
        UniqueConstraint(
            "cart_id",
            "movie_id",
            name="uq_cart_items_cart_id_movie_id",
        ),
        Index("ix_cart_items_movie_id", "movie_id"),
    )
