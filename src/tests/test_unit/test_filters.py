from datetime import date

import pytest
from pydantic import ValidationError

from src.database import OrderStatusEnum, PaymentStatusEnum
from src.schemas.filters import (
    AdminOrderFilterParams,
    AdminPaymentFilterParams,
    CommentListParams,
    MovieFilterParams,
    SortOrder,
)
from src.schemas.pagination import PaginationParams

pytestmark = pytest.mark.unit


def test_pagination_params_provide_shared_user_list_defaults():
    params = PaginationParams()

    assert params.page == 1
    assert params.per_page == 10


@pytest.mark.parametrize(
    "filter_schema",
    [AdminOrderFilterParams, AdminPaymentFilterParams],
)
def test_admin_filters_share_date_range_validation(filter_schema):
    with pytest.raises(ValidationError, match="date_from cannot be greater"):
        filter_schema(
            date_from=date(2026, 8, 2),
            date_to=date(2026, 8, 1),
        )


def test_admin_filters_keep_domain_specific_status_types():
    order_filters = AdminOrderFilterParams(status="paid")
    payment_filters = AdminPaymentFilterParams(status="successful")

    assert order_filters.status == OrderStatusEnum.PAID
    assert payment_filters.status == PaymentStatusEnum.SUCCESSFUL

    with pytest.raises(ValidationError):
        AdminPaymentFilterParams(status="paid")


def test_comments_and_movies_use_shared_sort_order():
    comment_params = CommentListParams(sort_order="asc")
    movie_params = MovieFilterParams(sort_order="asc")

    assert comment_params.sort_order == SortOrder.ASC
    assert movie_params.sort_order == SortOrder.ASC
