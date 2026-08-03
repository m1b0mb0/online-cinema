from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Request

from src.utils import build_pagination

pytestmark = pytest.mark.unit


def create_request(query_string: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/items/",
            "raw_path": b"/items/",
            "query_string": query_string.encode(),
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }
    )


@pytest.mark.parametrize(
    ("page", "expected_prev_page", "expected_next_page"),
    [
        (1, None, 2),
        (2, 1, 3),
        (3, 2, None),
    ],
)
def test_build_pagination_creates_links_and_preserves_query_params(
    page,
    expected_prev_page,
    expected_next_page,
):
    request = create_request("page=1&per_page=10&search=drama&sort=name")

    pagination = build_pagination(
        request=request,
        page=page,
        per_page=10,
        total_items=25,
    )

    assert pagination["total_pages"] == 3
    assert pagination["total_items"] == 25

    for link_name, expected_page in (
        ("prev_page", expected_prev_page),
        ("next_page", expected_next_page),
    ):
        link = pagination[link_name]
        if expected_page is None:
            assert link is None
            continue

        assert parse_qs(urlparse(link).query) == {
            "page": [str(expected_page)],
            "per_page": ["10"],
            "search": ["drama"],
            "sort": ["name"],
        }


def test_build_pagination_handles_empty_result():
    pagination = build_pagination(
        request=create_request("page=1&per_page=20"),
        page=1,
        per_page=20,
        total_items=0,
    )

    assert pagination == {
        "prev_page": None,
        "next_page": None,
        "total_pages": 0,
        "total_items": 0,
    }
