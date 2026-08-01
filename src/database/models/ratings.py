from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base

if TYPE_CHECKING:
    from src.database.models.accounts import UserModel
    from src.database.models.movies import MovieModel


class MovieRatingModel(Base):
    __tablename__ = "ratings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    user: Mapped["UserModel"] = relationship(back_populates="ratings")
    movie: Mapped["MovieModel"] = relationship(back_populates="ratings")

    __table_args__ = (
        CheckConstraint(
            "score >= 1 AND score <= 10",
            name="check_movie_score_range",
        ),
        Index("ix_ratings_movie_id", "movie_id"),
    )
