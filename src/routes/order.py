from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import (
    UserModel,
    CartModel,
    CartItemModel,
    OrderModel,
    OrderItemModel,
    OrderStatusEnum,
    get_db,
)
from src.schemas import (
    OrderCreateResponseSchema,
    OrderListResponseSchema,
    OrderResponseSchema,
    ExcludedOrderMovieSchema,
    OrderExclusionReasonEnum,
    PaginationParams,
)
from src.security.dependencies import get_current_active_user
from src.utils import build_pagination

router = APIRouter()

AUTH_RESPONSES = {
    401: {"description": "Access token is missing or invalid."},
    403: {"description": "User account is not activated."},
}


@router.post(
    "/orders/",
    response_model=OrderCreateResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Order From Cart",
    description=(
        "Create a pending order from every eligible movie in the current "
        "user's cart."
    ),
    response_description="Created pending order with price snapshots.",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "Shopping cart is empty."},
        409: {"description": "The cart contains no movies eligible for ordering."},
    },
)
async def create_order_from_cart(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
) -> OrderCreateResponseSchema:
    cart = await db.scalar(
        select(CartModel)
        .where(CartModel.user_id == current_user.id)
        .options(selectinload(CartModel.items).selectinload(CartItemModel.movie))
        .with_for_update()
    )

    if cart is None or not cart.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Shopping cart is empty."
        )

    cart_movie_ids = [item.movie.id for item in cart.items]

    rows = (
        await db.execute(
            select(OrderItemModel.movie_id, OrderModel.status)
            .join(OrderModel)
            .where(
                OrderModel.user_id == current_user.id,
                OrderItemModel.movie_id.in_(cart_movie_ids),
                OrderModel.status.in_([OrderStatusEnum.PAID, OrderStatusEnum.PENDING]),
            )
        )
    ).all()

    purchased_ids = {
        movie_id
        for movie_id, order_status in rows
        if order_status == OrderStatusEnum.PAID
    }

    pending_ids = {
        movie_id
        for movie_id, order_status in rows
        if order_status == OrderStatusEnum.PENDING
    }

    excluded_movies = []
    eligible_items = []
    for item in cart.items:
        if item.movie_id in purchased_ids:
            excluded_movies.append(
                ExcludedOrderMovieSchema(
                    movie=item.movie,
                    reason=OrderExclusionReasonEnum.ALREADY_PURCHASED,
                    detail="The movie has already been purchased.",
                )
            )
        elif item.movie_id in pending_ids:
            excluded_movies.append(
                ExcludedOrderMovieSchema(
                    movie=item.movie,
                    reason=OrderExclusionReasonEnum.ALREADY_PENDING,
                    detail="This movie is already included in a pending order.",
                )
            )
        else:
            eligible_items.append(item)

    if not eligible_items:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The cart contains no movies eligible for ordering.",
        )

    order_items = [
        OrderItemModel(movie=item.movie, price_at_order=item.movie.price)
        for item in eligible_items
    ]

    total_amount = sum(
        (item.price_at_order for item in order_items), start=Decimal("0.00")
    )

    order = OrderModel(
        user_id=current_user.id,
        status=OrderStatusEnum.PENDING,
        total_amount=total_amount,
        items=order_items,
    )

    try:
        db.add(order)
        await db.flush()
        await db.execute(delete(CartItemModel).where(CartItemModel.cart_id == cart.id))
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise

    return OrderCreateResponseSchema(
        id=order.id,
        created_at=order.created_at,
        status=order.status,
        total_amount=order.total_amount,
        items_count=len(order.items),
        items=order.items,
        excluded_movies=excluded_movies,
    )


@router.get(
    "/orders/",
    response_model=OrderListResponseSchema,
    summary="List Current User Orders",
    description="Return the current user's paginated order history.",
    response_description="Paginated order history.",
    responses=AUTH_RESPONSES,
)
async def get_current_user_orders(
    request: Request,
    params: Annotated[PaginationParams, Query()],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
) -> OrderListResponseSchema:
    total_items = await db.scalar(
        select(func.count(OrderModel.id)).where(OrderModel.user_id == current_user.id)
    )

    offset = (params.page - 1) * params.per_page
    statement = (
        select(OrderModel)
        .where(OrderModel.user_id == current_user.id)
        .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        .order_by(OrderModel.created_at.desc(), OrderModel.id.desc())
        .offset(offset)
        .limit(params.per_page)
    )

    orders = (await db.scalars(statement)).all()

    order_responses = []
    for order in orders:
        order_responses.append(
            OrderResponseSchema(
                id=order.id,
                created_at=order.created_at,
                status=order.status,
                total_amount=order.total_amount,
                items_count=len(order.items),
                items=order.items,
            )
        )

    pagination = build_pagination(
        request=request,
        page=params.page,
        per_page=params.per_page,
        total_items=total_items,
    )

    return OrderListResponseSchema(
        orders=order_responses,
        **pagination,
    )


@router.get(
    "/orders/{order_id}/",
    response_model=OrderResponseSchema,
    summary="Get Current User Order",
    description="Return one order owned by the current user.",
    response_description="Detailed order with its movie price snapshots.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Order was not found."},
    },
)
async def get_current_user_order(
    order_id: int = Path(gt=0, description="Order identifier."),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
) -> OrderResponseSchema:
    order = await db.scalar(
        select(OrderModel)
        .where(OrderModel.id == order_id, OrderModel.user_id == current_user.id)
        .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
    )

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order was not found."
        )

    return OrderResponseSchema(
        id=order.id,
        created_at=order.created_at,
        status=order.status,
        total_amount=order.total_amount,
        items_count=len(order.items),
        items=order.items,
    )


@router.post(
    "/orders/{order_id}/cancel/",
    response_model=OrderResponseSchema,
    summary="Cancel Pending Order",
    description="Cancel an order owned by the current user before it is paid.",
    response_description="Canceled order.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Order was not found."},
        409: {"description": "Only a pending order can be canceled."},
    },
)
async def cancel_current_user_order(
    order_id: int = Path(gt=0, description="Order identifier."),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
) -> OrderResponseSchema:
    order = await db.scalar(
        select(OrderModel)
        .where(OrderModel.id == order_id, OrderModel.user_id == current_user.id)
        .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        .with_for_update()
    )

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order was not found."
        )

    if order.status != OrderStatusEnum.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a pending order can be canceled.",
        )

    try:
        order.status = OrderStatusEnum.CANCELED
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise

    return OrderResponseSchema(
        id=order.id,
        created_at=order.created_at,
        status=order.status,
        total_amount=order.total_amount,
        items_count=len(order.items),
        items=order.items,
    )
