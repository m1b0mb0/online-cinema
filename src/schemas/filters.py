from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, model_validator

from src.database.models.order import OrderStatusEnum
from src.database.models.payments import PaymentStatusEnum
from src.schemas.pagination import AdminPaginationParams, PaginationParams


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class MovieSortField(StrEnum):
    NEWEST = "newest"
    NAME = "name"
    YEAR = "year"
    PRICE = "price"
    IMDB = "imdb"
    POPULARITY = "popularity"


class CatalogEntityListParams(PaginationParams):
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

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CommentListParams(PaginationParams):
    per_page: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of comments per page.",
    )
    sort_order: SortOrder = Field(
        default=SortOrder.DESC,
        description="Sort direction based on comment creation time.",
    )


class MovieFilterParams(PaginationParams):
    per_page: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Number of movies per page.",
    )
    sort_by: MovieSortField = Field(
        default=MovieSortField.NEWEST,
        description=(
            "Movie field used for sorting. Popularity is based on IMDb votes."
        ),
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
            "Case-insensitive search by movie title, description, actor, "
            "or director."
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

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
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


class AdminFilterParams(AdminPaginationParams):
    user_id: int | None = Field(
        default=None,
        gt=0,
        description="Return records created by this user.",
    )
    date_from: date | None = Field(
        default=None,
        description="Minimum creation date in UTC, inclusive.",
    )
    date_to: date | None = Field(
        default=None,
        description="Maximum creation date in UTC, inclusive.",
    )

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from cannot be greater than date_to.")

        return self


class AdminOrderFilterParams(AdminFilterParams):
    status: OrderStatusEnum | None = Field(
        default=None,
        description="Return orders with this status.",
    )


class AdminPaymentFilterParams(AdminFilterParams):
    status: PaymentStatusEnum | None = Field(
        default=None,
        description="Return payments with this status.",
    )
