from datetime import datetime
from typing import Optional, TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base

if TYPE_CHECKING:
    from src.database.models.accounts import UserModel
    from src.database.models.movies import MovieModel
    from src.database.models.reactions import CommentReactionModel


class CommentModel(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[UUID] = mapped_column(
        Uuid,
        unique=True,
        default=uuid4,
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
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

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
    )

    user: Mapped["UserModel"] = relationship(back_populates="comments")
    movie: Mapped["MovieModel"] = relationship(back_populates="comments")
    parent: Mapped[Optional["CommentModel"]] = relationship(
        back_populates="replies",
        remote_side="CommentModel.id",
    )
    replies: Mapped[list["CommentModel"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    reactions: Mapped[list["CommentReactionModel"]] = relationship(
        back_populates="comment",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(content)) > 0",
            name="check_comment_content_not_blank",
        ),
        Index(
            "ix_comments_movie_created_at",
            "movie_id",
            "created_at",
        ),
        Index(
            "ix_comments_parent_created_at",
            "parent_id",
            "created_at",
        ),
    )
