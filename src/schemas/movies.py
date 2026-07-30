from enum import StrEnum
from datetime import datetime
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

    page: int = Field(default=1, ge=1, description="Page number.")
    per_page: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of catalog entities per page.",
    )
    search: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Case-insensitive partial name search.",
    )


class MovieFilterParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    page: int = Field(default=1, ge=1, description="Page number.")
    per_page: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Number of movies per page.",
    )

    sort_by: MovieSortField = Field(
        default=MovieSortField.NEWEST,
        description="Movie field used for sorting. Popularity is based on IMDb votes.",
    )
    sort_order: SortOrder = Field(
        default=SortOrder.DESC,
        description="Ascending or descending sort direction.",
    )

    search: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description=(
            "Case-insensitive search by movie title, description, actor, or director."
        ),
    )

    years: list[int] | None = Field(
        default=None,
        description="Exact release years. May be provided multiple times.",
    )
    year_from: int | None = Field(
        default=None,
        gt=0,
        description="Minimum release year, inclusive.",
    )
    year_to: int | None = Field(
        default=None,
        gt=0,
        description="Maximum release year, inclusive.",
    )

    imdb_min: float | None = Field(
        default=None,
        ge=0,
        le=10,
        description="Minimum IMDb rating, inclusive.",
    )
    imdb_max: float | None = Field(
        default=None,
        ge=0,
        le=10,
        description="Maximum IMDb rating, inclusive.",
    )

    price_min: Decimal | None = Field(
        default=None,
        ge=0,
        description="Minimum purchase price, inclusive.",
    )
    price_max: Decimal | None = Field(
        default=None,
        ge=0,
        description="Maximum purchase price, inclusive.",
    )

    genre_ids: list[int] | None = Field(
        default=None,
        description="Genre identifiers. A movie may match any provided genre.",
    )
    certification_ids: list[int] | None = Field(
        default=None,
        description="Accepted certification identifiers.",
    )

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


class MovieListResponseSchema(BaseModel):
    movies: list[MovieListItemSchema]
    prev_page: str | None
    next_page: str | None
    total_pages: int
    total_items: int


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
