from typing import Optional
from uuid import UUID
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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


class MovieBaseSchema(BaseModel):
    name: str = Field(max_length=250)
    year: int = Field(ge=0)
    time: int = Field(ge=0)
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
    prev_page: Optional[str]
    next_page: Optional[str]
    total_pages: int
    total_items: int
