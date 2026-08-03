import math
from typing import TypedDict

from fastapi import Request


class PaginationData(TypedDict):
    prev_page: str | None
    next_page: str | None
    total_pages: int
    total_items: int


def build_pagination(
    request: Request,
    page: int,
    per_page: int,
    total_items: int,
) -> PaginationData:
    total_pages = math.ceil(total_items / per_page)
    prev_page = (
        str(
            request.url.include_query_params(
                page=page - 1,
                per_page=per_page,
            )
        )
        if page > 1
        else None
    )
    next_page = (
        str(
            request.url.include_query_params(
                page=page + 1,
                per_page=per_page,
            )
        )
        if page < total_pages
        else None
    )
    return {
        "prev_page": prev_page,
        "next_page": next_page,
        "total_pages": total_pages,
        "total_items": total_items,
    }
