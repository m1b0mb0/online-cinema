from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.pagination import PaginationResponseSchema


class CertificationSchema(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class StarSchema(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class GenreSchema(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class DirectorSchema(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class NamedCatalogEntityRequestSchema(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
        description="Unique catalog entity name.",
        examples=["Drama"],
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class GenreRequestSchema(NamedCatalogEntityRequestSchema):
    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.title()


class ActorRequestSchema(NamedCatalogEntityRequestSchema):
    pass


class GenreMovieCountSchema(BaseModel):
    id: int
    name: str
    movie_count: int = Field(description="Number of movies assigned to this genre.")


class GenreListResponseSchema(PaginationResponseSchema):
    genres: list[GenreMovieCountSchema]


class ActorListResponseSchema(PaginationResponseSchema):
    actors: list[StarSchema]


class MovieBaseSchema(BaseModel):
    name: str = Field(max_length=250, description="Movie title.")
    year: int = Field(gt=0, description="Release year.")
    time: int = Field(gt=0, description="Runtime in minutes.")
    imdb: float = Field(ge=0, le=10, description="IMDb rating from 0 to 10.")
    votes: int = Field(ge=0, description="Number of IMDb votes.")
    meta_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Optional Metascore from 0 to 100.",
    )
    gross: float | None = Field(
        default=None,
        ge=0,
        description="Optional gross revenue.",
    )
    description: str = Field(description="Movie synopsis.")
    price: Decimal = Field(
        ge=0,
        max_digits=10,
        decimal_places=2,
        description="Purchase price with two decimal places.",
    )

    model_config = ConfigDict(from_attributes=True)


class MovieDetailSchema(MovieBaseSchema):
    id: int
    uuid: UUID
    certification: CertificationSchema
    stars: list[StarSchema]
    genres: list[GenreSchema]
    directors: list[DirectorSchema]

    model_config = ConfigDict(from_attributes=True)


class MovieListItemSchema(BaseModel):
    id: int
    uuid: UUID
    name: str
    year: int
    time: int
    imdb: float
    votes: int
    description: str

    model_config = ConfigDict(from_attributes=True)


class MovieListResponseSchema(PaginationResponseSchema):
    movies: list[MovieListItemSchema]


class FavoriteResponseSchema(BaseModel):
    added_at: datetime
    movie: MovieListItemSchema

    model_config = ConfigDict(from_attributes=True)


StarName = Annotated[str, Field(max_length=100)]
DirectorName = Annotated[str, Field(max_length=100)]
GenreName = Annotated[str, Field(max_length=100)]


class MovieCreateSchema(MovieBaseSchema):
    certification: str = Field(max_length=100, description="Certification name.")
    stars: list[StarName] = Field(description="Actor names.")
    genres: list[GenreName] = Field(description="Genre names.")
    directors: list[DirectorName] = Field(description="Director names.")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("stars", "genres", "directors", mode="before")
    @classmethod
    def normalize_list_fields(cls, value: list[str]) -> list[str]:
        return [item.title() for item in value]


class MovieUpdateSchema(BaseModel):
    name: str | None = Field(default=None, max_length=250)
    year: int | None = Field(default=None, gt=0)
    time: int | None = Field(default=None, gt=0)
    imdb: float | None = Field(default=None, ge=0, le=10)
    votes: int | None = Field(default=None, ge=0)
    meta_score: float | None = Field(default=None, ge=0, le=100)
    gross: float | None = Field(default=None, ge=0)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    certification: str | None = Field(default=None, min_length=1, max_length=100)
    stars: list[StarName] | None = None
    genres: list[GenreName] | None = None
    directors: list[DirectorName] | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("stars", "genres", "directors", mode="before")
    @classmethod
    def normalize_list_fields(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value

        return [item.title() for item in value]
