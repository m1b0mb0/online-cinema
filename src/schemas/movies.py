from enum import StrEnum
from typing import Annotated
from uuid import UUID
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MovieSortField(StrEnum):
    NEWEST = "newest"
    NAME = "name"
    YEAR = "year"
    PRICE = "price"
    IMDB = "imdb"
    POPULARITY = "popularity"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class CatalogEntityListParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
    search: str | None = Field(default=None, min_length=1, max_length=100)


class MovieFilterParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=10, ge=1, le=20)

    sort_by: MovieSortField = MovieSortField.NEWEST
    sort_order: SortOrder = SortOrder.DESC

    search: str | None = Field(default=None, min_length=1, max_length=100)

    years: list[int] | None = None
    year_from: int | None = Field(default=None, gt=0)
    year_to: int | None = Field(default=None, gt=0)

    imdb_min: float | None = Field(default=None, ge=0, le=10)
    imdb_max: float | None = Field(default=None, ge=0, le=10)

    price_min: Decimal | None = Field(default=None, ge=0)
    price_max: Decimal | None = Field(default=None, ge=0)

    genre_ids: list[int] | None = None
    certification_ids: list[int] | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "MovieFilterParams":
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from cannot be greater than year_to.")

        if (
            self.imdb_min is not None
            and self.imdb_max is not None
            and self.imdb_min > self.imdb_max
        ):
            raise ValueError("imdb_min cannot be greater than imdb_max.")

        if (
            self.price_min is not None
            and self.price_max is not None
            and self.price_min > self.price_max
        ):
            raise ValueError("price_min cannot be greater than price_max.")

        return self


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
    name: str = Field(min_length=1, max_length=100)

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
    movie_count: int


class GenreListResponseSchema(BaseModel):
    genres: list[GenreMovieCountSchema]
    prev_page: str | None
    next_page: str | None
    page: int
    per_page: int
    total_pages: int
    total_items: int


class ActorListResponseSchema(BaseModel):
    actors: list[StarSchema]
    prev_page: str | None
    next_page: str | None
    page: int
    per_page: int
    total_pages: int
    total_items: int


class MovieBaseSchema(BaseModel):
    name: str = Field(max_length=250)
    year: int = Field(gt=0)
    time: int = Field(gt=0)
    imdb: float = Field(ge=0, le=10)
    votes: int = Field(ge=0)
    meta_score: float | None = Field(default=None, ge=0, le=100)
    gross: float | None = Field(default=None, ge=0)
    description: str
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

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


class MovieListResponseSchema(BaseModel):
    movies: list[MovieListItemSchema]
    prev_page: str | None
    next_page: str | None
    total_pages: int
    total_items: int


StarName = Annotated[str, Field(max_length=100)]
DirectorName = Annotated[str, Field(max_length=100)]
GenreName = Annotated[str, Field(max_length=100)]


class MovieCreateSchema(MovieBaseSchema):
    certification: str = Field(max_length=100)
    stars: list[StarName]
    genres: list[GenreName]
    directors: list[DirectorName]

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
