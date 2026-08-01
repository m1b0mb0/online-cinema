from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base

if TYPE_CHECKING:
    from src.database.models.accounts import UserModel
    from src.database.models.comments import CommentModel
    from src.database.models.movies import MovieModel


class ReactionTypeEnum(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"


class ReactionMixin:
    reaction_type: Mapped[ReactionTypeEnum] = mapped_column(
        Enum(
            ReactionTypeEnum,
            name="reaction_type_enum",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MovieReactionModel(ReactionMixin, Base):
    __tablename__ = "movie_reactions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )

    user: Mapped["UserModel"] = relationship(back_populates="movie_reactions")
    movie: Mapped["MovieModel"] = relationship(back_populates="reactions")

    __table_args__ = (
        Index(
            "ix_movie_reactions_movie_type",
            "movie_id",
            "reaction_type",
        ),
    )


class CommentReactionModel(ReactionMixin, Base):
    __tablename__ = "comment_reactions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    comment_id: Mapped[int] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True
    )

    user: Mapped["UserModel"] = relationship(back_populates="comment_reactions")
    comment: Mapped["CommentModel"] = relationship(back_populates="reactions")

    __table_args__ = (
        Index(
            "ix_comment_reactions_comment_type",
            "comment_id",
            "reaction_type",
        ),
    )
