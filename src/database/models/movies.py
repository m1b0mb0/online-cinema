from uuid import UUID, uuid4
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)

from src.database.models.base import Base

if TYPE_CHECKING:
    from src.database.models.comments import CommentModel
    from src.database.models.favorites import FavoriteModel
    from src.database.models.reactions import MovieReactionModel
    from src.database.models.ratings import MovieRatingModel
    from src.database.models.cart import CartItemModel

MovieStarsModel = Table(
    "movie_stars",
    Base.metadata,
    Column(
        "movie_id",
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    Column(
        "star_id",
        ForeignKey("stars.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)


MovieGenresModel = Table(
    "movie_genres",
    Base.metadata,
    Column(
        "movie_id",
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    Column(
        "genre_id",
        ForeignKey("genres.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)


MovieDirectorsModel = Table(
    "movie_directors",
    Base.metadata,
    Column(
        "movie_id",
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    Column(
        "director_id",
        ForeignKey("directors.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)


class CertificationModel(Base):
    __tablename__ = "certifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    movies: Mapped[list["MovieModel"]] = relationship(back_populates="certification")


class StarModel(Base):
    __tablename__ = "stars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    movies: Mapped[list["MovieModel"]] = relationship(
        secondary=MovieStarsModel, back_populates="stars"
    )


class GenreModel(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    movies: Mapped[list["MovieModel"]] = relationship(
        secondary=MovieGenresModel, back_populates="genres"
    )


class DirectorModel(Base):
    __tablename__ = "directors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    movies: Mapped[list["MovieModel"]] = relationship(
        secondary=MovieDirectorsModel, back_populates="directors"
    )


class MovieModel(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[UUID] = mapped_column(Uuid, unique=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[int] = mapped_column(Integer, nullable=False)
    imdb: Mapped[float] = mapped_column(Float, nullable=False)
    votes: Mapped[int] = mapped_column(Integer, nullable=False)
    meta_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    certification_id: Mapped[int] = mapped_column(
        ForeignKey("certifications.id", ondelete="RESTRICT"), nullable=False
    )
    certification: Mapped["CertificationModel"] = relationship(back_populates="movies")
    stars: Mapped[list["StarModel"]] = relationship(
        secondary=MovieStarsModel, back_populates="movies"
    )
    genres: Mapped[list["GenreModel"]] = relationship(
        secondary=MovieGenresModel, back_populates="movies"
    )
    directors: Mapped[list["DirectorModel"]] = relationship(
        secondary=MovieDirectorsModel, back_populates="movies"
    )

    favorite_entries: Mapped[list["FavoriteModel"]] = relationship(
        back_populates="movie",
        cascade="all, delete-orphan",
    )
    reactions: Mapped[list["MovieReactionModel"]] = relationship(
        back_populates="movie",
        cascade="all, delete-orphan",
    )
    comments: Mapped[list["CommentModel"]] = relationship(
        back_populates="movie",
        cascade="all, delete-orphan",
    )
    ratings: Mapped[list["MovieRatingModel"]] = relationship(
        back_populates="movie",
        cascade="all, delete-orphan",
    )
    cart_items: Mapped[list["CartItemModel"]] = relationship(
        back_populates="movie",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("name", "year", "time", name="unique_movie_constraint"),
        CheckConstraint("year > 0", name="check_movie_year_positive"),
        CheckConstraint("time > 0", name="check_movie_time_positive"),
        CheckConstraint("votes >= 0", name="check_movie_votes_non_negative"),
        CheckConstraint("price >= 0", name="check_movie_price_non_negative"),
        CheckConstraint("gross >= 0", name="check_movie_gross_non_negative"),
        CheckConstraint("imdb >= 0 AND imdb <= 10", name="check_movie_imdb_range"),
        CheckConstraint(
            "meta_score >= 0 AND meta_score <= 100", name="check_movie_meta_score_range"
        ),
    )
